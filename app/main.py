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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("organizer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler.run())
    logger.info("Background scheduler task started")
    yield
    task.cancel()


app = FastAPI(title="Unraid File Organizer", version="1.4.0", lifespan=lifespan)

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
