# Setup Guide — Sovereign V3 (Regis)

This document covers every external service Regis uses or will use. Work through sections as needed — everything is optional except the basics.

---

## Quick Start — No Keys Needed

The following work immediately after boot with zero configuration:

- **Chat** — local LLM via Ollama + Mistral (or Gemma 4)
- **File indexing** — ~/Documents, ~/Desktop, ~/Downloads, iCloud Drive
- **Apple Contacts** — via osascript (macOS permission required, see below)
- **Apple Notes** — via AppleScript (macOS permission required, see below)
- **Web search** — DuckDuckGo Instant Answer (no key)
- **Voice input** — Whisper local transcription
- **Dashboard** — full UI, proposals, scan controls
- **macOS automation** — set volume, show notifications, run Shortcuts

---

## 1. Gmail + Calendar (OAuth 2.0)

Needed for: email search, archiving emails, creating calendar events, reading calendar in chat.

### Step-by-step

1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a new project (name it "Regis" or anything)
3. In the left menu: **APIs & Services → Library**
   - Search and enable: **Gmail API**
   - Search and enable: **Google Calendar API**
4. In the left menu: **APIs & Services → OAuth consent screen**
   - User type: **External**
   - Fill in app name ("Regis"), your email, save
   - Scopes: add `gmail.modify` and `calendar`
   - Test users: add your Gmail address
5. In the left menu: **APIs & Services → Credentials**
   - Click **+ Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name it anything, click **Create**
   - Click **Download JSON** → save the file
6. Move the downloaded file:
   ```bash
   mkdir -p ~/Sovereign\ V3/data/.secrets
   chmod 700 ~/Sovereign\ V3/data/.secrets
   mv ~/Downloads/client_secret_*.json ~/Sovereign\ V3/data/.secrets/gmail_creds.json
   chmod 600 ~/Sovereign\ V3/data/.secrets/gmail_creds.json
   ```
7. Trigger the OAuth flow (opens browser once):
   ```bash
   curl -X POST http://localhost:8765/connectors/gmail/scan \
     -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)"
   ```
   - A browser window will open → sign in → grant access → token saved automatically
8. Token auto-refreshes. You only need to repeat step 7 if the token expires (rare).

### Verify
```bash
curl -s http://localhost:8765/connectors/gmail/scan \
  -X POST -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)" | python3 -m json.tool
```
Should return `"status": "OK"` and `items_indexed > 0`.

---

## 2. OpenWeather API

Needed for: 7-day weather forecast in dashboard, weather context in chat.

### Step-by-step

1. Create a free account at [openweathermap.org](https://openweathermap.org/api)
2. Go to **API Keys** tab in your account dashboard
3. Copy your default API key (or create a new one named "Regis")
4. Subscribe to **One Call API 3.0** — it's free up to 1,000 calls/day:
   - Go to [openweathermap.org/api/one-call-3](https://openweathermap.org/api/one-call-3)
   - Click "Subscribe" → choose **Free** tier
5. Edit your env file:
   ```bash
   nano ~/Sovereign\ V3/data/.env
   ```
   Add/update:
   ```
   OPENWEATHER_KEY=your_api_key_here
   ```
6. Restart Regis:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist
   launchctl load ~/Library/LaunchAgents/com.regis.sovereign.plist
   ```

### Verify
```bash
curl -s http://localhost:8765/weather \
  -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)" | python3 -m json.tool
```
Should return `"status": "OK"` with `current` and `daily` arrays.

**Note:** New API keys can take 10–60 minutes to activate on OpenWeather's side.

---

## 3. Philips Hue Bridge

Needed for: controlling smart lights via chat ("turn off the lights", "movie mode", "dim to 30%").

### Step-by-step

**Find your bridge IP:**
1. Open the Hue app on your phone
2. Go to **Settings → My Hue system → Philips Hue → i (info)**
3. Note the IP address (e.g. `192.168.1.50`)

**Get your bridge token:**
1. Press the **physical button** on top of your Hue Bridge (you have ~30 seconds)
2. Immediately run:
   ```bash
   curl -s -X POST http://192.168.1.50/api \
     -H "Content-Type: application/json" \
     -d '{"devicetype":"regis#macbook"}'
   ```
   Replace `192.168.1.50` with your bridge IP.
3. You'll get a response like:
   ```json
   [{"success":{"username":"abc123def456..."}}]
   ```
4. Copy the `username` value — that's your token.

**Save to .env:**
```bash
nano ~/Sovereign\ V3/data/.env
```
Add/update:
```
HUE_BRIDGE_IP=192.168.1.50
HUE_BRIDGE_TOKEN=abc123def456...
```

**Restart Regis**, then scan:
```bash
curl -X POST http://localhost:8765/connectors/hue/scan \
  -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)"
```

### Verify lights are discoverable
```bash
curl -s http://localhost:8765/hue/lights \
  -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)" | python3 -m json.tool
```
Should return your lights with their names and IDs.

### Usage in chat
Once configured, say things like:
- "Turn off the lights"
- "Dim to 20%"
- "Movie mode" (activates a Hue scene named "Movie" if it exists)
- "Turn on light 1"

---

## 4. NewsAPI (Phase 11 — future)

Needed for: daily news headlines indexed into ChromaDB, available in chat.

### Step-by-step

1. Create a free account at [newsapi.org](https://newsapi.org/)
2. Go to **Account → API Key**
3. Copy your key
4. Edit `.env`:
   ```
   NEWS_API_KEY=your_key_here
   ```

Free tier: 100 requests/day, headlines only, 1-month archive.

---

## 5. Telegram Bot (Phase 12 — future)

Needed for: remote access to Regis from your phone, daily digest push, approving proposals remotely.

### Step-by-step

**Create the bot:**
1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. "Regis") and username (e.g. `my_regis_bot`)
4. Copy the token (format: `123456:ABC-DEF...`)

**Get your Telegram user ID:**
1. Search for **@userinfobot** on Telegram
2. Send it any message → it replies with your user ID (a number like `987654321`)

**Save to .env:**
```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ALLOWED_USER_ID=987654321
```

**Security note:** Regis silently ignores all messages from any user ID other than `TELEGRAM_ALLOWED_USER_ID`. Test this with a second account before relying on it.

---

## 6. macOS Permissions

Some connectors require explicit macOS privacy permissions.

### Contacts
> Required for: Contacts connector indexing (`/connectors/contacts/scan`)

1. **System Settings → Privacy & Security → Contacts**
2. Find **Terminal** (or **Python** if running directly) → toggle ON
3. If it doesn't appear, run a scan first — macOS will prompt automatically

### Notes (Automation)
> Required for: Notes connector indexing (`/connectors/notes/scan`)

1. **System Settings → Privacy & Security → Automation**
2. Find **Terminal → Notes** → toggle ON

### Microphone
> Required for: Voice input (mic button in dashboard)

macOS will prompt automatically on first use. If it doesn't:
1. **System Settings → Privacy & Security → Microphone**
2. Toggle ON for Terminal or the app running Regis

---

## 7. Server Restart Reference

Always restart via launchd, never via pkill:

```bash
# Full restart (stop + start)
launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist && \
launchctl load ~/Library/LaunchAgents/com.regis.sovereign.plist

# Check if running
launchctl list | grep regis

# View live logs
tail -f ~/Sovereign\ V3/data/regis.stdout.log

# View error logs
tail -f ~/Sovereign\ V3/data/regis.stderr.log
```

---

## 8. Getting Your API Token

Regis generates a Bearer token on first boot. Every API call requires it.

```bash
# Print your token
cat ~/Sovereign\ V3/data/.api_token

# Use it in curl
curl -H "Authorization: Bearer $(cat ~/Sovereign\ V3/data/.api_token)" \
  http://localhost:8765/snapshot
```

The dashboard injects the token automatically — you only need this for direct API calls.

---

## 9. Verifying Everything Works

Run these after each setup step:

```bash
TOKEN=$(cat ~/Sovereign\ V3/data/.api_token)
BASE="http://localhost:8765"

# Health check (no auth needed)
curl -s $BASE/health

# System snapshot
curl -s -H "Authorization: Bearer $TOKEN" $BASE/snapshot | python3 -m json.tool

# Weather (needs OPENWEATHER_KEY)
curl -s -H "Authorization: Bearer $TOKEN" $BASE/weather | python3 -m json.tool

# Hue lights (needs bridge config)
curl -s -H "Authorization: Bearer $TOKEN" $BASE/hue/lights | python3 -m json.tool

# Gmail scan (needs OAuth)
curl -s -X POST -H "Authorization: Bearer $TOKEN" $BASE/connectors/gmail/scan

# Full re-index
curl -s -X POST -H "Authorization: Bearer $TOKEN" $BASE/connectors/force_index
```

---

## Future Services (Phases 13–15)

| Service | Phase | Purpose | `data/.env` key |
|---|---|---|---|
| Gemma 4 via Ollama | 13 | Better LLM, function calling | — (model switch in config) |
| MLX backend | 13 | Native Apple Silicon inference | — (optional) |
| Apple Health | 15 | Steps, sleep, heart rate in chat | — (local export, no key) |
| Spotify | 15 | Playback context | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` |
| MCP server | 15 | Home Assistant, Obsidian, etc. | `MCP_SERVER_URL` |
| RSS feeds | 15 | News without API key | — (configured in settings) |
