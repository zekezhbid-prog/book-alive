"""Which connection and model a person uses: their own choice, else the shared default.

The shared default is what the administrator set (and what the Hubris key creates at
startup); a person's own choice is stored per account under `u:<user id>:<name>`."""

from sqlalchemy.orm import Session

from app.models import AppSetting, Project

# Text work falls into a few tasks that may each use their own model; an empty choice for a
# task means the main text model.
TEXT_TASKS = ("analysis", "chat", "prompts")

NAMES = (
    "text_connection_id",
    "text_model",
    *(f"text_{task}_{part}" for task in TEXT_TASKS for part in ("connection_id", "model")),
    "image_connection_id",
    "image_model",
    "video_connection_id",
    "video_model",
)


def personal_key(user_id: str, name: str) -> str:
    return f"u:{user_id}:{name}"


def value(session: Session, user_id: str | None, name: str) -> str | None:
    """The setting for this account, or the shared one; None when neither exists."""
    if user_id:
        own = session.get(AppSetting, personal_key(user_id, name))
        if own is not None:
            return own.value
    shared = session.get(AppSetting, name)
    return shared.value if shared is not None else None


def for_project(session: Session, project_id: str | None, name: str) -> str | None:
    """The setting of whoever owns the project (the shared one for an unowned book)."""
    project = session.get(Project, project_id) if project_id else None
    return value(session, project.owner_id if project else None, name)
