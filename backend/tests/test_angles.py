from datetime import UTC, datetime, timedelta

from app.images import angles
from app.models import Image

START = datetime(2026, 10, 14, tzinfo=UTC)


def pictures(*specs: tuple[str, bool], style: str = "anime") -> list[Image]:
    """(angle, is_main) pairs, made one minute apart in this order."""
    return [
        Image(angle=angle, is_main=main, style_key=style, created_at=START + timedelta(minutes=n))
        for n, (angle, main) in enumerate(specs)
    ]


def test_next_angle_is_the_first_missing_view():
    assert angles.next_angle([], "anime") == "face_front"
    taken = pictures(("face_front", True), ("full_front", True), ("face_profile", False))
    # A picture that is not main does not fill a view.
    assert angles.next_angle(taken, "anime") == "face_profile"
    every = pictures(*((a, True) for a in angles.ANGLES), ("face_front", True))
    assert angles.next_angle(every, "anime") == "full_front"


def test_scene_gets_the_best_face_and_figure():
    side, untagged, profile, front = pictures(
        ("full_side", True), ("", True), ("face_profile", True), ("full_front", True)
    )
    assert angles.for_scene([side, untagged, profile, front], "anime") == [profile, front]
    # Without any view set, the earliest main pictures fill the places.
    first, second, _ = pictures(("", True), ("", True), ("", True))
    assert angles.for_scene([first, second, _], "anime") == [first, second]


def test_only_main_pictures_of_the_style_are_references():
    main, look = pictures(("full_front", True), ("", False))
    (other,) = pictures(("face_front", True), style="cinematic")
    assert angles.for_drawing([main, look, other], "anime") == [main]
    assert angles.for_scene([main, look, other], "anime") == [main]
