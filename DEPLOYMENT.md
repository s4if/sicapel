# SICAPEL — Deployment Guide

> **Quick start with SQLite (zero external dependencies):** skip to [§1](#1-quick-start-sqlite).
> **Production with PostgreSQL:** skip to [§3](#3-postgresql-setup).

---

## Table of Contents

1. [Quick Start — SQLite](#1-quick-start-sqlite)
2. [Quick Start — PostgreSQL](#2-quick-start-postgresql)
3. [Environment Variables](#3-environment-variables)
4. [Building & Running Manually](#4-building--running-manually)
5. [First-Time Setup](#5-first-time-setup)
6. [Upgrading](#6-upgrading)
7. [Backup & Restore](#7-backup--restore)
8. [Production Hardening](#8-production-hardening)
9. [Architecture](#9-architecture)
10. [Serving Behind an External Reverse Proxy](#10-serving-behind-an-external-reverse-proxy)
11. [Cloudflare Tunnel](#11-cloudflare-tunnel)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Quick Start — SQLite

This mode requires **nothing** except Docker — no PostgreSQL, no external services.

```sh
# 1. Clone the repository
git clone <repo-url> sicapel
cd sicapel

# 2. Copy the environment file and edit SECRET_KEY
cp .env.example .env
#   Edit .env and set a strong SECRET_KEY (e.g. openssl rand -base64 48)

# 3. Build and start
docker compose up -d

# 4. The app is now available at http://localhost
```

The `docker-compose.yml` is pre-configured for SQLite out of the box. The database file lives at `/app/instance/sicapel.sqlite` inside the container, persisted via the `instance_data` Docker volume.

### Login credentials

After first startup, the container auto-seeds baseline data. Run:

```sh
docker compose exec app uv run flask seed --dev
```

Then log in with the dev credentials (see `NOTES.md`).

---

## 2. Quick Start — PostgreSQL

### 2.1 Enable the PostgreSQL service

Edit `docker-compose.yml` and uncomment:

1. The entire `db:` service block.
2. The PostgreSQL `DATABASE_URL` line under `app.environment`.
3. The `depends_on:` block under `app`.
4. Comment out or remove the SQLite `DATABASE_URL` line.

The relevant section should look like:

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: sicapel
      POSTGRES_USER: sicapel
      POSTGRES_PASSWORD: ${DB_PASSWORD:-sicapel}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sicapel"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  app:
    build: .
    environment:
      DATABASE_URL: postgresql://sicapel:${DB_PASSWORD:-sicapel}@db:5432/sicapel
      SECRET_KEY: ${SECRET_KEY:?SECRET_KEY is required}
      UPLOAD_FOLDER: /var/lib/sicapel/uploads
      SCHOOL_NAME: ${SCHOOL_NAME:-SICAPEL}
    volumes:
      - uploads:/var/lib/sicapel/uploads
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
```

### 2.2 Start

```sh
# Optionally set a custom DB password
echo "DB_PASSWORD=my-strong-password" >> .env

docker compose up -d
```

The app automatically runs `flask db upgrade` on startup, creating all tables.

---

## 3. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — | Flask secret key for sessions and CSRF. Generate with `openssl rand -base64 48`. |
| `DATABASE_URL` | No | `sqlite:////app/instance/sicapel.sqlite` | Database connection string. |
| `UPLOAD_FOLDER` | No | `/var/lib/sicapel/uploads` | Path for uploaded files. |
| `SCHOOL_NAME` | No | `SICAPEL` | School name printed on PDF letters. |
| `DB_PASSWORD` | No | `sicapel` | PostgreSQL password (used by both `db` and `app` services). |
| `PORT` | No | `80` | Host port mapped to compose nginx. |
| `APP_PORT` | No | `8000` | Direct gunicorn port (when not using compose nginx). |
| `FLASK_DEBUG` | No | `0` | Set to `1` for debug mode (development only). |

Example `.env`:

```
SECRET_KEY=W7L3vR8sX2pK9mN4qT6yA1cE5bH0jF8d
SCHOOL_NAME=SMA Negeri 1 Contoh
```

---

## 4. Building & Running Manually

Without docker-compose, or for custom setups:

```sh
# Build the image
docker build -t sicapel:latest .

# Run with SQLite
docker run -d \
  --name sicapel \
  -p 8000:8000 \
  -e SECRET_KEY="your-secret-key" \
  -v sicapel_uploads:/var/lib/sicapel/uploads \
  -v sicapel_instance:/app/instance \
  sicapel:latest

# Run with PostgreSQL
docker run -d \
  --name sicapel \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://sicapel:password@host:5432/sicapel" \
  -e SECRET_KEY="your-secret-key" \
  -v sicapel_uploads:/var/lib/sicapel/uploads \
  sicapel:latest
```

---

## 5. First-Time Setup

The container entrypoint handles this automatically:

1. **Migrations:** `flask db upgrade` runs on every start.
2. **Seed:** If the `users` table is empty, baseline data is seeded (4 violation categories, 1 admin user, 13 violation types, 1 active academic year).

### Manual seed (dev data)

```sh
# Seed comprehensive dev data (21 students, 3 classes, teachers, etc.)
docker compose exec app uv run flask seed --dev
```

See `NOTES.md` for login credentials after running `--dev`.

### Custom admin credentials

```sh
docker compose exec app uv run flask seed --admin-email=admin@school.id --admin-password=Str0ng!Pass
```

---

## 6. Upgrading

### Application code

```sh
# Pull latest code
git pull

# Rebuild and restart
docker compose build --no-cache
docker compose up -d
```

Migrations run automatically on startup. If the new version includes model changes, `flask db upgrade` will apply them.

### PostgreSQL version

```sh
docker compose exec app uv run flask db current   # check current migration
docker compose exec app uv run flask db upgrade   # manually run pending
```

---

## 7. Backup & Restore

### SQLite

```sh
# Backup
docker compose exec app sh -c 'cp /app/instance/sicapel.sqlite /tmp/backup.sqlite'
docker compose cp app:/tmp/backup.sqlite ./sicapel-backup-$(date +%F).sqlite

# Restore
docker compose cp ./sicapel-backup-2026-06-25.sqlite app:/app/instance/sicapel.sqlite
docker compose restart app
```

### PostgreSQL

```sh
# Backup
docker compose exec db pg_dump -U sicapel sicapel > sicapel-backup-$(date +%F).sql

# Restore
cat sicapel-backup-2026-06-25.sql | docker compose exec -T db psql -U sicapel -d sicapel
```

### Uploaded files

```sh
# Backup uploads volume
docker run --rm -v sicapel_uploads:/source -v $(pwd):/dest alpine \
  tar czf /dest/uploads-backup-$(date +%F).tar.gz -C /source .

# Restore
docker run --rm -v sicapel_uploads:/dest -v $(pwd):/source alpine \
  tar xzf /source/uploads-backup-2026-06-25.tar.gz -C /dest
```

Automate with cron:

```cron
0 2 * * * cd /opt/sicapel && docker compose exec -T db pg_dump -U sicapel sicapel > backups/sicapel-$(date +\%F).sql
```

---

## 8. Production Hardening

### 8.1 Security

| Concern | Action |
|---|---|
| **SECRET_KEY** | Generate with `openssl rand -base64 48` — never use the default. |
| **Database password** | Set `DB_PASSWORD` to a strong random string. |
| **TLS / HTTPS** | See [§10 (External Reverse Proxy)](#10-serving-behind-an-external-reverse-proxy) or [§11 (Cloudflare Tunnel)](#11-cloudflare-tunnel). |
| **Upload restrictions** | MIME whitelist and `MAX_CONTENT_LENGTH` (16 MB) are enforced by the app. Adjust `client_max_body_size` in `docker/nginx.conf` if needed. |
| **Non-root user** | The container runs as `sicapel` (UID 1001), not root. |

### 8.2 Resource limits

```yaml
# In docker-compose.yml under app:
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
```

### 8.3 gunicorn workers

The default is 4 workers. Adjust with `--workers N` in the Dockerfile `CMD`:

```dockerfile
CMD ["uv", "run", "gunicorn", "--workers", "2", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
```

Rule of thumb: `(2 × CPU cores) + 1`.

### 8.4 Healthcheck

Docker Compose can monitor the app:

```yaml
# Under app service:
healthcheck:
  test: ["CMD", "uv", "run", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthcheck')"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 15s
```

---

## 9. Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Browser    │ ───→ │   nginx:80   │ ───→ │  gunicorn    │
│ (user)       │      │ (reverse     │      │  :8000       │
│              │      │  proxy)      │      │  (Flask)     │
└──────────────┘      └──────┬───────┘      └──────┬───────┘
                             │                      │
                             │ static/              │ SQLite / PostgreSQL
                             ▼                      ▼
                     ┌──────────────┐      ┌──────────────┐
                     │  /app/app/   │      │  Database    │
                     │  static/     │      │  (file or    │
                     │  (nginx)     │      │  TCP)        │
                     └──────────────┘      └──────────────┘
```

**Container structure:**

| Container | Image | Exposed | Purpose |
|---|---|---|---|
| `app` | `sicapel:latest` (built) | 8000 (internal) | Gunicorn + Flask |
| `nginx` | `nginx:1.25-alpine` | 80 (host) | Reverse proxy, static serving |
| `db` | `postgres:16-alpine` | 5432 (internal) | PostgreSQL (optional) |

### Port mapping

| Host | Container | Service | Notes |
|---|---|---|---|
| `80` | `80` | nginx | Change with `PORT=8080 docker compose up -d` |
| — | `8000` | gunicorn | Internal only, not exposed to host |

---

## 10. Serving Behind an External Reverse Proxy

If your infrastructure team already manages a reverse proxy (nginx, Caddy, or
other) on the host, you do **not** need the `nginx` container from the
docker-compose stack. Instead, let gunicorn listen directly on a host port.

### 10.1 docker-compose adjustments

1. **Comment out** or remove the `nginx:` service block in `docker-compose.yml`.
2. **Uncomment** the `ports:` line under the `app:` service:

   ```yaml
   app:
     ports:
       - "${APP_PORT:-8000}:8000"
   ```

3. Restart the stack:

   ```sh
   docker compose up -d
   ```

The app now listens on `http://<host-ip>:8000`. Your host reverse proxy
handles TLS termination, domain routing, and forwards to that port.

### 10.2 Host-installed nginx

```nginx
server {
    listen 443 ssl http2;
    server_name sicapel.school.ac.id;

    ssl_certificate     /etc/ssl/certs/sicapel.pem;
    ssl_certificate_key /etc/ssl/private/sicapel-key.pem;

    client_max_body_size 20M;

    location /static/ {
        # Serve Flask static files directly from the mounted volume,
        # or copy them to a host directory and alias that instead.
        proxy_pass http://127.0.0.1:8000/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}

server {
    listen 80;
    server_name sicapel.school.ac.id;
    return 301 https://$host$request_uri;
}
```

Obtain certificates with [certbot](https://certbot.eff.org/):

```sh
sudo certbot --nginx -d sicapel.school.ac.id
```

### 10.3 Host-installed Caddy

Create a `Caddyfile` on the host:

```
sicapel.school.ac.id {
    reverse_proxy 127.0.0.1:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    @static {
        path /static/*
    }
    handle @static {
        reverse_proxy 127.0.0.1:8000 {
            header_up Host {host}
        }
    }
}
```

Caddy automatically provisions and renews TLS via Let's Encrypt — no
manual certificate management needed.

```sh
# Install Caddy (one-time)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy

# Place Caddyfile at /etc/caddy/Caddyfile
# Then start / enable
sudo systemctl enable --now caddy
```

---

## 11. Cloudflare Tunnel

Cloudflare Tunnel exposes the app without opening any firewall ports. All
traffic flows through an encrypted tunnel to Cloudflare's edge, which sits
in front of your origin.

### 11.1 How it works

```
Browser → Cloudflare edge → tunnel (cloudflared) → gunicorn:8000
```

No nginx container, no host-port exposure, no TLS certificates on the
server — Cloudflare handles all of that.

### 11.2 docker-compose adjustments

1. **Comment out** the `nginx:` service block in `docker-compose.yml`.
2. **Uncomment** the `ports:` line under `app:` (the tunnel connects to
   gunicorn directly).
3. Keep `APP_PORT` internal or set to `127.0.0.1:8000`:

   ```yaml
   app:
     ports:
       - "127.0.0.1:8000:8000"
   ```

   Binding to `127.0.0.1` ensures gunicorn is only reachable from the
   local tunnel process, not the open network.

### 11.3 Install & authenticate cloudflared

```sh
# On the host (one-time)
sudo apt install cloudflared  # or download from cloudflare.com

# Authenticate (opens a browser — log in to Cloudflare)
cloudflared tunnel login
```

### 11.4 Create the tunnel

```sh
# Create a named tunnel
cloudflared tunnel create sicapel

# This creates a credentials JSON file in ~/.cloudflared/
# and a tunnel ID. Keep the tunnel ID — you need it below.
```

### 11.5 Configure the tunnel

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <tunnel-id-from-step-4>
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json

ingress:
  # Serve Flask app through the tunnel
  - hostname: sicapel.school.ac.id
    service: http://localhost:8000

  # Healthcheck endpoint (excluded from metrics, optional)
  - hostname: sicapel.school.ac.id
    path: /healthcheck
    service: http://localhost:8000

  # Last rule: catch-all rejects (prevents routing to unknown hosts)
  - service: http_status:404
```

### 11.6 Create DNS record

```sh
# Route your domain's traffic through the tunnel
cloudflared tunnel route dns <tunnel-id> sicapel.school.ac.id
```

### 11.7 Run the tunnel

```sh
# Install as a system service so it starts on boot
sudo cloudflared service install

# Or run manually (foreground, for testing)
cloudflared tunnel run <tunnel-id>
```

### 11.8 Verify

```sh
curl https://sicapel.school.ac.id/healthcheck
# → {"status":"ok"}
```

### 11.9 Advantages & trade-offs

| Pro | Con |
|---|---|
| No open ports — zero attack surface | Adds ~10–30 ms latency from Cloudflare routing |
| Automatic TLS — no cert management | Requires a Cloudflare-managed domain |
| DDoS protection included | Free plan has limited features |
| Dashboard analytics at cloudflare.com | Tunnels cap at ~100 MB per request on free plan |
| Works with any host (even behind NAT/CGNAT) | — |

---

## 12. Troubleshooting

### Container exits immediately

```sh
# Check logs
docker compose logs app

# Common cause: missing SECRET_KEY
#   → Ensure SECRET_KEY is set in .env
```

### Database connection refused (PostgreSQL)

```sh
# Check if database is healthy
docker compose ps db
docker compose logs db

# Ensure the db service is fully uncommented in docker-compose.yml
# and depends_on is configured correctly
```

### "No such file or directory" for SQLite

```sh
# The entrypoint script creates the directory automatically.
# If the issue persists, check permissions:
docker compose exec app ls -la /app/instance/
```

### Permission denied for uploads

```sh
# Ensure uploads directory is writable by the sicapel user
docker compose exec app ls -la /var/lib/sicapel/uploads/
```

### Migrations fail

```sh
# Reset migrations completely (data loss — use with care)
docker compose exec app sh -c 'rm -rf migrations/versions/*'
docker compose exec app uv run flask db init
docker compose exec app uv run flask db migrate -m "recovery"
docker compose exec app uv run flask db upgrade
```

### Reset everything

```sh
# WARNING: destroys all data
docker compose down -v
docker compose up -d
```
