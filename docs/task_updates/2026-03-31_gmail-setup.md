# Gmail & Calendar OAuth Setup Guide

This file documents how to configure OAuth2 for the Gmail and Calendar connectors.

---

## Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "Regis Local")
3. Enable the **Gmail API** and **Google Calendar API** under APIs & Services → Library

---

## Step 2 — Create OAuth Credentials

1. Go to APIs & Services → Credentials
2. Click "Create Credentials" → "OAuth 2.0 Client ID"
3. Application type: **Desktop app**
4. Name it anything (e.g. "Regis")
5. Download the JSON — save it as:
   ```
   /Users/matisselg/Sovereign V3/data/gmail_creds.json
   ```

---

## Step 3 — Configure OAuth Consent Screen

1. Go to APIs & Services → OAuth consent screen
2. User type: **External** (for personal use)
3. Add scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`
4. Add your Gmail address as a test user

---

## Step 4 — Run the OAuth Flow (one time only)

Run this from the project root to generate the token:

```bash
cd ~/Sovereign\ V3
source venv/bin/activate
python - <<'EOF'
from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file("data/gmail_creds.json", SCOPES)
creds = flow.run_local_server(port=0)
Path("data/gmail_token.json").write_text(creds.to_json())
print("Token saved to data/gmail_token.json")
EOF
```

This opens a browser window. Approve access. Token is saved at `data/gmail_token.json`.

---

## Step 5 — Verify

```bash
curl -X POST http://localhost:8765/connectors/gmail/scan
curl -X POST http://localhost:8765/connectors/calendar/scan
```

Both should return `"status": "OK"`.

---

## Notes

- Token auto-refreshes — you only need to run the flow once
- Both Gmail and Calendar share the same token (combined scopes)
- The token file is gitignored — never commit it
- If you revoke access, delete `data/gmail_token.json` and re-run Step 4
