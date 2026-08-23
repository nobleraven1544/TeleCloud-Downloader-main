#!/bin/sh
set -eu

# Beginner installer for TeleCloud-Downloader (Ubuntu/Debian).
# This script is idempotent and safe to rerun.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR="$SCRIPT_DIR"
ENV_FILE="$PROJECT_DIR/.env"
RUNTIME_COMPOSE_FILE="$PROJECT_DIR/.start.compose.yml"
COLAB_DEFAULT_URL="https://colab.research.google.com/drive/1Ltyqs4i0UAuR6FpBrn3ygMuqlnPo_igV?usp=sharing"

if [ -t 1 ]; then
  C_RESET="$(printf '\033[0m')"
  C_BLUE="$(printf '\033[34m')"
  C_GREEN="$(printf '\033[32m')"
  C_YELLOW="$(printf '\033[33m')"
  C_RED="$(printf '\033[31m')"
else
  C_RESET=""
  C_BLUE=""
  C_GREEN=""
  C_YELLOW=""
  C_RED=""
fi

log_step() { printf "%s==> %s%s\n" "$C_BLUE" "$1" "$C_RESET"; }
log_ok() { printf "%sOK:%s %s\n" "$C_GREEN" "$C_RESET" "$1"; }
log_warn() { printf "%sWARN:%s %s\n" "$C_YELLOW" "$C_RESET" "$1"; }
log_err() { printf "%sERROR:%s %s\n" "$C_RED" "$C_RESET" "$1" >&2; }
die() { log_err "$1"; exit 1; }

is_truthy() {
  v="$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')"
  case "$v" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    die "This script needs root privileges. Install sudo or run as root."
  fi
fi

run_root() {
  if [ -n "$SUDO" ]; then
    "$SUDO" "$@"
  else
    "$@"
  fi
}

APT_UPDATED=0
apt_install() {
  if [ "$APT_UPDATED" -eq 0 ]; then
    run_root apt-get update -y
    APT_UPDATED=1
  fi
  run_root apt-get install -y "$@"
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }

ensure_dir_path() {
  path="$1"
  if [ -e "$path" ] && [ ! -d "$path" ]; then
    die "Path '$path' must be a directory, but a file exists there."
  fi
  mkdir -p "$path"
}

ensure_regular_file() {
  path="$1"
  default_content="$2"
  if [ -e "$path" ] && [ -d "$path" ]; then
    die "Path '$path' must be a file, but a directory exists there."
  fi
  if [ ! -e "$path" ]; then
    if [ -n "$default_content" ]; then
      printf "%s" "$default_content" > "$path"
    else
      : > "$path"
    fi
  fi
}

env_get() {
  key="$1"
  if [ ! -f "$ENV_FILE" ]; then
    return 1
  fi
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  [ -n "$line" ] || return 1
  printf "%s" "${line#*=}"
}

env_set() {
  key="$1"
  value="$2"
  ensure_regular_file "$ENV_FILE" ""
  if grep -q -E "^${key}=" "$ENV_FILE"; then
    tmp_file="$(mktemp)"
    awk -v k="$key" -v v="$value" '
      BEGIN { done=0 }
      {
        if ($0 ~ ("^" k "=")) {
          if (!done) {
            print k "=" v
            done=1
          }
        } else {
          print $0
        }
      }
      END {
        if (!done) print k "=" v
      }
    ' "$ENV_FILE" > "$tmp_file"
    mv "$tmp_file" "$ENV_FILE"
  else
    printf "%s=%s\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

prompt_value() {
  prompt="$1"
  secret="$2"
  while :; do
    if [ "$secret" = "1" ]; then
      printf "%s: " "$prompt" > /dev/tty
      stty -echo < /dev/tty
      IFS= read -r value < /dev/tty
      stty echo < /dev/tty
      printf "\n" > /dev/tty
    else
      printf "%s: " "$prompt" > /dev/tty
      IFS= read -r value < /dev/tty
    fi
    if [ -n "$value" ]; then
      printf "%s" "$value"
      return 0
    fi
    printf "Value cannot be empty.\n" > /dev/tty
  done
}

prompt_yes_no() {
  question="$1"
  default="${2:-n}"
  while :; do
    if [ "$default" = "y" ]; then
      printf "%s [Y/n]: " "$question" > /dev/tty
    else
      printf "%s [y/N]: " "$question" > /dev/tty
    fi
    IFS= read -r answer < /dev/tty
    case "${answer:-$default}" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) printf "Please answer y or n.\n" > /dev/tty ;;
    esac
  done
}

prompt_choice_1_2() {
  while :; do
    printf "Your .env is already configured. What would you like to do?\n" > /dev/tty
    printf "  1) Review / edit existing values\n" > /dev/tty
    printf "  2) Keep existing values and continue\n" > /dev/tty
    printf "Choose [1/2] (default 2): " > /dev/tty
    IFS= read -r choice < /dev/tty
    case "${choice:-2}" in
      1|2)
        printf "%s" "${choice:-2}"
        return 0
        ;;
      *)
        printf "Please choose 1 or 2.\n" > /dev/tty
        ;;
    esac
  done
}

ensure_required_env() {
  key="$1"
  label="$2"
  secret="$3"
  numeric="$4"
  existing="$(env_get "$key" || true)"
  if [ -n "$existing" ]; then
    log_ok "Using existing $key from .env"
    return 0
  fi
  while :; do
    value="$(prompt_value "$label" "$secret")"
    if [ "$numeric" = "1" ]; then
      case "$value" in
        *[!0-9]*)
          log_warn "$key must be numeric."
          continue
          ;;
      esac
    fi
    env_set "$key" "$value"
    return 0
  done
}

review_or_edit_env() {
  key="$1"
  label="$2"
  secret="$3"
  numeric="$4"

  existing="$(env_get "$key" || true)"
  if [ -z "$existing" ]; then
    ensure_required_env "$key" "$label" "$secret" "$numeric"
    return 0
  fi

  if [ "$secret" = "1" ]; then
    shown="***"
  else
    shown="$existing"
  fi

  printf "%s current value: %s\n" "$key" "$shown"
  if prompt_yes_no "Keep this value?" "y"; then
    return 0
  fi

  while :; do
    value="$(prompt_value "$label" "$secret")"
    if [ "$numeric" = "1" ]; then
      case "$value" in
        *[!0-9]*)
          log_warn "$key must be numeric."
          continue
          ;;
      esac
    fi
    env_set "$key" "$value"
    return 0
  done
}

set_default_if_missing() {
  key="$1"
  value="$2"
  existing="$(env_get "$key" || true)"
  if [ -z "$existing" ]; then
    env_set "$key" "$value"
    log_ok "Set default $key=$value"
  fi
}

all_required_present() {
  for key in DOWNLOADER_BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH ADMIN_ID; do
    if [ -z "$(env_get "$key" || true)" ]; then
      return 1
    fi
  done
  return 0
}

docker_compose_ok() {
  run_root docker compose version >/dev/null 2>&1
}

generate_runtime_compose() {
  local_mode="$1"

  if [ "$local_mode" = "1" ]; then
    cat > "$RUNTIME_COMPOSE_FILE" <<'EOF'
version: '3.8'

services:
  telegram-bot-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-bot-api
    restart: unless-stopped
    network_mode: host
    env_file:
      - .env
    volumes:
      - ./telegram-bot-api-data:/var/lib/telegram-bot-api
      - ./downloads:/root/downloads

  telegram-bot:
    build: .
    container_name: telegram-bot
    restart: unless-stopped
    network_mode: host
    env_file:
      - .env
    volumes:
      - ./downloads:/root/downloads
      - ./cookies:/root/cookies
      - ./cookies_enabled.json:/root/cookies_enabled.json
      - ./rclone:/root/.config/rclone
      - ./user_configs:/app/user_configs
      - .:/app
      - ./telegram-bot-api-data:/var/lib/telegram-bot-api:ro
EOF
  else
    cat > "$RUNTIME_COMPOSE_FILE" <<'EOF'
version: '3.8'

services:
  telegram-bot:
    build: .
    container_name: telegram-bot
    restart: unless-stopped
    network_mode: host
    env_file:
      - .env
    volumes:
      - ./downloads:/root/downloads
      - ./cookies:/root/cookies
      - ./cookies_enabled.json:/root/cookies_enabled.json
      - ./rclone:/root/.config/rclone
      - ./user_configs:/app/user_configs
      - .:/app
EOF
  fi
}

start_compose() {
  if docker_compose_ok; then
    run_root docker compose -f "$RUNTIME_COMPOSE_FILE" up -d --build --remove-orphans
    run_root docker compose -f "$RUNTIME_COMPOSE_FILE" ps
    return 0
  fi
  if has_cmd docker-compose; then
    run_root docker-compose -f "$RUNTIME_COMPOSE_FILE" up -d --build --remove-orphans
    run_root docker-compose -f "$RUNTIME_COMPOSE_FILE" ps
    return 0
  fi
  die "Neither 'docker compose' nor 'docker-compose' is available."
}

log_step "Checking project context"
cd "$PROJECT_DIR"
[ -f "$PROJECT_DIR/docker-compose.yml" ] || die "docker-compose.yml not found. Run this script from the project folder."
[ -f "$PROJECT_DIR/main.py" ] || die "main.py not found. Run this script from the project folder."

log_step "Checking operating system support"
[ -f /etc/os-release ] || die "Cannot detect OS. /etc/os-release not found."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *)
    case "${ID_LIKE:-}" in
      *debian*|*ubuntu*) ;;
      *) die "Unsupported OS '$ID'. This installer supports Ubuntu/Debian only." ;;
    esac
    ;;
esac
log_ok "Supported OS detected: ${PRETTY_NAME:-$ID}"

log_step "Installing/checking system dependencies"
missing_tools=""
for tool in git curl unzip; do
  if ! has_cmd "$tool"; then
    missing_tools="$missing_tools $tool"
  fi
done
if [ -n "$missing_tools" ]; then
  # shellcheck disable=SC2086
  apt_install $missing_tools
fi

if ! has_cmd docker; then
  log_warn "Docker not found. Installing docker.io..."
  apt_install docker.io
fi

if ! docker_compose_ok; then
  log_warn "Docker Compose plugin not found. Installing..."
  if ! apt_install docker-compose-plugin; then
    log_warn "docker-compose-plugin package unavailable. Installing docker-compose fallback."
    apt_install docker-compose
  fi
fi

if has_cmd systemctl; then
  run_root systemctl enable --now docker >/dev/null 2>&1 || run_root systemctl start docker >/dev/null 2>&1 || true
else
  run_root service docker start >/dev/null 2>&1 || true
fi

run_root docker info >/dev/null 2>&1 || die "Docker daemon is not usable. Check docker service status and user permissions."
log_ok "Docker is ready."

log_step "Preparing required folders/files"
ensure_dir_path "$PROJECT_DIR/downloads"
ensure_dir_path "$PROJECT_DIR/cookies"
ensure_dir_path "$PROJECT_DIR/user_configs"
ensure_regular_file "$PROJECT_DIR/cookies_enabled.json" "{}"
log_ok "Base paths are ready."

log_step "Configuring .env (required values + safe defaults)"
ensure_regular_file "$ENV_FILE" ""

review_mode=0
skip_optional=0

if all_required_present; then
  choice="$(prompt_choice_1_2)"
  if [ "$choice" = "1" ]; then
    review_mode=1
  else
    skip_optional=1
  fi
fi

if [ "$review_mode" -eq 1 ]; then
  review_or_edit_env "DOWNLOADER_BOT_TOKEN" "Enter DOWNLOADER_BOT_TOKEN (from @BotFather)" 0 0
  review_or_edit_env "TELEGRAM_API_ID" "Enter TELEGRAM_API_ID (from my.telegram.org)" 0 1
  review_or_edit_env "TELEGRAM_API_HASH" "Enter TELEGRAM_API_HASH (from my.telegram.org)" 0 0
  review_or_edit_env "ADMIN_ID" "Enter ADMIN_ID (your Telegram numeric user id)" 0 1
else
  ensure_required_env "DOWNLOADER_BOT_TOKEN" "Enter DOWNLOADER_BOT_TOKEN (from @BotFather)" 0 0
  ensure_required_env "TELEGRAM_API_ID" "Enter TELEGRAM_API_ID (from my.telegram.org)" 0 1
  ensure_required_env "TELEGRAM_API_HASH" "Enter TELEGRAM_API_HASH (from my.telegram.org)" 0 0
  ensure_required_env "ADMIN_ID" "Enter ADMIN_ID (your Telegram numeric user id)" 0 1
fi

set_default_if_missing "REGISTRATION_OPEN" "false"
set_default_if_missing "MAX_DAILY_FILES" "20"
set_default_if_missing "MAX_DAILY_BYTES" "5368709120"
set_default_if_missing "MAX_CONCURRENT_DOWNLOADS" "2"
set_default_if_missing "COLAB_URL" "$COLAB_DEFAULT_URL"

local_env_raw="$(env_get TELEGRAM_LOCAL || true)"
if [ -n "$local_env_raw" ] && is_truthy "$local_env_raw"; then
  local_enabled="enabled"
else
  local_enabled="disabled"
fi

ask_local=0
if [ "$review_mode" -eq 1 ]; then
  ask_local=1
elif [ -z "$local_env_raw" ]; then
  ask_local=1
fi

if [ "$skip_optional" -eq 1 ] && [ "$ask_local" -eq 1 ] && [ -n "$local_env_raw" ]; then
  ask_local=0
fi

if [ "$ask_local" -eq 1 ]; then
  printf "Enable Local Telegram Bot API server?\n"
  printf "%s\n" "- YES: removes 20MB limit, supports up to 2GB uploads"
  printf "%s\n" "- NO: simpler setup, 20MB limit applies"
  if prompt_yes_no "Enable Local Telegram Bot API server" "y"; then
    env_set "TELEGRAM_LOCAL" "1"
    local_enabled="enabled"
  else
    env_set "TELEGRAM_LOCAL" "0"
    local_enabled="disabled"
  fi
else
  if [ "$local_enabled" = "enabled" ]; then
    env_set "TELEGRAM_LOCAL" "1"
  else
    env_set "TELEGRAM_LOCAL" "0"
  fi
fi

if [ "$local_enabled" = "enabled" ]; then
  ensure_dir_path "$PROJECT_DIR/telegram-bot-api-data"
fi

# Google Drive optional flow
rclone_path="$PROJECT_DIR/rclone.conf"
if [ -e "$rclone_path" ] && [ -d "$rclone_path" ]; then
  die "Path '$rclone_path' must be a file, but a directory exists there."
fi

drive_enabled="disabled"
if [ -f "$rclone_path" ] && [ -s "$rclone_path" ]; then
  drive_enabled="enabled"
fi

ask_drive=0
if [ "$review_mode" -eq 1 ]; then
  ask_drive=1
elif [ ! -f "$rclone_path" ]; then
  ask_drive=1
fi

if [ "$skip_optional" -eq 1 ] && [ "$ask_drive" -eq 1 ] && [ -f "$rclone_path" ]; then
  ask_drive=0
fi

if [ "$ask_drive" -eq 1 ]; then
  printf "Enable Google Drive uploads via rclone?\n"
  printf "%s\n" "- YES: files can be uploaded to Google Drive"
  printf "%s\n" "- NO: all files sent to Telegram only"
  if prompt_yes_no "Enable Google Drive uploads via rclone" "n"; then
    if [ -s "$rclone_path" ]; then
      log_ok "Existing rclone.conf file detected."
      drive_enabled="enabled"
    else
      if prompt_yes_no "Do you already have an rclone.conf file" "n"; then
        while :; do
          printf "Enter full path to your rclone.conf: "
          IFS= read -r rclone_src
          [ -n "$rclone_src" ] || { log_warn "Path cannot be empty."; continue; }
          if [ ! -f "$rclone_src" ]; then
            log_warn "File not found: $rclone_src"
            continue
          fi
          cp "$rclone_src" "$rclone_path"
          drive_enabled="enabled"
          log_ok "Copied rclone.conf into project root."
          break
        done
      else
        touch "$rclone_path"
        drive_enabled="disabled"
        colab_url="$(env_get COLAB_URL || true)"
        [ -n "$colab_url" ] || colab_url="$COLAB_DEFAULT_URL"
        log_warn "Google Drive is not configured yet. Bot will run in Telegram-only mode."
        printf "\nFollow these steps later:\n"
        printf "1) Open your Colab link:\n   %s\n" "$colab_url"
        printf "2) Run it and download the generated rclone.conf file.\n"
        printf "3) Upload/copy that file to this server and replace:\n   %s/rclone.conf\n" "$PROJECT_DIR"
        printf "4) Re-run this script (or restart containers).\n\n"
      fi
    fi
  else
    touch "$rclone_path"
    drive_enabled="disabled"
    log_warn "Google Drive disabled. Telegram-only mode is active."
  fi
else
  ensure_regular_file "$rclone_path" ""
  if [ -s "$rclone_path" ]; then
    drive_enabled="enabled"
  else
    drive_enabled="disabled"
  fi
fi

# Hard safety guard before compose
ensure_regular_file "$PROJECT_DIR/cookies_enabled.json" "{}"
ensure_regular_file "$rclone_path" ""

if [ ! -s "$PROJECT_DIR/cookies_enabled.json" ]; then
  printf "{}" > "$PROJECT_DIR/cookies_enabled.json"
fi

if [ "$local_enabled" = "enabled" ]; then
  generate_runtime_compose "1"
else
  generate_runtime_compose "0"
fi

printf "\n=== Setup summary ===\n"
printf "Local Bot API : %s\n" "$local_enabled"
printf "Google Drive  : %s\n" "$drive_enabled"
printf "Bot token     : set\n"
printf "Admin ID      : set\n"

if ! prompt_yes_no "Proceed?" "y"; then
  log_warn "Setup canceled before launch."
  exit 0
fi

log_step "Starting services"
start_compose

printf "\n"
log_ok "Setup completed."
printf "Next checks:\n"
printf "  - docker compose -f %s ps\n" "$RUNTIME_COMPOSE_FILE"
printf "  - docker compose -f %s logs -f telegram-bot\n" "$RUNTIME_COMPOSE_FILE"
if [ "$local_enabled" = "enabled" ]; then
  printf "  - docker compose -f %s logs -f telegram-bot-api\n" "$RUNTIME_COMPOSE_FILE"
fi
