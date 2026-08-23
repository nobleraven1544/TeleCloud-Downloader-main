<div dir="rtl">

# راهنمای نصب TeleCloud-Downloader

> نسخه انگلیسی: [SETUP.md](./SETUP.md)
> مستند اصلی: [README_FA.md](./README_FA.md)

## نمای کلی

این راهنما روش استقرار و اجرای TeleCloud-Downloader را در حالت production (Docker) و حالت محلی (بدون Docker) توضیح می‌دهد.

## راه‌اندازی با Docker (پیشنهادی)

### 1. پیش‌نیازها

- Docker Engine
- Docker Compose v2 (`docker compose`)
- Git

### 2. Clone

```bash
git clone https://github.com/parsa-f/TeleCloud-Downloader.git
cd TeleCloud-Downloader
```

### 3. ساخت فایل‌های لازم روی هاست قبل از اجرای اول

این فایل‌ها باید قبل از `docker compose up` روی هاست به‌صورت فایل وجود داشته باشند:

```bash
touch cookies_enabled.json
touch rclone.conf
```

بررسی:

```bash
ls -la
```

### 4. پیکربندی `.env`

حداقل مقادیر:

```env
DOWNLOADER_BOT_TOKEN=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_LOCAL=1
ADMIN_ID=123456789
```

### 5. اجرا

```bash
docker compose up -d --build
docker compose ps
```

## اجرای محلی (بدون Docker)

### 1. پیش‌نیازها

- Python 3.11+
- `ffmpeg`
- `aria2c`
- `rclone`
- Local Telegram Bot API server تنظیم و اجرا شده باشد

### 2. نصب وابستگی‌های پایتون

```bash
pip install -r requirements.txt
```

### 3. اجرا

```bash
python3 main.py
```


</div>
