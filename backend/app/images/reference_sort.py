"""The user's own pictures of a character, looked at before a set of base pictures is drawn
from them: whether they show one person, which view each one is, and which can stand in a
view's slot as they are. The rest only guide the drawing."""

import base64

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.images import angles
from app.llm.calls import TextModel

VIEWS = ", ".join(angles.ANGLES)

SYSTEM = f"""You look at reference pictures a user gave for one character of an illustrated
book, numbered from 1, before a set of base pictures (a character sheet) is drawn from them.

1. Decide whether all pictures show the same person (or creature). Clothes, age by a few
years, light and drawing style may differ; the face and build must not. If not, list the
numbers of the pictures that show someone else than most of them (or than picture 1 when
there is no majority) in "others".
2. For each picture give "view", one of: {VIEWS}, or "" when it fits none. face_* is a
head-and-shoulders portrait; full_* shows the whole body; front is facing the camera,
three_quarter is turned partly away, profile/side is strict side view, back is from behind.
3. "clean": true only if the picture shows this one character alone, in that view, on a plain
or quiet background, with nothing covering the face or body, so it could serve as that base
picture.
4. "style_ok": true only if the drawing style matches the book's style given below (medium,
rendering, palette); a photo never matches a drawn style. With no style given, true.

Reply with only a JSON object:
{{"same_person": true or false, "others": [numbers], "reason": "one short sentence in Russian,
only when same_person is false: who differs and how",
"pictures": [{{"n": 1, "view": "...", "clean": true or false, "style_ok": true or false}}]}}"""


class PictureVerdict(BaseModel):
    n: int
    view: str = ""
    clean: bool = False
    style_ok: bool = False


class SortVerdict(BaseModel):
    same_person: bool = True
    others: list[int] = Field(default_factory=list)
    reason: str = ""
    pictures: list[PictureVerdict] = Field(default_factory=list)


class Placement(BaseModel):
    """Index into the pictures sent (from 0) and the view's slot it goes into as it is."""

    index: int
    angle: str


class SortResult(BaseModel):
    same_person: bool
    # Indexes (from 0) of the pictures showing someone else.
    others: list[int]
    reason: str
    # Pictures that go into empty slots as they are; every other one guides the drawing.
    placed: list[Placement]
    # The view of each picture as the model saw it, "" when none.
    views: list[str]


def ask_model(
    model: TextModel, style: str, pictures: list[tuple[bytes, str]], character: str
) -> SortVerdict:
    content: list[str | dict] = [
        {"type": "text", "text": f"The character: {character}\nThe book's style: {style or '-'}"}
    ]
    for n, (data, mime) in enumerate(pictures, start=1):
        encoded = base64.b64encode(data).decode()
        content.append({"type": "text", "text": f"Picture {n}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    messages = [SystemMessage(SYSTEM), HumanMessage(content=content)]
    return model.invoke_json("reference_sort", messages, SortVerdict)


def decide(verdict: SortVerdict, count: int, taken: set[str]) -> SortResult:
    """Turn the model's verdict into what happens. A picture goes into a slot only when it is
    clean, already in the book's style (a picture in another style is redrawn, never put in:
    the whole set stays in one style) and its view is still empty; one picture per view."""
    by_n = {p.n: p for p in verdict.pictures if 1 <= p.n <= count}
    views = [
        by_n[n].view if n in by_n and by_n[n].view in angles.ANGLES else ""
        for n in range(1, count + 1)
    ]
    others = sorted({n - 1 for n in verdict.others if 1 <= n <= count})
    if not verdict.same_person and not others:
        # The model said "different people" but named no one: nothing can be suggested,
        # so the user is asked to look at all of them.
        others = list(range(count))
    if not verdict.same_person:
        return SortResult(
            same_person=False, others=others, reason=verdict.reason, placed=[], views=views
        )
    placed: list[Placement] = []
    filled = set(taken)
    for index, view in enumerate(views):
        picture = by_n.get(index + 1)
        if view and view not in filled and picture and picture.clean and picture.style_ok:
            placed.append(Placement(index=index, angle=view))
            filled.add(view)
    return SortResult(same_person=True, others=[], reason="", placed=placed, views=views)
