FROM python:3.13-bookworm

# Python runtime sanity
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DEFAULT_TIMEOUT=120

WORKDIR /usr/src/app

# ---- fix apt reliability ----
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --- pip network reliability config ---
RUN pip config set global.default-timeout 120 \
 && pip config set global.trusted-host "pypi.org files.pythonhosted.org"

# Upgrade pip (پشتیبانی کامل از Python 3.13)
RUN pip install --upgrade pip

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
