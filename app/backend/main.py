"""FastAPI application entry point for Airport Digital Twin."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.backend.api.routes import router
from app.backend.api.websocket import websocket_router
from app.backend.api.predictions import prediction_router

# Resolve frontend dist path
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

app = FastAPI(
    title="Airport Digital Twin API",
    description="Real-time flight data API for the Airport Digital Twin visualization",
    version="0.1.0",
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)
app.include_router(websocket_router)
app.include_router(prediction_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Serve static frontend files (must be after API routes)
if FRONTEND_DIST.exists():
    # Serve static assets (JS, CSS, etc.)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    # Catch-all route for SPA - serves index.html for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the SPA for all non-API routes."""
        # Skip API paths
        if full_path.startswith("api/") or full_path.startswith("ws"):
            return {"error": "Not found"}

        index_file = FRONTEND_DIST / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"error": "Frontend not built"}
