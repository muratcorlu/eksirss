# ekşirss

EkşiSözlük başlıkları RSS kaynağı - [https://eksirss.muratcorlu.com](https://eksirss.muratcorlu.com)

## Development

Run locally with Docker Compose:

```bash
docker compose -f docker-compose.local.yml up --build
```

The app will be available at [http://localhost:8080](http://localhost:8080).

### Services

- **app** — Flask web server (gunicorn) on port 8080
- **worker** — Background worker that refreshes feed caches
- **redis** — Data storage and caching

### Architecture

- Feeds are stored in Redis hashes (`feed:<keyword>`)
- Feed response cache uses Redis via `flask-caching`
- A background worker polls a Redis set (`feed:queue`) to refresh stale feeds
- Inactive feeds (not accessed in 24h) are automatically cleaned up

## Deployment

Docker images are automatically built and pushed to GitHub Container Registry on every push to `master`:

```
ghcr.io/muratcorlu/eksirss:latest
```

Run with the published image:

```bash
docker compose up -d
```
