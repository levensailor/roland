"""FastAPI entrypoint for the Roland TM-2 sample loader."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.logging_setup import configure_logging
from app.models import HealthResponse, RouteInfo
from app.routers import card, samples, volumes
from app.services.converter import ffmpeg_available

settings = get_settings()
logger = configure_logging(settings)

app = FastAPI(
    title=settings.app_name,
    description="Convert audio and write Roland TM-2 WAVE folders on a mounted SD card.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def reject_oversize_uploads(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > settings.max_upload_bytes:
            logger.info("Rejected oversize upload: %s bytes", content_length)
            return JSONResponse(
                status_code=413,
                content={"detail": f"Upload exceeds {settings.max_upload_mb} MB."},
            )
    return await call_next(request)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    available = ffmpeg_available(settings)
    logger.info("Health check ffmpeg_available=%s", available)
    return HealthResponse(
        app_name=settings.app_name,
        author=settings.app_author,
        ffmpeg_available=available,
        ffmpeg_binary=settings.ffmpeg_binary,
    )


app.include_router(volumes.get_router(logger))
app.include_router(card.get_router(logger))
app.include_router(samples.get_router(logger))


@app.get("/api/routes", response_model=list[RouteInfo])
def list_routes() -> list[RouteInfo]:
    routes: list[RouteInfo] = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", []) or [])
        path = getattr(route, "path", "")
        name = getattr(route, "name", "")
        if not path.startswith("/api"):
            continue
        for method in methods:
            if method == "HEAD":
                continue
            routes.append(RouteInfo(method=method, path=path, name=name))
    return sorted(routes, key=lambda item: (item.path, item.method))

if settings.frontend_dir.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(settings.frontend_dir), html=True),
        name="frontend",
    )
    logger.info("Serving frontend from %s", settings.frontend_dir)
else:
    logger.info("Frontend directory missing at %s", settings.frontend_dir)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
