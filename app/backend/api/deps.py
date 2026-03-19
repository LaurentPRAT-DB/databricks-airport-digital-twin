"""FastAPI dependencies for the Airport Digital Twin API."""

from fastapi import Request


def get_current_user(request: Request) -> str:
    """Extract user email from Databricks App proxy headers.

    Databricks Apps inject X-Forwarded-Email and X-Forwarded-User
    headers via their reverse proxy.
    """
    email = request.headers.get("X-Forwarded-Email")
    if email:
        return email
    user = request.headers.get("X-Forwarded-User")
    if user:
        return user
    return "anonymous"
