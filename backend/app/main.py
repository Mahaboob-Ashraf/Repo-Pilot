"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.routes import router


app = FastAPI(
    title="RepoPilot Backend",
    version="0.1.0",
    description="M0 local inference connectivity foundation",
)
app.include_router(router)

