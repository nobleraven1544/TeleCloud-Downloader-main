import os
print("API_ID:", os.environ.get("TELEGRAM_API_ID"))
print("API_HASH:", (os.environ.get("TELEGRAM_API_HASH") or "")[:12])
print("TOKEN:", bool(os.environ.get("DOWNLOADER_BOT_TOKEN")))
