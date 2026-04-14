FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    CRON_SCHEDULE="0 8,18 * * *"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Supercronic para cron em container com logs em stdout
RUN curl -fsSL -o /usr/local/bin/supercronic \
    https://github.com/aptible/supercronic/releases/download/v0.2.29/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic

COPY . .

RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/run_monitor_container.sh

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
