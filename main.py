# encoding: utf-8
import logging
import requests

from datetime import datetime
from datetime import timedelta
from urlparse import urlparse, urlunparse
from google.appengine.ext import ndb
from flask import Flask, render_template, request, redirect
from flask_caching import Cache
from lxml import html, etree
from user_agent import generate_user_agent
from werkzeug.http import http_date

import requests_toolbelt.adapters.appengine
requests_toolbelt.adapters.appengine.monkeypatch()

# 2 hours
CACHE_TIMEOUT = 2 * 60 * 60
TOPIC_PER_MINUTE = 2

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
    last_hit = ndb.DateTimeProperty()

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
        # 'Cache-Control': 'public, max-age=%d' % CACHE_TIMEOUT,
        # 'Expires': http_date(feed.last_update + timedelta(seconds=CACHE_TIMEOUT))
    }


def fetch_feed(keyword):
    with requests.Session() as s:
        s.headers.update({
            'User-Agent': generate_user_agent()
        })

        page = s.get('https://eksisozluk.com/', params={'q': keyword})

        tree = html.fromstring(page.content)
        url = page.url

        # get last page
        pager = tree.xpath('//*[@class="pager"]/@data-pagecount')
        if len(pager) > 0:
            last_page_number = tree.xpath('//*[@class="pager"]/@data-pagecount')[0]
            current_page_number = tree.xpath('//*[@class="pager"]/@data-currentpage')[0]

            if last_page_number > current_page_number:
                page = s.get(page.url, params={'p': last_page_number})
                tree = html.fromstring(page.content)
                url = page.url

    feed = create_feed_from_page(keyword, url, tree)
    feed.put()

    return feed


def create_feed_from_page(keyword, url, tree):
    topic_feed = Feed()
    topic_feed.key = feed_key(keyword)
    topic_feed.title = tree.xpath('//*[@id="title"]/a/span/text()')[0]
    topic_feed.url = url
    topic_feed.keyword = keyword

    entries = [etree.tostring(entry) for entry in tree.xpath('//*[@id="entry-list"]/li/div[1]')][::-1]
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
    return topic_feed


@app.route('/')
def main():
    return render_template('main.html')


@app.route('/tasks/fill-cache/')
def fill_cache():
    for feed in Feed.query().order(Feed.last_update).fetch(limit=TOPIC_PER_MINUTE):
        feed = fetch_feed(feed.keyword)
        response = render_feed(feed)

        logging.info('filling cache for %s', feed.keyword)
        cache.set(cache_key(feed.keyword), response, timeout=CACHE_TIMEOUT)

    return "ok"


@app.route('/tasks/clear-db/')
def clear_db():
    one_day_ago = datetime.now() - timedelta(days=1)

    # keys_to_delete = [key for key in old_topics.iter(keys_only=True)]
    keys_to_delete = []
    for feed in Feed.query(Feed.last_hit < one_day_ago):
        logging.info('deleting %s from db', feed.keyword)
        keys_to_delete.append(feed.key)
    else:
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
    return render_feed(feed)


@app.before_request
def redirect_nonwww():
    """Redirect non-www requests to www."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == 'eksirss.appspot.com':
        urlparts_list = list(urlparts)
        urlparts_list[1] = 'eksirss.muratcorlu.com'
        return redirect(urlunparse(urlparts_list), code=301)


@app.after_request
def after_request(response):
    if get_feed.__name__ == request.endpoint:
        feed = feed_key(request.args.get('t')).get()
        if feed:
            # update last hit
            feed.last_hit = datetime.now()
            feed.put()

    return response


@app.errorhandler(500)
def server_error(e):
    # Log the error and stacktrace.
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500
