"""Unraid File Organizer — FastAPI application entry point."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router, scheduler
from app.version import VERSION
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("organizer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    task = asyncio.create_task(scheduler.run())
    writable = os.access(os.path.dirname(os.environ.get("ORGANIZER_CONFIG", "/config/config.json")), os.W_OK)
    logger.info(
        "Unraid File Organizer v%s starting | uid=%d | /config writable=%s",
        VERSION, os.geteuid(), writable,
    )
    yield
    task.cancel()


app = FastAPI(title="Unraid File Organizer", version=VERSION, lifespan=lifespan)


@app.get("/api/version")
async def version_info():
    import os
    config_dir = os.environ.get("ORGANIZER_CONFIG", "/config/config.json")
    parent = os.path.dirname(config_dir)
    return {
        "version": VERSION,
        "uid": os.geteuid(),
        "config_path": config_dir,
        "config_writable": os.access(parent, os.W_OK),
    }

app.include_router(api_router)

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = TEMPLATES_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse("<h1>Unraid File Organizer</h1><p>index.html missing</p>")


@app.get("/health")
async def health():
    return {"status": "ok"}
