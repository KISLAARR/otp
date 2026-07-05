# ─────────────────────────────────────────────────────────────
# Stage 1 — builder: зависимости в изолированный venv
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip uninstall -y jaraco.context wheel setuptools pip \
    && rm -rf /opt/venv/lib/python*/site-packages/pkg_resources \
              /opt/venv/lib/python*/site-packages/_distutils_hack

# ─────────────────────────────────────────────────────────────
# Stage 2 — runtime: только venv + код, non-root
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

RUN rm -rf /usr/local/lib/python3.12/site-packages/setuptools* \
           /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/site-packages/wheel* \
           /usr/local/lib/python3.12/site-packages/pkg_resources \
           /usr/local/lib/python3.12/site-packages/_distutils_hack \
           /usr/local/lib/python3.12/site-packages/jaraco* \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 /usr/local/bin/wheel

COPY --from=builder /opt/venv /opt/venv
COPY . .

# .env не копируется — секреты приходят через окружение (см. .dockerignore)
RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-1} -b 0.0.0.0:8000 --access-logfile - --error-logfile -"]
