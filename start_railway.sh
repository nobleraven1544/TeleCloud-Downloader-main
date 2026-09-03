#!/bin/sh
set -e

# ── Start Local Telegram Bot API Server (enables 2GB uploads) ──
# Load from .env file if variables not provided by environment
if [ -z "$TELEGRAM_API_ID" ] && [ -f /app/bot_env.env ]; then
  . /app/bot_env.env
fi
API_ID="${TELEGRAM_API_ID:-0}"
API_HASH="${TELEGRAM_API_HASH:-00000000000000000000000000000000}"
echo "[debug] TELEGRAM_API_ID=$API_ID API_HASH=${API_HASH:0:8}..."

mkdir -p /var/lib/telegram-bot-api /root/downloads /root/storage /root/.config/rclone
# empty rclone config placeholder (gdrive path is disabled, but keep file present)
if [ ! -f /root/.config/rclone/rclone.conf ]; then
  printf '[gdrive]\ntype = drive\n' > /root/.config/rclone/rclone.conf
fi

echo "[railway] starting telegram-bot-api on 0.0.0.0:8081 (local mode)"
/usr/local/bin/telegram-bot-api \
  --local \
  --api-id "$API_ID" \
  --api-hash "$API_HASH" \
  --http-port 8081 \
  --dir /var/lib/telegram-bot-api \
  --log /var/lib/telegram-bot-api/bot-api.log \
  &

# wait for bot-api to actually be listening, not just 4s
for i in $(seq 1 30); do
  if curl -s -o /dev/null -x '' http://localhost:8081/ 2>/dev/null || curl -s -o /dev/null http://localhost:8081/ 2>/dev/null; then
    echo "[railway] bot-api is up"
    break
  fi
  echo "[railway] waiting for bot-api ($i/30)..."
  sleep 2
done

# ── Wait for Postgres only if DATABASE_URL is provided ──
if [ -n "$DATABASE_URL" ]; then
  echo "[railway] DATABASE_URL found, waiting for Postgres..."
  for i in $(seq 1 30); do
    if python3 -c "import psycopg2,os; psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=2).close(); print('ok')" 2>/dev/null; then
      echo "[railway] Postgres is up"
      break
    fi
    echo "[railway] Postgres not ready yet (attempt $i/30), retrying..."
    sleep 2
  done
else
  echo "[railway][WARN] DATABASE_URL not set — bot will use local SQLite fallback"
fi

echo "[railway] starting bot"
exec python3 main.py
