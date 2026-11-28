import io
import zipfile

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_engine
from app.models import (
    Chapter,
    Entity,
    EntityFact,
    Image,
    Project,
    Scene,
    SceneSplit,
    new_id,
    text_hash,
)
from app.scenes import service
from tests.test_images import PNG

PARAGRAPHS = [
    "Ростан подошёл к мельнице на рассвете.",
    "Колесо скрипело, вода шумела под мостками.",
    "Внутри его ждала Лана в красном платке.",
    "Она молча протянула ему серебряный ключ.",
    "К вечеру они вышли на дорогу к замку.",
]
MILL = "\n\n".join(PARAGRAPHS)


class FakeModel:
    request_overhead = 0

    def __init__(self, scenes=None):
        self.scenes = scenes or []
        self.context = ""
        self.system = ""
        self.video = {
            "references": [2],
            "prompt": " The figure from reference 2 hands over a key. ",
        }

    def invoke_json(self, operation, messages, schema):
        if schema is service.EnrichAnswer:
            self.system, self.context = messages[0].content, messages[1].content
            return schema.model_validate(
                {
                    "text": "Лана ждёт у жернова. Мука пылит в луче света.",
                    "added": ["Мука пылит в луче света.", "Этого нет в тексте."],
                    "why": "Мельница в работе.",
                }
            )
        if schema is service.VideoAnswer:
            self.system, self.context = messages[0].content, messages[1].content
            return schema.model_validate(self.video)
        return schema.model_validate({"scenes": self.scenes})

    def invoke(self, operation, messages):
        self.system, self.context = messages[0].content, messages[1].content
        return " A woman hands over a silver key. "


def split(session, model, chapter):
    """Every proposal of a new split picked: the cards the old one-step split made."""
    proposals = service.propose_scenes(session, model, chapter).proposals
    return [service.scene_from_proposal(session, chapter, p) for p in proposals]


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db


@pytest.fixture
def book(session, tmp_path):
    project = Project(title="Тест", mode="reader", style_id="cinematic")
    early = Chapter(position=0, title="Пролог", text="Пролог.", content_hash=text_hash("Пролог."))
    mill = Chapter(position=1, title="Мельница", text=MILL, content_hash=text_hash(MILL))
    project.chapters += [early, mill]
    session.add(project)
    session.flush()
    lana = Entity(project_id=project.id, kind="character", name="Лана", aliases=[])
    rostan = Entity(project_id=project.id, kind="character", name="Ростан", aliases=["Дед"])
    place = Entity(project_id=project.id, kind="location", name="Мельница", aliases=[])
    lana.facts = [
        EntityFact(chapter_id=early.id, chapter_hash="", category="permanent", text="рыжие волосы"),
        EntityFact(chapter_id=early.id, chapter_hash="", category="state", text="серый плащ"),
        EntityFact(chapter_id=mill.id, chapter_hash="", category="state", text="красный платок"),
    ]
    rostan.facts = [
        EntityFact(chapter_id=early.id, chapter_hash="", category="state", text="посох"),
    ]
    session.add_all([lana, rostan, place])
    session.flush()

    def picture(entity, **fields):
        fields.setdefault("style_key", "cinematic")
        image = Image(
            project_id=project.id,
            entity_id=entity.id,
            origin="upload",
            path=f"{project.id}/images/{new_id()}.png",
            mime="image/png",
            **fields,
        )
        session.add(image)
        return image

    for image in (
        picture(lana, is_main=True),
        picture(lana, look_label="в платке", chapter_from_id=mill.id, chapter_to_id=mill.id),
        picture(lana, look_label="в плаще", chapter_from_id=early.id, chapter_to_id=early.id),
        picture(rostan, is_main=True, style_key="anime"),  # another style: not offered
    ):
        target = settings.files_dir / image.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG)
    session.commit()
    project.mill, project.early = mill, early
    return project


def test_model_boundaries_are_forced_to_tile_the_chapter(session, book):
    # The model overlaps, leaves a gap and stops early; the result must still cover 0..4.
    model = FakeModel(
        [
            {"from": 0, "to": 2, "title": "У мельницы", "vivid": False, "characters": ["Ростан"]},
            {
                "from": 2,
                "to": 3,
                "title": "Ключ",
                "vivid": True,
                "characters": ["Лана"],
                "location": "Мельница",
            },
        ]
    )
    scenes = split(session, model, book.mill)
    assert [(s.paragraph_from, s.paragraph_to, s.vivid) for s in scenes] == [
        (0, 2, False),
        (3, 4, True),
    ]
    names = lambda scene: {session.get(Entity, i).name for i in scene.entity_ids}
    # "Лана" is in the first scene by the text itself, though the model did not list her.
    assert names(scenes[0]) == {"Ростан", "Лана", "Мельница"}
    assert names(scenes[1]) == {"Лана", "Мельница"}

    # A new split only proposes: the cards made before and the ones marked by hand stay.
    manual = service.mark_scene(session, book.mill, 3, 3, "")
    assert manual.title == "Она молча протянула ему серебряный ключ."
    service.propose_scenes(
        session, FakeModel([{"from": 0, "to": 4, "title": "Вся глава"}]), book.mill
    )
    kept = session.query(Scene).filter_by(chapter_id=book.mill.id).all()
    assert len(kept) == 3
    assert session.get(SceneSplit, book.mill.id).proposals[0]["title"] == "Вся глава"


def test_names_in_a_title_line_are_not_the_scene_cast(session, book):
    # Owner's notes 25.11: a name came into a scene from the book title at the chapter's top.
    text = "ЛАНА И МЕЛЬНИЦА\n\nРостан шёл по дороге один."
    chapter = Chapter(project_id=book.id, position=2, title="", text=text, content_hash="x")
    session.add(chapter)
    session.commit()
    model = FakeModel([{"from": 0, "to": 1, "title": "Дорога", "characters": ["Лана", "Ростан"]}])
    [scene] = split(session, model, chapter)
    assert {session.get(Entity, i).name for i in scene.entity_ids} == {"Ростан"}
    assert service.is_heading("Пилигримы Цирона", "Пилигримы Цирона MAIN", "")
    assert not service.is_heading("Цирон!", "Пилигримы Цирона MAIN", "")
    assert not service.is_heading("Адбыўся цуд.", "Пилигримы Цирона MAIN", "")
    manual = service.mark_scene(session, chapter, 0, 1, "")
    assert {session.get(Entity, i).name for i in manual.entity_ids} == {"Ростан"}


def test_a_one_line_lead_in_is_not_a_scene_of_its_own(session, book):
    # Owner's notes 26.11: a tiny prologue came out as two cards about the same miracle.
    text = (
        "ПИЛИГРИМЫ ЦИРОНА\n\nАдбыўся цуд. Ніхто не бачыў.\n\n"
        "Ноччу на пустым скрыжаванні сярод цёмных сцежак з неба сарвалася зорка і "
        "ўпала на зямлю, і там, дзе была толькі цемра, заззяў цуд."
    )
    chapter = Chapter(project_id=book.id, position=2, title="", text=text, content_hash="y")
    session.add(chapter)
    session.commit()
    model = FakeModel(
        [
            {"from": 0, "to": 1, "title": "Цуд без сведкаў", "summary": "Уступ."},
            {"from": 2, "to": 2, "title": "Зорка на скрыжаванні", "summary": "Зорка падае."},
        ]
    )
    [scene] = split(session, model, chapter)
    assert (scene.paragraph_from, scene.paragraph_to) == (0, 2)
    assert scene.title == "Зорка на скрыжаванні"
    assert "Do not make a scene of a passage that only announces" in service.SPLIT_SYSTEM


def test_short_dialogue_lines_join_one_at_a_time_not_in_a_chain(session, book):
    # Review: a run of short lines must not melt into one scene; each lead-in joins once.
    long = "Ноччу на пустым скрыжаванні з неба сарвалася зорка і ўпала на зямлю ля млына."
    text = f"— Хто там?\n\n— Я.\n\n{long}\n\n— Ну?\n\n— Ды так.\n\n{long}\n\n— Бывай."
    chapter = Chapter(project_id=book.id, position=2, title="", text=text, content_hash="z")
    session.add(chapter)
    session.commit()
    model = FakeModel([{"from": i, "to": i, "title": f"S{i}"} for i in range(7)])
    scenes = split(session, model, chapter)
    assert [(s.paragraph_from, s.paragraph_to) for s in scenes] == [(0, 1), (2, 2), (3, 4), (5, 6)]


def test_enrich_suggests_and_marks_only_what_is_in_the_text(session, book):
    scene = service.mark_scene(session, book.mill, 2, 3, "Ключ")
    model = FakeModel()
    answer = service.enrich_scene(session, model, book, scene, book.mill)
    assert answer.added == ["Мука пылит в луче света."]
    # The paragraphs around the scene are given to the model; nothing is saved yet.
    assert "Колесо скрипело" in model.context and "К вечеру" in model.context
    assert session.get(Scene, scene.id).summary == ""
    assert "Author's wishes" not in model.context
    # Owner's notes 26.11: the author may say what to add; empty wishes change nothing.
    service.enrich_scene(session, model, book, scene, book.mill, "  больше про звуки  ")
    assert "Author's wishes: больше про звуки" in model.context
    assert "wishes" in model.system


def test_references_follow_the_chapter_and_the_current_style(session, book):
    scene = service.mark_scene(session, book.mill, 2, 3, "Ключ")
    refs = service.references(session, book, scene, book.mill)
    # Лана: main picture and the look for this chapter. Ростан's picture is in another style.
    assert [(r.number, r.entity.name, r.role, r.image.look_label) for r in refs] == [
        (1, "Лана", "main", ""),
        (2, "Лана", "look", "в платке"),
    ]


def test_video_prompt_gets_the_state_as_of_the_chapter(session, book):
    scene = service.mark_scene(session, book.mill, 0, 3, "Ключ")
    model = FakeModel()
    prompt, chosen = service.video_prompt(session, model, book, scene, "камера снизу")
    # Every base view and the look for this chapter are offered; the look of the prologue is not.
    assert "Character: Лана - reference 1 (base), reference 2 (look: в платке)" in model.context
    # The model took only the look: it becomes reference 1, in the prompt as well.
    assert prompt == "The figure from reference 1 hands over a key."
    look = session.query(Image).filter_by(project_id=book.id, look_label="в платке").one()
    assert chosen == [look.id]
    scene.reference_ids = chosen
    refs = service.references(session, book, scene, book.mill)
    assert [(r.number, r.role, r.image.look_label) for r in refs] == [(1, "look", "в платке")]
    assert "at this point: красный платок" in model.context
    assert "серый плащ" not in model.context  # an earlier chapter, replaced by this one
    # Ростан has no state facts in this chapter: the latest earlier ones are used.
    assert "Character: Ростан - no reference picture" in model.context
    assert "at this point: посох" in model.context
    assert "Author's note: камера снизу" in model.context
    assert "cinematic realism" in model.system


def test_video_prompt_follows_the_scene_text_not_the_book(session, book):
    # Owner's notes 28.11, item 51: the prompt (and the first frame made from it) comes
    # from the scene's own text; the book's text stays only for the spoken lines.
    scene = service.mark_scene(session, book.mill, 0, 3, "Ключ")
    model = FakeModel()
    service.video_prompt(session, model, book, scene, "")
    assert model.context.startswith("Scene text:\n")  # no scene text yet: the book's text
    scene.summary = "Девушка у мельницы молча отдаёт ключ."
    service.video_prompt(session, model, book, scene, "")
    first, _, rest = model.context.partition("\n\n")
    assert first.startswith("Scene text (film this") and scene.summary in first
    assert rest.startswith("The book's text of the scene")


def test_a_change_in_the_dialogue_may_take_a_picture_in_or_leave_one_out(session, book):
    # Owner's notes 27.11, scene dialogue: "we need ..." / "no reference for ..." in words.
    scene = service.mark_scene(session, book.mill, 0, 3, "Ключ")
    model = FakeModel()
    scene.prompt, scene.reference_ids = service.video_prompt(session, model, book, scene, "")
    look = session.query(Image).filter_by(project_id=book.id, look_label="в платке").one()
    assert (scene.prompt, scene.reference_ids) == (
        "The figure from reference 1 hands over a key.",
        [look.id],
    )
    # The model sees the pool's numbers: the look is 2 there, the base view 1.
    model.video = {"references": [1], "prompt": "The figure from reference 1 smiles."}
    prompt, chosen = service.refine_prompt(session, model, book, scene, "возьми общий вид Ланы")
    assert "Pictures the prompt uses now: 2" in model.context
    assert "Prompt:\nThe figure from reference 2 hands over a key." in model.context
    assert "Change wanted:\nвозьми общий вид Ланы" in model.context
    base = next(r for r in service.candidates(session, book, scene, book.mill) if r.number == 1)
    assert (prompt, chosen) == ("The figure from reference 1 smiles.", [base.image.id])
    assert "drop one" in model.system


def test_the_scene_dialogue_keeps_its_lines(client, session, book):
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 2, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    picture = session.query(Image).filter_by(project_id=book.id).first()
    lines = [
        {"role": "user", "text": "  Собрать промпт  "},
        {"role": "assistant", "kind": "prompt", "prompt": "A key."},
        {"role": "assistant", "kind": "frame", "image_id": picture.id},
        {"role": "assistant", "kind": "frame", "image_id": "gone"},
        {"role": "assistant", "kind": "enrich", "text": "Полнее.", "added": ["Полнее."]},
        # The first frame's prompt shown before drawing (owner's notes 28.11, item 46).
        {"role": "assistant", "kind": "frame_prompt", "prompt": "A still of a key."},
    ]
    scene = client.post(f"/api/scenes/{made['id']}/chat", json=lines).json()
    assert scene["chat"][5]["prompt"] == "A still of a key."
    assert [(m["kind"], m["text"]) for m in scene["chat"]][:2] == [
        ("text", "Собрать промпт"),
        ("prompt", ""),
    ]
    assert scene["chat"][2]["image_url"] == f"/api/images/{picture.id}/file"
    assert scene["chat"][3]["image_url"] == ""  # the picture was deleted: the line stays
    assert client.get(f"/api/scenes/{made['id']}").json()["chat"][4]["added"] == ["Полнее."]
    bad = client.post(f"/api/scenes/{made['id']}/frame", json={"size": "7:5"})
    assert bad.status_code == 422


def test_scene_api_prompt_edit_and_archive(client, session, book):
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 2, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    listed = client.get(f"/api/projects/{book.id}/scenes").json()
    assert [(s["title"], s["chapter_title"], s["stale"]) for s in listed] == [
        ("Ключ", "Мельница", False)
    ]
    assert client.get(f"/api/scenes/{made['id']}/archive").status_code == 409  # no prompt yet

    saved = client.put(
        f"/api/scenes/{made['id']}/prompt", json={"prompt": " A key changes hands. "}
    ).json()
    assert saved["prompt"] == "A key changes hands."
    assert saved["text"].startswith("Внутри его ждала Лана")
    assert [r["role"] for r in saved["references"]] == ["main", "look"]
    # The card's every picture can be paged through, not only those sent to the video.
    assert len(saved["participants"][0]["images"]) >= len(saved["references"])

    response = client.get(f"/api/scenes/{made['id']}/archive")
    assert response.headers["content-disposition"] == 'attachment; filename="test_klyuch.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert sorted(bundle.namelist()) == [
            "README.txt",
            "prompt.txt",
            "ref01_lana_main.png",
            "ref02_lana_v_platke.png",
        ]
        assert bundle.read("prompt.txt").decode() == "A key changes hands."
        assert (
            "ref02_lana_v_platke.png: reference 2 - Лана, look (в платке)"
            in bundle.read("README.txt").decode()
        )

    # The chapter text changes: the scene's paragraph numbers can no longer be trusted.
    book.mill.text += "\n\nНовый абзац."
    book.mill.content_hash = text_hash(book.mill.text)
    session.commit()
    assert client.get(f"/api/scenes/{made['id']}").json()["stale"] is True


def test_uploaded_frame_needs_no_prompt_and_goes_into_the_archive(client, book):
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 2, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    url = f"/api/scenes/{made['id']}/frame/upload"
    assert client.post(url, files={"file": ("x.txt", b"text")}).status_code == 422
    scene = client.post(url, files={"file": ("mine.png", PNG)}).json()
    assert [f["origin"] for f in scene["frames"]] == ["upload"]
    assert scene["frame_prompt"] == ""

    scene = client.put(
        f"/api/scenes/{made['id']}/prompt", json={"prompt": "A key changes hands."}
    ).json()
    assert scene["frame_prompt"].endswith(": A key changes hands.")
    response = client.get(f"/api/scenes/{made['id']}/archive")
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert "frame.png" in bundle.namelist()


def test_bad_range_and_missing_model(client, book):
    url = f"/api/chapters/{book.mill.id}/scenes"
    assert client.post(url, json={"paragraph_from": 3, "paragraph_to": 9}).status_code == 422
    estimate = client.get(f"{url}/estimate").json()
    assert estimate["input_tokens"] > 0 and estimate["existing"] == 0


def test_slug_transliterates_cyrillic_and_belarusian():
    assert service.slug("Зинка ў лесе") == "zinka_u_lese"
    assert service.slug("!!!") == "x"


def test_writer_can_describe_a_card_and_a_scene_in_words(client, book):
    lana = client.get(f"/api/projects/{book.id}/entities", params={"kind": "character"}).json()
    lana_id = next(c["id"] for c in lana if c["name"] == "Лана")
    assert client.get(f"/api/entities/{lana_id}").json()["description"] == ""
    saved = client.put(
        f"/api/entities/{lana_id}/description", json={"text": "  Рыжая и упрямая.  "}
    )
    assert saved.status_code == 200
    assert saved.json()["description"] == "Рыжая и упрямая."
    assert client.get(f"/api/entities/{lana_id}").json()["description"] == "Рыжая и упрямая."
    assert client.put("/api/entities/nope/description", json={"text": "x"}).status_code == 404

    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 0, "paragraph_to": 0, "title": "Ключ"},
    ).json()
    scene = client.put(f"/api/scenes/{made['id']}/summary", json={"text": " Лана отдаёт ключ. "})
    assert scene.status_code == 200
    assert scene.json()["summary"] == "Лана отдаёт ключ."
    assert client.get(f"/api/scenes/{made['id']}").json()["summary"] == "Лана отдаёт ключ."


def test_a_scene_names_the_references_it_still_lacks(client, session, book):
    # Owner's notes 26.11: Лана's main picture has no view, Ростан's is in another style, the
    # mill has none: each lack is named, so the user can draw it from the scene.
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 0, "paragraph_to": 3, "title": "Мельница"},
    ).json()
    made = client.get(f"/api/scenes/{made['id']}").json()
    names = {p["name"] for p in made["participants"]}
    lacks = {(m["name"], m["need"]) for m in made["missing"]}
    if "Мельница" in names:
        assert ("Мельница", "base") in lacks
    assert {("Лана", "face"), ("Лана", "figure")} <= lacks
    lana = next(p for p in made["participants"] if p["name"] == "Лана")
    main = next(i for i in lana["images"] if i["is_main"])
    client.patch(f"/api/images/{main['id']}", json={"angle": "face_front"})
    again = client.get(f"/api/scenes/{made['id']}").json()
    lacks = {(m["name"], m["need"]) for m in again["missing"]}
    assert ("Лана", "face") not in lacks and ("Лана", "figure") in lacks


def test_the_user_picks_the_scene_references_by_hand(client, book):
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 2, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    made = client.get(f"/api/scenes/{made['id']}").json()
    main, look = [r["image_id"] for r in made["references"]]
    # The look of the prologue does not cover this chapter: the scene may not use it.
    prologue = next(
        i["id"] for p in made["participants"] for i in p["images"] if i["look_label"] == "в плаще"
    )
    url = f"/api/scenes/{made['id']}/references"
    chosen = client.put(url, json={"image_ids": [look, prologue]}).json()
    assert [r["image_id"] for r in chosen["references"]] == [look]
    # An empty choice goes back to the fixed rules.
    back = client.put(url, json={"image_ids": []}).json()
    assert [r["image_id"] for r in back["references"]] == [main, look]


def test_a_chapter_is_split_once_and_a_card_is_made_from_the_scene_picked(
    client, session, book, monkeypatch
):
    # Owner's notes 27.11 (14, 25): the split is kept and shown again without the model; a
    # card is made only for the proposal the user picks; a new split needs `again`.
    model = FakeModel(
        [{"from": 0, "to": 1, "title": "Мельница"}, {"from": 2, "to": 4, "title": "Ключ"}]
    )
    calls = []
    monkeypatch.setattr("app.api.scenes._text_model", lambda *a: calls.append(1) or model)
    url = f"/api/chapters/{book.mill.id}/scenes"
    assert client.get(f"{url}/proposals").json() == {
        "chapter_id": book.mill.id,
        "exists": False,
        "stale": False,
        "items": [],
    }
    assert client.get(f"{url}/estimate").json()["existing"] == 0

    made = client.post(f"{url}/split").json()
    assert made["exists"] and not made["stale"]
    assert [(p["title"], p["scene_id"]) for p in made["items"]] == [("Мельница", ""), ("Ключ", "")]
    assert client.get(f"/api/projects/{book.id}/scenes").json() == []  # no card yet
    assert client.get(f"{url}/estimate").json()["existing"] == 2

    card = client.post(f"{url}/proposals/1").json()
    assert (card["title"], card["paragraph_from"], card["paragraph_to"]) == ("Ключ", 2, 4)
    assert client.post(f"{url}/proposals/1").json()["id"] == card["id"]  # not made twice
    assert client.post(f"{url}/proposals/5").status_code == 404

    shown = client.post(f"{url}/split").json()
    assert len(calls) == 1  # the kept split, no second call
    assert [p["scene_id"] for p in shown["items"]] == ["", card["id"]]

    model.scenes = [{"from": 0, "to": 4, "title": "Вся глава"}]
    remade = client.post(f"{url}/split", params={"again": True}).json()
    assert len(calls) == 2 and [p["title"] for p in remade["items"]] == ["Вся глава"]
    listed = client.get(f"/api/projects/{book.id}/scenes").json()
    assert [s["id"] for s in listed] == [card["id"]]  # the card made before stays

    # The text changed since: the kept split is stale and no card is made from it.
    session.get(Chapter, book.mill.id).content_hash = "changed"
    session.commit()
    assert client.get(f"{url}/proposals").json()["stale"]
    assert client.post(f"{url}/proposals/0").json()["detail"] == "proposals_stale"


def test_first_frame_prompt_is_changed_in_words(client, book, monkeypatch):
    # Owner's notes 28.11, item 47: words typed under the shown frame prompt change it.
    from app.api import scenes as scenes_api

    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 2, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    seen = []
    monkeypatch.setattr(scenes_api, "_text_model", lambda *a: "model")
    monkeypatch.setattr(
        scenes_api,
        "refine_image_prompt",
        lambda model, prompt, change: seen.append((model, prompt, change)) or "A still, at dusk.",
    )
    answer = client.post(
        f"/api/scenes/{made['id']}/frame-prompt/refine",
        json={"prompt": "A still.", "change": "вечером"},
    )
    assert answer.json() == {"text": "A still, at dusk."}
    assert seen == [("model", "A still.", "вечером")]


# ---------- sub-scenes (owner's notes 28.11, items 67, 68) ----------

BREAKDOWN = {
    "subscenes": [
        {
            "from": 0,
            "to": 1,
            "heading": "У мельницы — рассвет",
            "past": False,
            "cast": ["Ростан"],
            "action": "Ростан подходит к мельнице. Колесо скрипит.",
            "lines": [],
            "goal": "Дойти до мельницы.",
        },
        {
            "from": 2,
            "to": 9,  # past the scene: clamped
            "heading": "Внутри мельницы",
            "past": False,
            "cast": ["Лана"],
            "action": "Лана молча протягивает ключ.",
            "lines": [
                {"who": "Лана", "how": "тихо", "text": "серебряный ключ", "voice": False},
                {"who": "Лана", "how": "", "text": "Этого нет в книге", "voice": False},
                {"who": "Лана", "how": "", "text": "ждала Лана … красном платке", "voice": True},
            ],
            "goal": "",
        },
    ]
}


class BreakdownModel(FakeModel):
    def __init__(self, answer=BREAKDOWN):
        super().__init__()
        self.answer = answer

    def invoke_json(self, operation, messages, schema):
        if schema is service.Breakdown:
            self.system, self.context = messages[0].content, messages[1].content
            return schema.model_validate(self.answer)
        return super().invoke_json(operation, messages, schema)


def _scene(session, book, start=0, end=3):
    return service.mark_scene(session, book.mill, start, end, "Ключ")


def test_breakdown_makes_sub_scenes_with_the_book_s_own_lines(session, book):
    scene = _scene(session, book)
    model = BreakdownModel()
    service.break_down(session, model, book, scene, book.mill)
    subs = scene.subscenes
    assert [(s["from"], s["to"]) for s in subs] == [(0, 1), (2, 3)]
    # Only lines whose words stand in the scene text are kept; "…" joins two pieces of it.
    assert [line["text"] for line in subs[1]["lines"]] == [
        "серебряный ключ",
        "ждала Лана … красном платке",
    ]
    assert subs[0]["entity_ids"] and subs[0]["entity_ids"] != subs[1]["entity_ids"]
    # The scene's text is made of the blocks: the video prompt and the export read it.
    assert "1. У мельницы — рассвет" in scene.summary
    assert "Лана молча протягивает ключ." in scene.summary
    assert "Этого нет в книге" not in scene.summary
    # The model sees the numbered paragraphs of the scene and what is around it.
    assert "[3] Она молча протянула ему серебряный ключ." in model.context
    assert "К вечеру" in model.context  # the paragraph after, for context


def test_a_breakdown_with_nothing_usable_keeps_the_scene_whole(session, book):
    scene = _scene(session, book)
    service.break_down(session, BreakdownModel({"subscenes": []}), book, scene, book.mill)
    assert len(scene.subscenes) == 1
    assert (scene.subscenes[0]["from"], scene.subscenes[0]["to"]) == (0, 3)


def test_a_private_chapter_is_not_broken_down(client, session, book):
    book.mill.private = True
    session.commit()
    scene = _scene(session, book)
    assert client.post(f"/api/scenes/{scene.id}/rebuild").status_code == 403


def test_rebuild_and_edit_a_sub_scene(client, session, book, monkeypatch):
    monkeypatch.setattr("app.api.scenes.TextModel", lambda *a: BreakdownModel())
    scene = _scene(session, book)
    out = client.post(f"/api/scenes/{scene.id}/rebuild").json()
    assert [s["heading"] for s in out["subscenes"]] == ["У мельницы — рассвет", "Внутри мельницы"]
    assert out["subscenes"][1]["cast"] == ["Лана"]
    edited = client.put(
        f"/api/scenes/{scene.id}/subscenes/1", json={"action": "Лана кладёт ключ на стол."}
    ).json()
    assert edited["subscenes"][1]["action"] == "Лана кладёт ключ на стол."
    assert "Лана кладёт ключ на стол." in edited["summary"]
    assert (
        client.put(f"/api/scenes/{scene.id}/subscenes/5", json={"action": "x"}).status_code == 404
    )


def test_a_scene_picked_from_the_proposals_is_broken_down_at_once(
    client, session, book, monkeypatch
):
    monkeypatch.setattr("app.api.scenes.TextModel", lambda *a: BreakdownModel())
    session.add(
        SceneSplit(
            chapter_id=book.mill.id,
            project_id=book.id,
            chapter_hash=book.mill.content_hash,
            proposals=[
                {
                    "from": 0,
                    "to": 3,
                    "title": "Ключ",
                    "summary": "Кратко.",
                    "vivid": False,
                    "entity_ids": [],
                }
            ],
        )
    )
    session.commit()
    brief = client.post(f"/api/chapters/{book.mill.id}/scenes/proposals/0").json()
    scene = client.get(f"/api/scenes/{brief['id']}").json()
    assert len(scene["subscenes"]) == 2
    # Picked again: the same card, not broken down anew over the author's changes.
    client.put(f"/api/scenes/{brief['id']}/subscenes/0", json={"action": "Своё."})
    client.post(f"/api/chapters/{book.mill.id}/scenes/proposals/0")
    assert client.get(f"/api/scenes/{brief['id']}").json()["subscenes"][0]["action"] == "Своё."


def test_enrich_of_one_sub_scene_reads_only_its_paragraphs(session, book):
    scene = _scene(session, book)
    service.break_down(session, BreakdownModel(), book, scene, book.mill)
    model = FakeModel()
    service.enrich_scene(session, model, book, scene, book.mill, "", sub=0)
    assert "Ростан подходит к мельнице." in model.context
    scene_part = model.context.split("Scene text:")[1].split("Before the scene:")[0]
    assert "серебряный ключ" not in scene_part
