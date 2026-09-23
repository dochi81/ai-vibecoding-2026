"""FastAPI entry point for the automated trading trader."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import PROJECT_DIR
from app.database.db import create_database_tables


class NoCacheStaticFiles(StaticFiles):
    """Serve the local dashboard assets without stale browser caching."""

    async def get_response(self, path: str, scope: object):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare local persistence before accepting HTTP requests."""
    create_database_tables()
    yield


app = FastAPI(
    title="TOSS AUTO TRADER v0.1",
    description="Toss Securities Open API based paper-trading service.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
app.mount("/static", NoCacheStaticFiles(directory=PROJECT_DIR / "app" / "static"), name="static")


@app.get("/", include_in_schema=False)
def quote_home() -> FileResponse:
    """Serve the quote-first home screen."""
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "market.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    """Serve the paper-trading dashboard."""
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/market", include_in_schema=False)
def market_screen() -> FileResponse:
    """Serve the read-only Toss Securities quote screen."""
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "market.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/auto-buy", include_in_schema=False)
def auto_buy_screen() -> FileResponse:
    """Serve the paper-only automatic-buy control screen."""
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "auto-buy.html",
        headers={"Cache-Control": "no-store"},
    )
