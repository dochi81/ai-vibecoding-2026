"""FastAPI entry point for the automated trading trader."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.database.db import create_database_tables


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare local persistence before accepting HTTP requests."""
    create_database_tables()
    yield


app = FastAPI(
    title="AUTO TRADING v0.1",
    description="Toss Securities Open API based paper-trading service.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
