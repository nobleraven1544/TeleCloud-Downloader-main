FROM parsafadaeei/telegram-bot:latest

COPY requirements.txt /tmp/requirements.txt

RUN apk add --no-cache aria2 curl unzip nodejs ffmpeg && \
    curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
    unzip rclone-current-linux-amd64.zip && \
    cp rclone-*-linux-amd64/rclone /usr/bin/rclone && \
    chmod +x /usr/bin/rclone && \
    rm -rf rclone-* && \
    pip install --no-cache-dir -r /tmp/requirements.txt --break-system-packages

ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app/
RUN mkdir -p /root/.config/yt-dlp && echo '--js-runtimes node' > /root/.config/yt-dlp/config

# Start local Bot API server in background, then run bot
CMD sh -c '\
  echo "[docker] Starting local Bot API server..."; \
  telegram-bot-api --local --api-id "$TELEGRAM_API_ID" --api-hash "$TELEGRAM_API_HASH" --http-port 8081 --dir /var/lib/telegram-bot-api --log /var/lib/telegram-bot-api/bot-api.log & \
  for i in $(seq 1 30); do \
    if curl -s -o /dev/null http://localhost:8081/ 2>/dev/null; then \
      echo "[docker] Bot API server is up"; \
      break; \
    fi; \
    echo "[docker] Waiting for Bot API ($i/30)..."; \
    sleep 2; \
  done; \
  exec python3 main.py'
