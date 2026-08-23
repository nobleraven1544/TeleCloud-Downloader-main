<div align="center">
  <h1>☁️ TeleCloud-Downloader</h1>
  <p><strong>Advanced, Fully Modular Asynchronous Telegram Download Manager</strong></p>

  <a href="./README_FA.md">🇮🇷 مستندات فارسی</a>
  <br>
  <a href="./QUICKSTART.md">⚡ Quick Start (Beginners)</a> · <a href="./QUICKSTART_FA.md">⚡ شروع سریع فارسی</a>
  <br>
  <a href="./SETUP.md">🛠️ Setup Guide</a> · <a href="./SETUP_FA.md">🛠️ راهنمای نصب فارسی</a>
  <br><br>

  <!-- Badges -->
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/pyTelegramBotAPI-Latest-229ED9.svg?logo=telegram&logoColor=white" alt="pyTelegramBotAPI">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/yt--dlp-Powered-FF0000.svg?logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/Local%20Bot%20API-2GB%20Uploads-26A69A.svg?logo=telegram&logoColor=white" alt="Local Bot API">
  <img src="https://img.shields.io/badge/License-MIT-22C55E.svg" alt="License">
</div>

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🤔 Why TeleCloud-Downloader?](#-why-telecloud-downloader)
- [🏗️ Architecture Overview](#-architecture-overview)
- [🛠️ Tech Stack](#-tech-stack)
- [🚀 Installation & Deployment](#-installation--deployment)
- [💬 Usage & Commands](#-usage--commands)
- [⚙️ Configuration Reference](#-configuration-reference)
- [📁 Project Structure](#-project-structure)
- [💾 Data Persistency & Volumes](#-data-persistency--volumes)
- [🔒 Security Notes](#-security-notes)
- [🐛 Troubleshooting & FAQ](#-troubleshooting--faq)
- [📄 License](#-license)

---

## ✨ Features

### 🚀 Multi-Engine Downloader

#### 🌐 Supported Sites (yt-dlp)
Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), the bot supports **thousands of websites**. Here are the most popular ones:

| Platform | Type |
|---|---|
| YouTube | Videos, Playlists, Shorts, Live streams |
| Instagram | Reels, Posts, Stories, IGTV |
| X (Twitter) | Videos, GIFs |
| TikTok | Videos |
| SoundCloud | Tracks, Playlists |
| Vimeo | Videos |
| Dailymotion | Videos |
| Reddit | Videos, GIFs |
| Pinterest | Videos |
| Twitch | Clips, VODs |
| Facebook | Videos, Reels |


> This is just a highlight — [yt-dlp supports 1000+ sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md). If a URL works with yt-dlp, it works here.

#### 🧲 Torrent & Magnet Links
Send any **BitTorrent magnet link** (`magnet:?xt=urn:btih:...`) directly to the bot. The torrent engine will download the content and deliver it to Telegram or Google Drive — no torrent client needed on your end.

#### 🔗 Direct Link Downloader
Send any raw HTTP/HTTPS file URL and the bot will download it directly — PDFs, ZIPs, MP4s, or any other file type.

---

### ☁️ Google Drive Integration via Rclone

Every downloaded file can be routed directly to your **Google Drive** using [Rclone](https://rclone.org/). No manual transfers, no storage worries:

- **📂 Per-user Drive config** — Each user uploads their own `rclone.conf` file to the bot. The bot stores it privately and uses it for that user's Drive uploads.
- **🔄 Three destination modes** — Toggle between `Telegram`, `Google Drive`, or `Ask every time` directly from the Settings panel.
- **⚡ Auto-reroute for large files** — If a file exceeds 2 GB, the bot automatically uploads it to Drive even if Telegram was selected.
- **🔗 Direct Drive links** — After every Drive upload, the bot sends a direct shareable link to the file.
- **🗂️ Admin folder routing** — The admin can set a `DRIVE_FOLDER_ID` to control the default upload destination for their own uploads.
- **🔧 Easy setup via Google Colab** — Setting up `rclone.conf` doesn't require any technical knowledge. The bot provides a ready-made Google Colab notebook: open it, run it, log in to your Google account, download the generated `rclone.conf`, and send it directly to the bot. Done.
- **🔌 Connect & disconnect anytime** — Users can disconnect their Drive at any time from the Settings panel, which deletes their personal config from the bot.

---

### 🔥 Local Telegram Bot API Server — No More File Size Limits
> This is the most critical architectural feature of TeleCloud-Downloader.

Unlike standard bots that are capped by Telegram's default **20 MB download / 50 MB upload** limits, TeleCloud-Downloader runs its own **self-hosted Local Telegram Bot API Server** (`aiogram/telegram-bot-api`). This completely bypasses Telegram's cloud restrictions:

- **📦 Supports files up to 2 GB** — download and send massive video, audio, and archive files without restrictions.
- **⚡ Lightning-fast local file transfers** — In local mode, the bot reads files directly from shared local Bot API storage (`/var/lib/telegram-bot-api`) and falls back to cloud download only when needed.
- **🔒 Private & self-contained** — All API traffic stays on your own server (`http://localhost:8081`), never touching Telegram's cloud API endpoint.

### 🎛️ Advanced Settings Panel
- **Video Mode:** Cycle between `mp4`, `mkv`, or `default` format.
- **Audio Mode:** Cycle between `mp3`, `m4a`, `flac`, or `default` format.
- **Video Quality:** 480p / 720p / 1080p / 1440p (2K) / 2160p (4K) / Best
- **Audio Quality:** 128 kbps / 192 kbps / 320 kbps

### 📝 Smart Subtitle Embedding (Muxing)
Hard and soft subtitle embedding for English and Persian subtitles via FFmpeg, with a graceful fallback mechanism — if subtitles are unavailable, the bot downloads and sends the video without crashing.

### ⏱️ YouTube Chapters Extraction
Automatically extracts and injects native YouTube timestamp chapters into downloaded video files using FFmpeg metadata injection.

### 🌐 Bilingual UI & 🍪 Cookie Manager
Full Persian and English localization. Includes an interactive cookie manager (via `.txt` file uploads) to bypass age restrictions or access private playlists.

---

## 🤔 Why TeleCloud-Downloader?

There are two common types of Telegram download bots:

- **Heavy mirror/leech bots** — Extremely powerful, but complex to install, require significant server resources, and have no Persian UI.
- **Simple yt-dlp bots** — Easy to use, but limited to yt-dlp only, no torrent, no Google Drive, no Local API.

TeleCloud-Downloader sits in between — powerful enough for real use, simple enough for anyone to deploy:

| | Heavy bots | Simple bots | TeleCloud-Downloader |
|---|---|---|---|
| Torrent support | ✅ | ❌ | ✅ |
| Google Drive upload | ✅ | ❌ | ✅ |
| 2 GB file support | ✅ | ❌ | ✅ |
| One-command install | ❌ | ✅ | ✅ |
| Persian UI | ❌ | ❌ | ✅ |
| Persian subtitles | ❌ | ❌ | ✅ |
| Per-user Drive config | ❌ | ❌ | ✅ |

---

## 🏗️ Architecture Overview

TeleCloud-Downloader runs with two deployment modes:

- **Local API mode (`TELEGRAM_LOCAL=1`)**: `telegram-bot` + `telegram-bot-api`
- **Cloud API mode (`TELEGRAM_LOCAL=0`)**: `telegram-bot` only

Local API mode architecture:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Docker Host (Host Network)              │
│                                                             │
│  ┌────────────────────┐    ┌─────────────────────────────┐  │
│  │  telegram-bot-api  │    │       telegram-bot          │  │
│  │  Port: 8081        │◄───│  Uses localhost Bot API     │  │
│  └────────────┬───────┘    └────────────┬────────────────┘  │
│               │                          │                   │
│               └──────────────────────────┘                   │
│      Shared local API storage: /var/lib/telegram-bot-api       │
└─────────────────────────────────────────────────────────────┘
```

**Important runtime detail:** In local mode, `bot.get_file()` can return a relative path. The bot reconstructs the absolute path under `/var/lib/telegram-bot-api/...` before reading the file, with cloud download fallback when needed.

---

## 🛠️ Tech Stack

| Component | Technology | Role |
|---|---|---|
| **Local Bot API** | `aiogram/telegram-bot-api:latest` | ⭐ Removes file size limits → supports up to **2 GB** |
| **Runtime** | Python 3.11+ | Core application language |
| **Bot Framework** | pyTelegramBotAPI | Telegram Bot API integration |
| **Download Engine** | yt-dlp | Multi-platform media downloads |
| **Media Processing** | FFmpeg | Subtitle muxing, chapters, encoding |
| **Containerization** | Docker + Docker Compose | Full service orchestration |
| **Cloud Storage** | Rclone | Google Drive upload integration |
| **Source Control** | Git + GitHub | Version-controlled deployment workflow |

---

## 🚀 Installation & Deployment

Choose the guide that fits your situation:

| Guide | Who it's for |
|---|---|
| [⚡ QUICKSTART.md](./QUICKSTART.md) | First-time setup on Ubuntu/Debian — one-command installer (`start.sh`) |
| [🛠️ SETUP.md](./SETUP.md) | Manual Docker setup, advanced configuration, non-Docker local run |

---

## 💬 Usage & Commands

### 👥 Multi-User Access Control

TeleCloud-Downloader supports multiple users with an approval-based access system.

**When a new user sends `/start`:**
- If `REGISTRATION_OPEN=true` — the user is approved instantly and can start using the bot.
- If `REGISTRATION_OPEN=false` — the user sees a join request button. The admin receives the request and can approve or reject it.

**Admin commands for user management:**

| Command | Description |
|---|---|
| `/adduser <id>` | Manually approve a user by Telegram ID |
| `/deluser <id>` | Ban a user and immediately cancel all their active and queued tasks |
| `/setquota <id> <files> <GB>` | Set a custom daily download quota for a specific user |
| `/users` | Open the admin user management panel |
| `/togglereg` | Toggle open/closed self-registration mode |
| `/broadcast` | Send a message to all approved users |

**Admin panel (`/users`)** allows browsing all users, viewing their details, enabling/disabling accounts, and adjusting quotas interactively.

**Quota system:**
- Global defaults are set via `MAX_DAILY_FILES` and `MAX_DAILY_BYTES` in `.env`.
- The admin can override quotas per user individually with `/setquota` or from the admin panel.
- Quotas reset daily.

### 🙋 Regular User Capabilities

Once approved, users can:

- Send any supported URL or magnet link to start a download
- Upload files/media directly to the bot — the bot sends them to Drive
- Upload a personal `rclone.conf` to connect their own Google Drive
- Toggle download destination between Telegram, Drive, or Ask-every-time
- Adjust video/audio quality, format, subtitles, and chapters from the Settings panel
- Manage cookies (add, enable, disable, rename, delete)
- View their download queue and remove items from it
- Cancel any running download or upload task at any time
- Disconnect their personal Drive config from the Settings panel

### Downloading Media

Send any supported URL or magnet link directly to the bot:

| Input Type | Example |
|---|---|
| YouTube Video | `https://www.youtube.com/watch?v=...` |
| YouTube Playlist | `https://www.youtube.com/playlist?list=...` |
| SoundCloud / Instagram / X | Any yt-dlp-supported URL |
| BitTorrent Magnet Link | `magnet:?xt=urn:btih:...` |
| Direct File URL | `https://example.com/largefile.mp4` |

### Settings Panel

Send `/settings` or tap the **⚙️ Settings** button to open the interactive inline panel:

| Setting | Options |
|---|---|
| **Media Mode** | 🎬 Video / 🎵 Audio |
| **Video Quality** | 480p / 720p / 1080p / 1440p / 2160p / Best |
| **Video Format** | MP4 / MKV / Default |
| **Audio Quality** | 128 kbps / 192 kbps / 320 kbps |
| **Audio Format** | MP3 / M4A / FLAC / Default |
| **Upload Destination** | 📨 Telegram / ☁️ Google Drive |
| **Subtitles** | Off / English / Persian |
| **Chapters** | On / Off |
| **Download Mode** | Auto / yt-dlp / Torrent / Direct |

### Cookie Management

To bypass age restrictions or access private content, upload a **Netscape-format** cookies `.txt` file directly to the bot chat. The cookie manager will process and store it securely.

---

## ⚙️ Configuration Reference

Runtime configuration in `config.py` reads the following `.env` variables:

| Variable | Required | Description |
|---|---|---|
| `DOWNLOADER_BOT_TOKEN` | ✅ Yes | Your Telegram Bot Token from @BotFather |
| `TELEGRAM_API_ID` | ✅ Yes (Local mode) | Telegram API ID from my.telegram.org — required for Local Bot API mode |
| `TELEGRAM_API_HASH` | ✅ Yes (Local mode) | Telegram API Hash from my.telegram.org — required for Local Bot API mode |
| `DRIVE_FOLDER_ID` | ⬜ Optional | Default Google Drive root folder ID — applies to admin uploads only |
| `ADMIN_ID` | ✅ Yes | Telegram numeric user ID for the bot administrator |
| `REGISTRATION_OPEN` | ⬜ Optional | `true/false` toggle for self-registration on `/start` |
| `MAX_DAILY_FILES` | ⬜ Optional | Default daily file-count quota per user |
| `MAX_DAILY_BYTES` | ⬜ Optional | Default daily byte quota per user |
| `COLAB_URL` | ⬜ Optional | Colab link shown for Drive onboarding |
| `MAX_CONCURRENT_DOWNLOADS` | ⬜ Optional | Parallel download worker limit |
| `TELEGRAM_LOCAL` | ⬜ Optional | `1/true` enables local Bot API mode; `0/false` uses cloud Bot API |

`start.sh` also collects `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` for local Bot API server deployment.

---

## 📁 Project Structure

```text
TeleCloud-Downloader/
├── Dockerfile                  # Bot container build definition
├── docker-compose.yml          # Full multi-container service orchestration
├── .env                        # (Excluded from Git) Secrets & API credentials
├── .gitignore                  # Excludes downloads/, cookies, .env, JSON DBs
├── main.py                     # Bot entry point — always runs from here
├── config.py                   # All settings, shared state, bot object
├── handlers.py                 # Message and command handlers
├── callbacks.py                # Inline keyboard callback query processing
├── menu.py                     # Telegram markup / keyboard builders
├── playlist_menu.py            # YouTube playlist-specific menus
├── dest_helpers.py             # Upload destination routing (Telegram vs Drive)
├── downloader_queue.py         # Async task queue and worker management
├── cookies.py                  # Cookie manager logic
├── utils.py                    # Shared utilities and helper functions
├── user_langs.py               # Per-user language persistence
├── downloaders/                # Download engines
│   ├── __init__.py
│   ├── youtube.py              #   yt-dlp (YouTube, social platforms)
│   ├── social.py               #   General social platform handler
│   ├── torrent.py              #   BitTorrent / magnet link engine
│   └── direct.py              #   Direct HTTP file downloader
└── uploaders/                  # Upload engines
    ├── __init__.py
    ├── telegram_upload.py      #   Local Telegram API uploader
    ├── gdrive_upload.py        #   Rclone / Google Drive uploader
    └── smart_dest.py          #   Destination routing logic
```

---

## 💾 Data Persistency & Volumes

All persistent data lives **on the host machine** via Docker bind mounts, ensuring it survives container restarts and image rebuilds:

| Host Path | Container Path | Service | Contents |
|---|---|---|---|
| `./telegram-bot-api-data` | `/var/lib/telegram-bot-api` | `telegram-bot-api` | Local API server session data |
| `./downloads` | `/root/downloads` | Both containers | Shared file staging area (the 2GB transfer bridge) |
| `./cookies` | `/root/cookies` | `telegram-bot` | Netscape-format cookie files |
| `./cookies_enabled.json` | `/root/cookies_enabled.json` | `telegram-bot` | Cookie activation state |
| `./rclone.conf` | `/root/.config/rclone/rclone.conf` | `telegram-bot` | Default Google Drive rclone config file |
| `./user_configs` | `/app/user_configs` | `telegram-bot` | SQLite DB and per-user config files |
| `.` | `/app` | `telegram-bot` | **Live-mounted** bot source code |
| `./telegram-bot-api-data` | `/var/lib/telegram-bot-api` (ro) | `telegram-bot` | Read-only local API file store for direct file reads |

The two `telegram-bot-api-data` mounts are only used when Local API mode is enabled (`TELEGRAM_LOCAL=1`).

> **Tip:** To perform a clean reinstall without losing user data, rebuild only the image: `docker compose build && docker compose up -d`

---

## 🔒 Security Notes

- **Access Control:** The bot enforces approval-based access control. Users are admitted through `REGISTRATION_OPEN` policy and/or admin approval.
- **Secret Management:** Keep `.env` out of version control. At minimum it contains bot token and deployment/runtime settings.
- **Local API Isolation:** The Local Telegram Bot API server only listens on `localhost:8081`. It is not exposed to the public internet.
- **Cookie Safety:** The cookie manager handles `.txt` tokens safely. Keep your cookie files secure and never expose them publicly.
- **Rclone Config:** Your `rclone.conf` contains Google account credentials. It is mounted into the container and should never be committed to Git.

---

## 🐛 Troubleshooting & FAQ

<details>
<summary><strong>🔴 The bot is not responding after deployment</strong></summary>

1. Check services with the same compose file you launched with:
   - Manual: `docker compose ps`
   - `start.sh`: `docker compose -f .start.compose.yml ps`
2. View bot logs:
   - Manual: `docker compose logs -f telegram-bot`
   - `start.sh`: `docker compose -f .start.compose.yml logs -f telegram-bot`
3. If local mode is enabled (`TELEGRAM_LOCAL=1`), also check `telegram-bot-api` logs.
4. Verify `DOWNLOADER_BOT_TOKEN` in `.env` is valid and has no extra spaces.

</details>

<details>
<summary><strong>🔴 "File too large" error or upload fails</strong></summary>

The standard Telegram Bot API caps file uploads at **50 MB**. This project runs a **self-hosted Local Telegram Bot API Server** that raises this limit to **2 GB**. If you are seeing this error:

1. Confirm the `telegram-bot-api` container is running: `docker ps | grep telegram-bot-api`
2. Check its logs: `docker logs -f telegram-bot-api`
3. Verify `TELEGRAM_LOCAL=1` is present in your `.env` file.
4. Ensure the bot is configured to point to `http://localhost:8081`.

</details>

<details>
<summary><strong>🔴 Google Drive upload fails</strong></summary>

1. Confirm `./rclone.conf` exists in the project root and is a **file**.
2. Run `docker exec telegram-bot rclone listremotes` to verify rclone sees your remote.
3. Check that your configured Drive remote has write access to the target folder.

</details>

<details>
<summary><strong>🔴 `[Errno 21] Is a directory` for `cookies_enabled.json` or `rclone.conf`</strong></summary>

Docker can create missing bind-mount targets as directories. Ensure both paths exist as files on the host:

```bash
test -f cookies_enabled.json || printf "{}" > cookies_enabled.json
test -f rclone.conf || touch rclone.conf
```

If either path is currently a directory, remove it and recreate it as a file before restarting containers.

</details>

<details>
<summary><strong>🔴 Local Bot API download fails with 404 for Telegram files</strong></summary>

In local mode, `bot.get_file()` may return a relative path (for example `videos/file_6.mp4`). The bot must reconstruct an absolute path under `/var/lib/telegram-bot-api/...` before reading.

This project already includes that guard, and it depends on this mount in `telegram-bot`:

```yaml
- ./telegram-bot-api-data:/var/lib/telegram-bot-api:ro
```

If you removed that mount, put it back and restart.

</details>

<details>
<summary><strong>🔴 Drive uploads fail because folder ID env key is ignored</strong></summary>

Use exact env key casing: `DRIVE_FOLDER_ID` (uppercase `ID`).  
Wrong casing like `DRIVE_FOLDER_iD` will not be read by runtime config.

</details>

<details>
<summary><strong>🔴 Download fails with "403 Forbidden" or age-restriction error</strong></summary>

You need to provide authentication cookies from a logged-in browser session. Export your cookies in **Netscape format** using a browser extension (e.g., "Get cookies.txt LOCALLY"), then upload the `.txt` file directly to the bot chat.

</details>

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).





