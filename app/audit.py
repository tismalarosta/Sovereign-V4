"""
Audit logger — Phase 6.5 SEC-05.

Every HTTP request is logged as a JSONL line to data/audit.log.
Format: {"ts": ISO, "method": "GET", "path": "/snapshot", "status": 200, "ip": "127.0.0.1"}

Never logs request bodies, Authorization headers, or credentials.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

AUDIT_LOG = Path(__file__).parent.parent / "data" / "audit.log"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start = datetime.now(timezone.utc)
        response = await call_next(request)
        entry = {
            "ts":     start.isoformat(),
            "method": request.method,
            "path":   request.url.path,
            "status": response.status_code,
            "ip":     request.client.host if request.client else "unknown",
        }
        try:
            with open(AUDIT_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass   # never crash the request just because audit log failed
        return response
