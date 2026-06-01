"""OAuth2 mock for FLIFO authentication."""

import hashlib
import time
from typing import Optional

from fastapi import Header, HTTPException

VALID_CREDENTIALS = {
    "test": "test",
    "flifo_client": "flifo_secret",
    "sita_demo": "demo_secret",
}

_active_tokens: dict[str, float] = {}

TOKEN_EXPIRY_SECONDS = 3600


def issue_token(client_id: str, client_secret: str) -> Optional[str]:
    """Issue a bearer token if credentials valid."""
    expected_secret = VALID_CREDENTIALS.get(client_id)
    if expected_secret is None or expected_secret != client_secret:
        return None

    raw = f"{client_id}:{time.time()}"
    token = hashlib.sha256(raw.encode()).hexdigest()[:48]
    _active_tokens[token] = time.time() + TOKEN_EXPIRY_SECONDS
    return token


def validate_token(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency that validates Bearer token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization format. Use: Bearer <token>")

    token = parts[1]

    expiry = _active_tokens.get(token)
    if expiry is None:
        raise HTTPException(status_code=401, detail="Invalid or unknown token")

    if time.time() > expiry:
        del _active_tokens[token]
        raise HTTPException(status_code=401, detail="Token expired")

    return token
