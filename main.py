import json
import logging
import os

import redis
import requests
from datetime import datetime, timedelta
from urllib.parse import urljoin

from flask import Flask, render_template, request
from flask_caching import Cache
from furl import furl
from lxml import html, etree
from user_agent import generate_user_agent
from werkzeug.http import http_date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HTTP_REQUEST_TIMEOUT = 10

# 12 hours
CACHE_TIMEOUT = 12 * 60 * 60

# 1 hour
CDN_CACHE_TIMEOUT = 60 * 60

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_DROP_TOKEN = os.environ.get("CACHE_DROP_TOKEN", "")

app = Flask(__name__)
app.config["CACHE_TYPE"] = "RedisCache"
app.config["CACHE_REDIS_URL"] = REDIS_URL
app.config["CACHE_KEY_PREFIX"] = "eksirss:"

cache = Cache(app)

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

FEED_KEY_PREFIX = "feed:"
LAST_HIT_KEY_PREFIX = "last_hit:"
FEED_INDEX_KEY = "feed:index"


class Feed:
    def __init__(self, keyword="", title="", url="", content=None, last_update=None):
        self.keyword = keyword
        self.title = title
        self.url = url
        self.content = content or {}
        self.last_update = last_update or datetime.now()

    def to_dict(self):
        return {
            "keyword": self.keyword,
            "title": self.title,
            "url": self.url,
            "content": json.dumps(self.content),
            "last_update": self.last_update.isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            keyword=data.get("keyword", ""),
            title=data.get("title", ""),
            url=data.get("url", ""),
            content=json.loads(data.get("content", "{}")),
            last_update=datetime.fromisoformat(data.get("last_update", datetime.now().isoformat())),
        )

    def save(self):
        key = FEED_KEY_PREFIX + self.keyword
        redis_client.hset(key, mapping=self.to_dict())
        redis_client.sadd(FEED_INDEX_KEY, self.keyword)

    @staticmethod
    def get(keyword):
        key = FEED_KEY_PREFIX + keyword
        data = redis_client.hgetall(key)
        return Feed.from_dict(data)

    @staticmethod
    def delete(keyword):
        key = FEED_KEY_PREFIX + keyword
        redis_client.delete(key)
        redis_client.srem(FEED_INDEX_KEY, keyword)

    @staticmethod
    def all_keywords():
        return redis_client.smembers(FEED_INDEX_KEY)

    def __repr__(self):
        return f"<Topic {self.keyword!r} updated at {self.last_update!r}>"


def cache_key(keyword=None):
    if not keyword:
        keyword = request.args.get("t")
    return f"feed:{keyword}"


def render_feed(feed):
    origin = request.host_url.rstrip("/")
    response = render_template("rss_tpl.xml", feed=feed, origin=origin)
    return response, 200, {
        "Content-Type": "application/rss+xml",
        "Last-Modified": http_date(feed.last_update),
        "Expires": http_date(feed.last_update + timedelta(seconds=CDN_CACHE_TIMEOUT)),
    }


def fetch_feed(keyword, url_with_paging=None):
    with requests.Session() as s:
        s.headers.update({"User-Agent": generate_user_agent()})

        if url_with_paging:
            page = s.get(url_with_paging, allow_redirects=True, timeout=HTTP_REQUEST_TIMEOUT)
        else:
            page = s.get(
                "https://eksisozluk.com/",
                allow_redirects=True,
                params={"q": keyword},
                timeout=HTTP_REQUEST_TIMEOUT,
            )

        tree = html.fromstring(page.content)
        url = page.url

        pager = tree.xpath('//*[@class="pager"]/@data-pagecount')
        if pager:
            last_page_number = pager[0]
            current_page_number = tree.xpath('//*[@class="pager"]/@data-currentpage')[0]

            if last_page_number != current_page_number:
                paging_replaced_url = furl(url).remove("p").add({"p": last_page_number}).url
                page = s.get(paging_replaced_url, timeout=HTTP_REQUEST_TIMEOUT)
                tree = html.fromstring(page.content)
                url = page.url

    feed = create_feed_from_page(tree, keyword, url)
    feed.save()

    return feed


def create_feed_from_page(tree, keyword, url):
    topic_feed = Feed(keyword=keyword)
    topic_feed.title = tree.xpath('//*[@id="title"]/a/span/text()')[0]
    topic_feed.url = url

    entries = [
        etree.tostring(fix_links(entry), encoding="unicode")
        for entry in tree.xpath('//*[@id="entry-item-list"]/li/div[1]')
    ][::-1]
    links = tree.xpath('//*[@class="entry-date permalink"]/@href')[::-1]
    authors = tree.xpath('//*[@class="entry-author"]/text()')[::-1]
    dates = [
        datetime.strptime(date.split(" ~ ")[0], "%d.%m.%Y %H:%M")
        for date in tree.xpath('//*[@class="entry-date permalink"]/text()')
    ][::-1]

    topic_feed.content = {
        "entries": entries,
        "links": links,
        "authors": authors,
        "dates": [d.strftime("%a, %d %b %Y %H:%M:%S") for d in dates],
    }
    topic_feed.last_update = datetime.now()

    if not entries:
        load_more_link = tree.xpath('//*[@id="topic"]/a/@href')
        if load_more_link:
            load_more_link = load_more_link[0].lstrip("/")
            topic_feed.url = f"https://eksisozluk.com/{load_more_link}"

    return topic_feed


def fix_links(tree):
    for node in tree.xpath("a[@href]"):
        href = node.get("href")
        if not (href.startswith("http://") or href.startswith("https://")):
            url = urljoin("https://eksisozluk.com", href)
            node.set("href", url)

    return tree


def enqueue_feed_update(keyword):
    redis_client.sadd("feed:queue", keyword)


def update_last_hit(keyword):
    key = LAST_HIT_KEY_PREFIX + keyword
    redis_client.set(key, datetime.now().isoformat(), ex=25 * 60 * 60)


def find_last_hit(keyword):
    key = LAST_HIT_KEY_PREFIX + keyword
    val = redis_client.get(key)
    if val:
        return datetime.fromisoformat(val)
    return None


@app.route("/health")
def health():
    redis_client.ping()
    return {"status": "ok"}


@app.route("/")
def index():
    return render_template("main.html")


@app.route("/feed/")
@cache.cached(key_prefix=cache_key, timeout=CACHE_TIMEOUT)
def get_feed():
    keyword = request.args.get("t")
    logger.info("cache not found for %s", keyword)

    feed = Feed.get(keyword)
    if not feed:
        feed = fetch_feed(keyword)
        enqueue_feed_update(keyword)

    return render_feed(feed)


@app.route("/cache/drop", methods=["POST"])
def drop_cache():
    if not CACHE_DROP_TOKEN:
        return {"error": "CACHE_DROP_TOKEN not configured"}, 503

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {CACHE_DROP_TOKEN}":
        return {"error": "unauthorized"}, 401

    body = request.get_json(silent=True) or {}
    keyword = body.get("key")

    if keyword:
        cache.delete(cache_key(keyword))
        logger.info("cache dropped for %s", keyword)
        return {"dropped": keyword}

    cache.clear()
    logger.info("all cache dropped")
    return {"dropped": "all"}


@app.after_request
def after_request(response):
    if request.endpoint == "get_feed":
        keyword = request.args.get("t")
        if keyword:
            update_last_hit(keyword)
    return response


@app.errorhandler(500)
def server_error(e):
    logger.exception("An error occurred during a request.")
    return "An internal error occurred.", 500