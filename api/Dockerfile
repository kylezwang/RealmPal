# Build context is the repo root (see docker-compose.yml and the `docker
# build` command in docs/DEPLOYMENT_GUIDE.md), not ./api. uvicorn is run as
# the `api.main:app` package path everywhere else (start_services.ps1,
# local dev), so the image needs that same `api/` package layout, not a
# flattened copy of its contents.
#
# Base image ships Chromium (+ Firefox/WebKit) and every OS-level dependency
# Playwright needs already installed. Manually apt-installing that library
# list on python:slim is brittle and drifts from whatever Playwright
# actually needs release to release; the official image tracks the pinned
# `playwright` version in api/requirements.txt instead. Bump both together.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Dependencies before the app code so a code-only change doesn't invalidate
# this layer and reinstall everything.
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api api

ENV PYTHONUNBUFFERED=1
# Matches the local dev port (start_services.ps1) and the Container Apps
# target port in docs/DEPLOYMENT_GUIDE.md Priority 4 Step 5 - keep all
# three in sync if this ever changes.
EXPOSE 8001

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-proxy-headers"]
