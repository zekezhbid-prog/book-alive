"""One visual style per project, so every picture looks like it is from the same film."""

import hashlib

from app.models import Project

# id -> the English fragment that goes into every image and video prompt.
PRESETS: dict[str, str] = {
    "cinematic": "cinematic realism, film still, natural light, shallow depth of field, "
    "detailed textures, muted colour grading",
    "dark_fantasy": "dark fantasy, moody painterly realism, dramatic chiaroscuro lighting, "
    "desaturated palette with deep shadows, intricate detail",
    "anime": "anime style, clean line art, cel shading, expressive faces, vivid colours",
    "illustration": "classic book illustration, ink and watercolour, soft washes, "
    "visible paper texture, storybook composition",
}
CUSTOM = "custom"


def style_prompt(project: Project) -> str:
    if project.style_id == CUSTOM:
        return project.style_text.strip()
    return PRESETS.get(project.style_id, "")


def style_key(project: Project) -> str:
    """Label stored on every picture. Pictures are offered as references only while
    their label equals the project's current one."""
    if not project.style_id:
        return ""
    if project.style_id == CUSTOM:
        digest = hashlib.sha256(project.style_text.strip().encode()).hexdigest()[:8]
        return f"{CUSTOM}:{digest}"
    return project.style_id
