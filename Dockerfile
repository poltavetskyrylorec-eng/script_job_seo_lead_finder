FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python -m pip install --upgrade pip \
    && pip install -e . \
    && python -m playwright install --with-deps chromium \
    && npm install -g @anthropic-ai/claude-code@latest

CMD ["python", "-m", "dabud_job_agent.main", "run-all"]
