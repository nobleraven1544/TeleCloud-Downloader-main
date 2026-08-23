<div dir="rtl">

# شروع سریع TeleCloud-Downloader (مبتدی)

> نسخه انگلیسی: [QUICKSTART.md](./QUICKSTART.md)  
> راهنمای کامل نصب: [SETUP_FA.md](./SETUP_FA.md)

این راهنما برای کاربرانی است که می‌خواهند روی Ubuntu/Debian با یک مسیر ساده و یک‌دستور راه‌اندازی را انجام دهند.

## پیش‌نیازها

- سرور Ubuntu/Debian
- دسترسی به اینترنت
- یک کاربر با دسترسی `sudo`

## دریافت پروژه

مخزن را از GitHub کلون کنید:

```bash
git clone https://github.com/parsa-f/TeleCloud-Downloader.git
cd TeleCloud-Downloader
```

یا فایل ZIP را دانلود و extract کنید:

```bash
curl -L https://github.com/parsa-f/TeleCloud-Downloader/archive/refs/heads/main.zip -o telecloud.zip
unzip telecloud.zip
cd TeleCloud-Downloader-main
```

## اجرای نصب‌کننده

از ریشه پروژه:

```bash
chmod +x start.sh
./start.sh
```

## اسکریپت `start.sh` چه کار می‌کند

- ابزارهای لازم و Docker stack را نصب/بررسی می‌کند
- پوشه‌ها و فایل‌های ضروری را به‌صورت امن می‌سازد
- تنظیمات ضروری ربات را از شما می‌گیرد (`DOWNLOADER_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ADMIN_ID`)
- حالت بازپیکربندی دارد تا مقادیر فعلی `.env` را بازبینی/ویرایش کنید
- امکان انتخاب Local Bot API mode و Google Drive mode را می‌دهد
- از کنترل دسترسی مبتنی بر تایید استفاده می‌کند (`REGISTRATION_OPEN` + فرایند تایید ادمین)
- قبل از اجرا خلاصه نشان می‌دهد و تایید نهایی می‌گیرد
- کانتینرها را با یک فایل compose زمان‌اجرا که خودکار تولید می‌شود بالا می‌آورد

## حالت‌های استقرار

### 1) حالت کامل (Local API + Drive)

- `TELEGRAM_LOCAL=1`
- سرویس محلی `telegram-bot-api` فعال است
- پشتیبانی از آپلود تا 2GB
- `rclone.conf` برای آپلود به Drive تنظیم می‌شود

### 2) حالت بدون Drive (فقط Local API)

- `TELEGRAM_LOCAL=1`
- سرویس محلی `telegram-bot-api` فعال است
- پشتیبانی از آپلود تا 2GB
- Drive غیرفعال است؛ ربات فقط با ارسال تلگرام کار می‌کند
- نصب‌کننده همچنان مطمئن می‌شود `./rclone.conf` به‌صورت فایل placeholder وجود داشته باشد

### 3) حالت ساده (بدون Local API و بدون Drive)

- `TELEGRAM_LOCAL=0`
- سرویس محلی `telegram-bot-api` اجرا نمی‌شود
- حالت cloud API تلگرام (محدودیت 20MB اعمال می‌شود)
- Drive غیرفعال؛ جریان کار فقط تلگرام

## رفتار در اجرای مجدد

می‌توانید هر زمان `./start.sh` را دوباره اجرا کنید:

- اگر `.env` کامل باشد، از شما می‌پرسد:
  - `1) Review / edit existing values`
  - `2) Keep existing values and continue`
- اگر گزینه continue را انتخاب کنید، حالت‌های اختیاری قبلی دوباره استفاده می‌شوند
- فایل‌های ایمنی ضروری همیشه اعمال می‌شوند:
  - `cookies_enabled.json` باید یک فایل حاوی `{}` باشد
  - `rclone.conf` باید فایل باشد (اگر Drive غیرفعال باشد فایل placeholder ساخته می‌شود)

</div>
