"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router


LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


app = FastAPI(
    title="RepoPilot Backend",
    version="0.7.0",
    description="Local human-controlled repository repair workflow",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def bounded_request_validation_error(
    request: Request, error: RequestValidationError
):
    if request.url.path.startswith("/api/workflows"):
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "invalid_request",
                    "message": "Workflow request fields are invalid or incomplete.",
                }
            },
        )
    return await request_validation_exception_handler(request, error)
