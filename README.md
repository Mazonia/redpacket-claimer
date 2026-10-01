# 🎁 Binance Red Packet & Binance Square Auto-Claimer

A high-performance, automated Python application that monitors Telegram channels for Binance Red Packet (Crypto Box) codes and Binance Square Comment-to-Earn reward drops, automatically redeeming them on Binance in real-time.

---

## ✨ Features

- **⚡ Direct Red Packet / Crypto Box Claiming**:
  - Automatically captures dropped codes (e.g. `🎁  I8C23DTN`, `BP...`) and claims them on the official Binance Crypto Box page (`https://www.binance.com/en/my/wallet/account/payment/cryptobox`).
  - Auto-clicks **Claim Now** and the **Open** modal to credit rewards directly to your Binance Funding Wallet.

- **💬 Binance Square Comment-to-Earn Automation**:
  - Detects Binance Feed / Square posts (e.g. `app.binance.com/uni-qr/cpos/...` or `binance.com/en/square/post/...`).
  - Extracts answers enclosed in `❕...❕` (e.g. `𝑨𝒏𝒔𝒘𝒆𝒓 :❕20.8k❕`).
  - Automatically opens the post, fills the answer into the answer/comment box, submits, and claims the reward!

- **🕰️ Historical Catch-Up Mode**:
  - On launch, automatically scans the channel's recent history to retrieve and claim the **last 5 codes** and **last 5 questions** you might have missed before transitioning into live mode.

- **💾 Local Cache & Duplicate Prevention**:
  - Keeps a local `claimed_cache.json` to prevent re-submitting previously processed codes or triggering rate limits.

- **🔐 100% Private & Persistent Session**:
  - **Telegram Session**: Telethon runs locally on your machine. No tokens or messages are shared externally.
  - **Binance Session**: Uses Playwright's persistent Chromium browser context (`./user_data/`). Log into Binance **once** manually with 2FA; your session is preserved across runs.

- **🎨 Modern Rich Terminal UI**:
  - Colored tables, live drop panels, status logs, and humanized stealth delays.

---

## 📁 Project Architecture

```
binance-auto-claimer/
├── main.py            # Orchestrator: Historical catch-up, live Telegram listener & claim dispatcher
├── parser.py          # Regex parser: Isolates 8-char codes, Binance Square links & answers
├── redemption.py      # Playwright automation engine: Handles UI navigation, typing, and claiming
├── requirements.txt   # Python dependencies
├── .env.example       # Template configuration file
├── .gitignore         # Protects credentials, session files, and browser cookies
└── README.md          # Project documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.9+
- A Binance account
- A Telegram account with API credentials from [my.telegram.org](https://my.telegram.org)

### 2. Installation

Clone the repository and install dependencies:
```bash
git clone https://github.com/Mazonia/redpacket-claimer.git
cd redpacket-claimer

pip install -r requirements.txt
python -m playwright install chromium
```

### 3. Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your details:
   ```env
   # Telegram API Credentials (from https://my.telegram.org)
   TELEGRAM_API_ID=your_api_id_here
   TELEGRAM_API_HASH=your_api_hash_here

   # Your Telegram phone number in international format (+...)
   TELEGRAM_PHONE=+1234567890

   # Target Channel to monitor
   TARGET_CHANNEL=@your_channel_name

   # Playwright Configuration
   HEADLESS=false
   USER_DATA_DIR=./user_data
   ```

---

## 🏃 Running the Auto-Claimer

Start the application:
```bash
python main.py
```

### First-Time Run Flow:
1. **Telegram Authorization**: Telethon will connect using your phone number and prompt for the 5-digit code sent to your Telegram app. This generates your local `binance_session.session`.
2. **Binance Session**: Chromium will open to `https://www.binance.com/en/my/wallet/account/payment/cryptobox`. Log in manually (solve 2FA). Your session is saved to `./user_data/` so you won't need to log in again.
3. **Catch-Up & Live Monitoring**:
   - The bot scans the channel for the last 5 codes and last 5 questions and claims them.
   - It then remains running in the background, claiming new drops within seconds!

---

## 🛡️ Security Best Practices

- **Never commit `.env` or `*.session` files**: They contain your sensitive credentials. The repository includes a preconfigured `.gitignore` to prevent leaks.
- **Stealth & Rate Limits**: The script incorporates randomized delays (`_human_delay`) and browser flags to mimic natural user behavior and protect against bot detection.

---

## 📜 License

MIT License. For educational and personal automation purposes.
