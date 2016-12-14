# encoding: utf-8
import logging

from flask import Flask, render_template, request, make_response
import requests
import requests_toolbelt.adapters.appengine
from lxml import html, etree
from datetime import datetime
from google.appengine.api.memcache import Client

app = Flask(__name__)

requests_toolbelt.adapters.appengine.monkeypatch()

cache = Client()

@app.route('/')
def main():
    return render_template('main.html')

@app.route('/feed/')
def feed():
    keyword = request.args.get('t')

    cache_key = u'feed-%s' % keyword

    if cache.get(cache_key) is None:
        print 'cache yok'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36'}

        params = {'q': keyword}

        page = requests.get('https://eksisozluk.com/', params=params, headers=headers)
        tree = html.fromstring(page.content)

        # get last page
        pager = tree.xpath('//*[@class="pager"]/@data-pagecount')

        if len(pager) > 0:
            last_page_number = tree.xpath('//*[@class="pager"]/@data-pagecount')[0]

            if last_page_number > 1:
                params = {
                    'p': last_page_number
                }
                page = requests.get(page.url, params=params, headers=headers)

                tree = html.fromstring(page.content)

        meta = {
            'query': keyword,
            'title': tree.xpath('//*[@id="title"]/a/span/text()')[0],
            'url': request.url,
            'date': ''
        }
        entries = [etree.tostring(entry) for entry in tree.xpath('//*[@id="entry-list"]/li/div[1]')][::-1]
        links = tree.xpath('//*[@class="entry-date permalink"]/@href')[::-1]
        authors = tree.xpath('//*[@class="entry-author"]/text()')[::-1]
        dates = [datetime.strptime(date.split(' ~ ')[0], "%d.%m.%Y %H:%M") for date in tree.xpath('//*[@class="entry-date permalink"]/text()')][::-1]

        rss_response = render_template('rss_tpl.xml', entries=entries, links=links, authors=authors, dates=dates, meta=meta)
        cache.set(cache_key, rss_response, time=15*60)
    else:
        rss_response = cache.get(cache_key)

    response = make_response(rss_response)
    response.headers["Content-Type"] = "application/rss+xml"

    return response
    

@app.errorhandler(500)
def server_error(e):
    # Log the error and stacktrace.
    logging.exception('An error occurred during a request.')
    return 'An internal error occurred.', 500
