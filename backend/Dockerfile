# Mastarr — single image: node builds the UI, python serves API + static assets.
#
# Build from the repo root so both ./frontend and ./backend are in context:
#   docker build -f backend/Dockerfile -t mastarr:latest .

# ----------------------------------------------------------------- frontend
FROM node:22-alpine AS frontend

WORKDIR /build
# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------ runtime
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MASTARR_DATA_DIR=/data

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/mastarr/ ./mastarr/
# main.py serves the SPA from mastarr/static when it exists.
COPY --from=frontend /build/dist/ ./mastarr/static/

# Non-root. The data volume must be writable by this uid — see the compose file.
RUN useradd --create-home --uid 1000 mastarr \
    && mkdir -p /data \
    && chown -R mastarr:mastarr /app /data
USER mastarr

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "mastarr.main:app", "--host", "0.0.0.0", "--port", "8000"]
