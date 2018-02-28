# encoding: utf-8
import logging
import requests

from datetime import datetime
from datetime import timedelta
from urlparse import urlparse, urlunparse, urljoin

from google.appengine.api import urlfetch
from google.appengine.ext.deferred import deferred
from google.appengine.ext import ndb

from flask import Flask, render_template, request, redirect
from flask_caching import Cache
from furl import furl
from lxml import html, etree
from user_agent import generate_user_agent
from werkzeug.http import http_date

import requests_toolbelt.adapters.appengine
requests_toolbelt.adapters.appengine.monkeypatch()

HTTP_REQUEST_TIMEOUT = 10

# 12 hours
CACHE_TIMEOUT = 12 * 60 * 60

# 1 hours
CDN_CACHE_TIMEOUT = 60 * 60

app = Flask(__name__)
app.config['CACHE_TYPE'] = 'gaememcached'
app.config['CACHE_KEY_PREFIX'] = ''

cache = Cache(app)


class Feed(ndb.Model):
    title = ndb.StringProperty()
    url = ndb.StringProperty()
    keyword = ndb.StringProperty()
    content = ndb.JsonProperty()
    last_update = ndb.DateTimeProperty()

    def __repr__(self):
        return '<Topic %r updated at %r>' % (self.keyword, self.last_update)


def feed_key(keyword):
    return ndb.Key(Feed, keyword)


def cache_key(keyword=None):
    if not keyword:
        keyword = request.args.get('t')

    safe_key = feed_key(keyword).urlsafe()

    key = u'feed/%s' % safe_key
    logging.info('cache_key %s', key)

    return key


def render_feed(feed):
    response = render_template('rss_tpl.xml', feed=feed)
    return response, 200, {
        'Content-Type': 'application/rss+xml',
        'Last-Modified': http_date(feed.last_update),
        # 'Cache-Control': 'public, max-age=%d' % CDN_CACHE_TIMEOUT,
        'Expires': http_date(feed.last_update + timedelta(seconds=CDN_CACHE_TIMEOUT))
    }


def fetch_feed(keyword, url_with_paging=None):
    with requests.Session() as s:
        s.headers.update({
            'User-Agent': generate_user_agent()
        })

        if url_with_paging:
            page = s.get(url_with_paging)
        else:
            page = s.get('https://eksisozluk.com/', params={'q': keyword})

        tree = html.fromstring(page.content)
        url = page.url

        # get last page
        pager = tree.xpath('//*[@class="pager"]/@data-pagecount')
        if len(pager) > 0:
            last_page_number = tree.xpath('//*[@class="pager"]/@data-pagecount')[0]
            current_page_number = tree.xpath('//*[@class="pager"]/@data-currentpage')[0]

            if last_page_number != current_page_number:
                paging_replaced_url = furl(url).remove('p').add({'p': last_page_number}).url

                page = s.get(paging_replaced_url)
                tree = html.fromstring(page.content)
                url = page.url

    feed = create_feed_from_page(tree, keyword, url)
    feed.put()

    return feed


def create_feed_from_page(tree, keyword, url):
    topic_feed = Feed()
    topic_feed.key = feed_key(keyword)
    topic_feed.title = tree.xpath('//*[@id="title"]/a/span/text()')[0]
    topic_feed.url = url
    topic_feed.keyword = keyword

    entries = [etree.tostring(fix_links(entry)) for entry in tree.xpath('//*[@id="entry-item-list"]/li/div[1]')][::-1]
    links = tree.xpath('//*[@class="entry-date permalink"]/@href')[::-1]
    authors = tree.xpath('//*[@class="entry-author"]/text()')[::-1]
    dates = [datetime.strptime(date.split(' ~ ')[0], "%d.%m.%Y %H:%M") for date in
             tree.xpath('//*[@class="entry-date permalink"]/text()')][::-1]
    topic_feed.content = {
        'entries': entries,
        'links': links,
        'authors': authors,
        'dates': [d.strftime("%a, %d %b %Y %H:%M:%S") for d in dates]
    }
    topic_feed.last_update = datetime.now()

    # if there are no entries, some entries might be deleted and we are requesting wrong page
    # Here we are overriding url so on the next job run, it will work
    if not entries:
        load_more_link = tree.xpath('//*[@id="topic"]/a/@href')
        if load_more_link:
            load_more_link = load_more_link[0].lstrip('/')
            topic_feed.url = 'https://eksisozluk.com/{0}'.format(load_more_link)

    return topic_feed


def fix_links(tree):
    for node in tree.xpath('//a[@href]'):
        href = node.get('href')
        if href.startswith('http://') or href.startswith('https://'):
            continue

        url = urljoin('https://eksisozluk.com', href)
        node.set('href', url)

    return tree


def fill_cache_for_key(key):
    feed = key.get()
    if not feed:
        return

    with app.app_context():
        feed = fetch_feed(feed.keyword, url_with_paging=feed.url)
        response = render_feed(feed)

        logging.info('filling cache for %s', feed.keyword)
        cache.set(cache_key(feed.keyword), response, timeout=CACHE_TIMEOUT)

        # schedule again
        add_feed_to_task_queue(key)


def add_feed_to_task_queue(key):
    deferred.defer(fill_cache_for_key, key, _queue="feed-queue")


def last_hit_key(keyword):
    safe_key = feed_key(keyword).urlsafe()
    key = u'feed/%s/last_hit' % safe_key
    return key


def update_last_hit(keyword):
    key = last_hit_key(keyword)
    cache.set(key, datetime.now(), timeout=25 * 60 * 60)


def find_last_hit(keyword):
    key = last_hit_key(keyword)
    return cache.get(key)


@app.route('/')
def main():
    return render_template('main.html')


@app.route('/tasks/fix-missing')
def fix_missing_tasks():
    # some tasks were not placed in queue in 24 hours
    one_day_ago = datetime.now() - timedelta(days=1)
    for key in Feed.query(Feed.last_update < one_day_ago).iter(keys_only=True):
        add_feed_to_task_queue(key)

    return "ok"


@app.route('/tasks/clear-db')
def clear_db():
    one_day_ago = datetime.now() - timedelta(days=1)
    keys_to_delete = []
    for key in Feed.query().iter(keys_only=True):
        last_hit = find_last_hit(key.id())
        if not last_hit or last_hit < one_day_ago:
            logging.info('deleting %s from db', key.id())
            keys_to_delete.append(key)

    if not keys_to_delete:
        logging.warn('nothing to delete')

    ndb.delete_multi(keys_to_delete)
    return str(len(keys_to_delete))


@app.route('/feed/')
@cache.cached(key_prefix=cache_key, timeout=CACHE_TIMEOUT)
def get_feed():
    keyword = request.args.get('t')
    logging.info('cache not found for %s', keyword)

    # try loading from data store first
    feed = feed_key(keyword).get()
    if not feed:
        feed = fetch_feed(keyword)
        # first time
        add_feed_to_task_queue(feed.key)
    return render_feed(feed)


@app.before_request
def redirect_nonwww():
    urlfetch.set_default_fetch_deadline(HTTP_REQUEST_TIMEOUT)
    if request.path.startswith('/tasks/'):
        return

    """Redirect non-www requests to www."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == 'eksirss.appspot.com':
        urlparts_list = list(urlparts)
        urlparts_list[1] = 'eksirss.muratcorlu.com'
        return redirect(urlunparse(urlparts_list), code=301)


@app.after_request
def after_request(response):
    if get_feed.__name__ == request.endpoint:
        update_last_hit(request.args.get('t'))

    return response


@app.errorhandler(500)
def server_error(e):
    # Log the error and stacktrace.
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500
