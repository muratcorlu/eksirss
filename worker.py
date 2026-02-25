import logging
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from main import (
    app,
    cache,
    cache_key,
    fetch_feed,
    find_last_hit,
    redis_client,
    render_feed,
    Feed,
    CACHE_TIMEOUT,
    FEED_INDEX_KEY,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limit: ~6 per minute (matches old queue.yaml rate)
TASK_INTERVAL = 10

# How often to run cleanup (every 24 hours)
CLEANUP_INTERVAL = 24 * 60 * 60


def process_queue():
    keyword = redis_client.spop("feed:queue")
    if not keyword:
        return False

    logger.info("Processing feed update for: %s", keyword)
    try:
        feed = Feed.get(keyword)
        if feed:
            url_with_paging = feed.url
        else:
            url_with_paging = None

        with app.app_context():
            updated_feed = fetch_feed(keyword, url_with_paging=url_with_paging)
            response = render_feed(updated_feed)
            cache.set(cache_key(keyword), response, timeout=CACHE_TIMEOUT)
            logger.info("Cache filled for %s", keyword)
    except Exception:
        logger.exception("Error processing feed for %s", keyword)
        # Re-enqueue on failure
        redis_client.sadd("feed:queue", keyword)

    return True


def enqueue_stale_feeds():
    logger.info("Checking for stale feeds to re-enqueue...")
    one_day_ago = datetime.now() - timedelta(days=1)
    count = 0

    for keyword in Feed.all_keywords():
        feed = Feed.get(keyword)
        if feed and feed.last_update < one_day_ago:
            redis_client.sadd("feed:queue", keyword)
            count += 1

    logger.info("Enqueued %d stale feeds", count)


def cleanup_inactive_feeds():
    logger.info("Cleaning up inactive feeds...")
    one_day_ago = datetime.now() - timedelta(days=1)
    deleted = 0

    for keyword in Feed.all_keywords():
        last_hit = find_last_hit(keyword)
        if not last_hit or last_hit < one_day_ago:
            logger.info("Deleting inactive feed: %s", keyword)
            Feed.delete(keyword)
            deleted += 1

    logger.info("Deleted %d inactive feeds", deleted)


HEALTH_PORT = 8081


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            try:
                redis_client.ping()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"status": "error"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    server.serve_forever()


def run():
    logger.info("Worker started")

    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    logger.info("Health server started on port %d", HEALTH_PORT)

    last_cleanup = time.time()
    last_stale_check = time.time()

    while True:
        # Process queued tasks
        had_work = process_queue()

        # Run stale feed check every 6 hours
        if time.time() - last_stale_check > 6 * 60 * 60:
            enqueue_stale_feeds()
            last_stale_check = time.time()

        # Run cleanup every 24 hours
        if time.time() - last_cleanup > CLEANUP_INTERVAL:
            cleanup_inactive_feeds()
            last_cleanup = time.time()

        if not had_work:
            time.sleep(TASK_INTERVAL)
        else:
            time.sleep(TASK_INTERVAL)


if __name__ == "__main__":
    run()
