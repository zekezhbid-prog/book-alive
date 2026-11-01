from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import auth, slowlog
from app.analysis import runner
from app.api import analysis, chat, connections, images, projects, review, scenes
from app.config import settings
from app.db import get_engine, init_db
from app.llm.provision import ensure_hubris


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(get_engine()) as session:
        runner.mark_interrupted(session)
        ensure_hubris(session)
    yield


app = FastAPI(
    title="Lorebook",
    lifespan=lifespan,
    # Under /api, so the login middleware covers the API description too.
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.middleware("http")(auth.require_login)
# Added last, so it runs first: the time it reports includes the login check.
app.middleware("http")(slowlog.log_slow_requests)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(connections.router)
app.include_router(analysis.router)
app.include_router(chat.router)
app.include_router(images.router)
app.include_router(scenes.router)
app.include_router(review.router)

# In production the API also serves the built frontend; in development Vite does.
if settings.frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        static = settings.frontend_dist / path
        if (
            path
            and static.is_file()
            and static.resolve().is_relative_to(settings.frontend_dist.resolve())
        ):
            return FileResponse(static)
        # Asset names carry a content hash; the page itself must be revalidated so a
        # rebuilt frontend reaches the browser without a hard reload.
        return FileResponse(
            settings.frontend_dist / "index.html", headers={"Cache-Control": "no-cache"}
        )
