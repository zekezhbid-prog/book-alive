"""Runs the analysis graph in a background thread and records how it ended."""

import threading
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.card import rebuild_card
from app.analysis.entities import GRAPH
from app.db import get_engine
from app.llm.calls import TextModel
from app.models import (
    RUN_CANCELLED,
    RUN_DONE,
    RUN_FAILED,
    RUN_RUNNING,
    AnalysisRun,
    Entity,
    Project,
    now,
)

# A model now and then answers with broken JSON or the service hiccups. Instead of stopping
# the whole run the same pass is simply started again: chapters already read are served from
# the database, so only the one that failed is asked once more.
MAX_RESTARTS = 4
RESTART_PAUSE = 5  # seconds, times the number of the restart


def execute(session: Session, run: AnalysisRun, model: TextModel) -> None:
    """Run to completion in the caller's thread. Chapters finished before a failure
    stay finished; starting again continues from there."""
    if run.entity_id:
        rebuild(session, run, model)
        return
    project = session.get(Project, run.project_id)
    forget_deleted_chapters(session, project, run.kind)
    if not run.done_chapter_ids and {c.id for c in project.chapters} <= set(run.chapter_ids):
        # A run over the whole book rebuilds the cards from scratch, so other names
        # collected by earlier runs must not carry over. Facts are rebuilt per chapter.
        for entity in session.scalars(
            select(Entity).where(Entity.project_id == project.id, Entity.kind == run.kind)
        ):
            entity.aliases = list(entity.pinned_names)  # what the user merged by hand stays
        session.commit()
    restarts = 0
    while True:
        pending = [cid for cid in run.chapter_ids if cid not in run.done_chapter_ids]
        try:
            GRAPH.invoke(
                {"run_id": run.id, "pending": pending},
                # Two steps per chapter plus the start, the final passes and some slack.
                {
                    "configurable": {"session": session, "model": model, "run_id": run.id},
                    "recursion_limit": 2 * len(pending) + 12,
                },
            )
        except Exception as exc:  # noqa: BLE001 - the run must always end in a recorded state
            session.rollback()
            session.refresh(run)
            restarts += 1
            if run.cancel_requested or restarts > MAX_RESTARTS:
                run.status = RUN_FAILED
                run.error = str(exc)[:500]
                break
            time.sleep(RESTART_PAUSE * restarts)
            continue
        session.refresh(run)
        run.status = RUN_CANCELLED if run.cancel_requested else RUN_DONE
        break
    run.finished_at = now()
    session.commit()


def rebuild(session: Session, run: AnalysisRun, model: TextModel) -> None:
    """One card across the book. Cheap enough to start over by hand if it fails."""
    try:
        rebuild_card(session, model, run)
        session.refresh(run)
        run.status = RUN_CANCELLED if run.cancel_requested else RUN_DONE
    except Exception as exc:  # noqa: BLE001 - the run must always end in a recorded state
        session.rollback()
        session.refresh(run)
        run.status = RUN_FAILED
        run.error = str(exc)[:500]
    run.finished_at = now()
    session.commit()


def forget_deleted_chapters(session: Session, project: Project, kind: str) -> None:
    """Facts read from chapters that no longer exist cannot be refreshed, only dropped."""
    alive = {c.id for c in project.chapters}
    for entity in session.scalars(
        select(Entity).where(Entity.project_id == project.id, Entity.kind == kind)
    ):
        for fact in [f for f in entity.facts if f.chapter_id not in alive]:
            entity.facts.remove(fact)
        if not entity.facts and not entity.standalone and not entity.images:
            session.delete(entity)
    session.commit()


def _work(run_id: str) -> None:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        run = session.get(AnalysisRun, run_id)
        try:
            model = TextModel(session, run.project_id, "analysis")
        except Exception as exc:  # noqa: BLE001 - same: report it on the run
            run.status = RUN_FAILED
            run.error = str(exc)[:500]
            run.finished_at = now()
            session.commit()
            return
        execute(session, run, model)


def start(run_id: str) -> None:
    threading.Thread(target=_work, args=(run_id,), daemon=True, name=f"analysis-{run_id}").start()


def active_run(session: Session, project_id: str) -> AnalysisRun | None:
    return session.scalars(
        select(AnalysisRun).where(
            AnalysisRun.project_id == project_id, AnalysisRun.status == RUN_RUNNING
        )
    ).first()


def mark_interrupted(session: Session) -> None:
    """Runs that were in flight when the server stopped cannot still be running."""
    session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.status == RUN_RUNNING)
        .values(status=RUN_FAILED, error="interrupted")
    )
    session.commit()
