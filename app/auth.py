"""
API token authentication — Phase 6.5 SEC-01.

Token is generated on first run and stored at data/.api_token (chmod 600).
All endpoints except /health and /dashboard require:
    Authorization: Bearer <token>

The dashboard HTML is served by FastAPI with the token embedded server-side
(replace __REGIS_TOKEN__ placeholder), so PyWebView calls work automatically.
"""

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException

TOKEN_PATH = Path(__file__).parent.parent / "data" / ".api_token"


def _load_or_create_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    os.chmod(TOKEN_PATH, 0o600)  # owner read-only
    return token


API_TOKEN: str = _load_or_create_token()


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — raises 401 if Bearer token is missing or wrong."""
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
