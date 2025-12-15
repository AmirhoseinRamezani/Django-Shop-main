FROM python:3.13-slim-bookworm

# Python runtime sanity
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /usr/src/app

# System dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip (پشتیبانی کامل از Python 3.13)
RUN pip install --upgrade pip

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
