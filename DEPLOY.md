# Deploy — Opiniion ARR Bridge

## Docker (recommended)

From repo root:

```bash
cp .env.example .env   # optional: TUNNEL_TOKEN for Cloudflare profile
docker compose up -d --build
docker compose logs -f --tail=50 arr-dashboard
```

| Access | URL |
|--------|-----|
| Local | http://127.0.0.1:8000 |

Data persists in Docker volume `arr_data`. To bind-mount a host path instead, change `docker-compose.yml` volumes.

## Seed database (first run)

If `data/arr.db` is missing, build the image and run once:

```bash
docker compose run --rm arr-dashboard python db.py
docker compose up -d arr-dashboard
```

## Cloudflare Tunnel (optional)

Compose profile (token from Zero Trust → Tunnels):

```bash
# .env: TUNNEL_TOKEN=...
docker compose --profile tunnel up -d
```

Or use `scripts/setup_cloudflare_tunnel.sh` for cert-based tunnel setup on the host.

## Former homelab LXC

See [docs/homelab-lxc-108-retired.md](docs/homelab-lxc-108-retired.md).
