FROM python:3.12-slim

WORKDIR /app

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Keep package layout so relative imports (from .config) work
WORKDIR /app
COPY . ./api/
ENV PYTHONPATH=/app

# --no-proxy-headers is deliberate: uvicorn would otherwise rewrite
# request.client.host from a caller-supplied X-Forwarded-For, which silently
# overrides the trust decision made in api/services/rate_limit.py. Proxy trust
# is configured there via TRUST_FORWARDED_FOR / FORWARDED_PROXY_HOPS.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-proxy-headers"]
