"""Views of a character's main pictures. Together they pin down the face and build;
there may be any number of them, each with a view or none."""

from collections.abc import Iterable

from app.models import Image

# In order of usefulness: the first views are the ones scenes and new pictures lean on.
ANGLES = {
    "face_front": "Head-and-shoulders portrait, face turned straight to the camera, neutral "
    "expression, plain uncluttered background, even light.",
    "full_front": "Full-body view of the character alone, standing, facing the camera, neutral "
    "pose, plain uncluttered background, even light, face clearly visible.",
    "face_profile": "Head-and-shoulders portrait in strict side profile, neutral expression, "
    "plain uncluttered background, even light.",
    "full_side": "Full-body view of the character alone, standing in side profile, neutral "
    "pose, plain uncluttered background, even light.",
    "full_back": "Full-body view of the character alone, standing, seen from behind, neutral "
    "pose, plain uncluttered background, even light.",
}
FACES = ("face_front", "face_profile")
FIGURES = ("full_front", "full_side", "full_back")

# Image models take only a few pictures, and each one costs input tokens.
DRAWING_LIMIT = 3
SCENE_LIMIT = 2


def _rank(image: Image) -> tuple[int, object]:
    order = list(ANGLES)
    return (order.index(image.angle) if image.angle in ANGLES else len(order), image.created_at)


def mains(images: Iterable[Image], key: str) -> list[Image]:
    """The main pictures in the given style, most useful first."""
    return sorted((i for i in images if i.is_main and i.style_key == key), key=_rank)


def next_angle(images: Iterable[Image], key: str) -> str:
    """The view to draw when the user did not pick one: the first one still missing,
    or, with every view there, the one with the fewest pictures."""
    taken = [i.angle for i in mains(images, key)]
    return min(ANGLES, key=taken.count)


def for_drawing(images: Iterable[Image], key: str) -> list[Image]:
    """References for a new picture of the same character."""
    return mains(images, key)[:DRAWING_LIMIT]


def for_scene(images: Iterable[Image], key: str) -> list[Image]:
    """The best face and the best full-length view; other main pictures fill any gap."""
    ranked = mains(images, key)
    face = next((i for i in ranked if i.angle in FACES), None)
    figure = next((i for i in ranked if i.angle in FIGURES), None)
    picked = [i for i in (face, figure) if i is not None]
    picked += [i for i in ranked if i not in picked]
    return picked[:SCENE_LIMIT]
