# TeleCloud-Downloader Setup Guide

> Persian version: [SETUP_FA.md](./SETUP_FA.md)
> Main docs: [README.md](./README.md)

## Overview

This guide explains how to deploy and run TeleCloud-Downloader in production (Docker) and locally (non-Docker).

## Docker Setup (Recommended)

### 1. Prerequisites

- Docker Engine
- Docker Compose v2 (`docker compose`)
- Git

### 2. Clone

```bash
git clone https://github.com/parsa-f/TeleCloud-Downloader.git
cd TeleCloud-Downloader
```

### 3. Create required host files before first run

These files must exist as files on host before `docker compose up`:

```bash
touch cookies_enabled.json
touch rclone.conf
```

Verify:

```bash
ls -la
```

### 4. Configure `.env`

At minimum:

```env
DOWNLOADER_BOT_TOKEN=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_LOCAL=1
ADMIN_ID=123456789
```

### 5. Start

```bash
docker compose up -d --build
docker compose ps
```

## Local Run (Non-Docker)

### 1. Prerequisites

- Python 3.11+
- `ffmpeg`
- `aria2c`
- `rclone`
- Local Telegram Bot API server configured and running

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python3 main.py
```
