# Build the frontend, then run the API, which also serves the built frontend.

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app/backend
# Dependencies first: this layer is rebuilt only when the lock file changes.
# No dev group and no `embedded` extra: the database is its own container here.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Uploads, pictures and the downloaded embedding model live in a volume.
ENV DATA_DIR=/data
RUN useradd --create-home app && mkdir /data && chown app /data
USER app
VOLUME /data

EXPOSE 8000
# --proxy-headers: behind a reverse proxy the app must see the original scheme,
# so the session cookie is marked Secure on HTTPS.
CMD ["uv", "run", "--no-dev", "--no-sync", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
