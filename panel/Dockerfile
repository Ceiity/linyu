FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJECT_DIR=/opt/astrbot/AstrBot-Deploy \
    INSTALL_PREFIX=/opt/astrbot \
    STATE_FILE=/opt/astrbot/.env \
    PANEL_CONFIG=/opt/astrbot/panel_config.json

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl ca-certificates docker-cli procps iproute2 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/astrbot/AstrBot-Deploy
COPY . /opt/astrbot/AstrBot-Deploy

EXPOSE 7070
CMD ["python3", "panel/backend/app.py", "--host", "0.0.0.0", "--port", "7070"]
