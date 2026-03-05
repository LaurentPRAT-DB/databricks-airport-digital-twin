"""FastAPI application entry point for Airport Digital Twin."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.api.routes import router
from app.backend.api.websocket import websocket_router
from app.backend.api.predictions import prediction_router


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
