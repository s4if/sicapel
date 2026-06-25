FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 gir1.2-rsvg-2.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    FLASK_APP=app

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv sync --frozen --no-dev

RUN DATABASE_URL=sqlite:////tmp/build.db uv run flask db init && \
    DATABASE_URL=sqlite:////tmp/build.db uv run flask db migrate -m "docker build" && \
    rm -f /tmp/build.db

RUN addgroup --system --gid 1001 sicapel && \
    adduser --system --uid 1001 --gid 1001 sicapel

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 gir1.2-rsvg-2.0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    FLASK_APP=app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app /app
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group

COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /app/instance /var/lib/sicapel/uploads /var/lib/sicapel/cache && \
    chown -R sicapel:sicapel /app/instance /var/lib/sicapel

EXPOSE 8000

USER sicapel

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "gunicorn", "--workers", "4", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-", "app:create_app()"]
