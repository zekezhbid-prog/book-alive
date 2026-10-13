from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import connections, projects
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Book Alive", lifespan=lifespan)
app.include_router(projects.router)
app.include_router(connections.router)

# In production the API also serves the built frontend; in development Vite does.
if settings.frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(settings.frontend_dist / "index.html")
