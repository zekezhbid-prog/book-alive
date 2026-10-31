import io
import zipfile

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_engine
from app.models import Chapter, Entity, EntityFact, Image, Project, Scene, new_id, text_hash
from app.scenes import service
from tests.test_images import PNG

PARAGRAPHS = [
    "Рыхташ подошёл к мельнице на рассвете.",
    "Колесо скрипело, вода шумела под мостками.",
    "Внутри его ждала Люта в красном платке.",
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
        if schema is service.VideoAnswer:
            self.system, self.context = messages[0].content, messages[1].content
            return schema.model_validate(self.video)
        return schema.model_validate({"scenes": self.scenes})

    def invoke(self, operation, messages):
        self.system, self.context = messages[0].content, messages[1].content
        return " A woman hands over a silver key. "


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
    luta = Entity(project_id=project.id, kind="character", name="Люта", aliases=[])
    rykhtash = Entity(project_id=project.id, kind="character", name="Рыхташ", aliases=["Дед"])
    place = Entity(project_id=project.id, kind="location", name="Мельница", aliases=[])
    luta.facts = [
        EntityFact(chapter_id=early.id, chapter_hash="", category="permanent", text="рыжие волосы"),
        EntityFact(chapter_id=early.id, chapter_hash="", category="state", text="серый плащ"),
        EntityFact(chapter_id=mill.id, chapter_hash="", category="state", text="красный платок"),
    ]
    rykhtash.facts = [
        EntityFact(chapter_id=early.id, chapter_hash="", category="state", text="посох"),
    ]
    session.add_all([luta, rykhtash, place])
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
        picture(luta, is_main=True),
        picture(luta, look_label="в платке", chapter_from_id=mill.id, chapter_to_id=mill.id),
        picture(luta, look_label="в плаще", chapter_from_id=early.id, chapter_to_id=early.id),
        picture(rykhtash, is_main=True, style_key="anime"),  # another style: not offered
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
            {"from": 0, "to": 2, "title": "У мельницы", "vivid": False, "characters": ["Рыхташ"]},
            {
                "from": 2,
                "to": 3,
                "title": "Ключ",
                "vivid": True,
                "characters": ["Люта"],
                "location": "Мельница",
            },
        ]
    )
    scenes = service.split_chapter(session, model, book.mill)
    assert [(s.paragraph_from, s.paragraph_to, s.vivid) for s in scenes] == [
        (0, 2, False),
        (3, 4, True),
    ]
    names = lambda scene: {session.get(Entity, i).name for i in scene.entity_ids}
    # "Люта" is in the first scene by the text itself, though the model did not list her.
    assert names(scenes[0]) == {"Рыхташ", "Люта", "Мельница"}
    assert names(scenes[1]) == {"Люта", "Мельница"}

    # Splitting again replaces automatic scenes and keeps the ones marked by hand.
    manual = service.mark_scene(session, book.mill, 3, 3, "")
    assert manual.title == "Она молча протянула ему серебряный ключ."
    service.split_chapter(
        session, FakeModel([{"from": 0, "to": 4, "title": "Вся глава"}]), book.mill
    )
    kept = session.query(Scene).filter_by(chapter_id=book.mill.id).all()
    assert sorted((s.origin, s.title) for s in kept) == [
        ("auto", "Вся глава"),
        ("manual", "Она молча протянула ему серебряный ключ."),
    ]


def test_references_follow_the_chapter_and_the_current_style(session, book):
    scene = service.mark_scene(session, book.mill, 2, 3, "Ключ")
    refs = service.references(session, book, scene, book.mill)
    # Люта: main picture and the look for this chapter. Рыхташ's picture is in another style.
    assert [(r.number, r.entity.name, r.role, r.image.look_label) for r in refs] == [
        (1, "Люта", "main", ""),
        (2, "Люта", "look", "в платке"),
    ]


def test_video_prompt_gets_the_state_as_of_the_chapter(session, book):
    scene = service.mark_scene(session, book.mill, 0, 3, "Ключ")
    model = FakeModel()
    prompt, chosen = service.video_prompt(session, model, book, scene, "камера снизу")
    # Every base view and the look for this chapter are offered; the look of the prologue is not.
    assert "Character: Люта - reference 1 (base), reference 2 (look: в платке)" in model.context
    # The model took only the look: it becomes reference 1, in the prompt as well.
    assert prompt == "The figure from reference 1 hands over a key."
    look = session.query(Image).filter_by(project_id=book.id, look_label="в платке").one()
    assert chosen == [look.id]
    scene.reference_ids = chosen
    refs = service.references(session, book, scene, book.mill)
    assert [(r.number, r.role, r.image.look_label) for r in refs] == [(1, "look", "в платке")]
    assert "at this point: красный платок" in model.context
    assert "серый плащ" not in model.context  # an earlier chapter, replaced by this one
    # Рыхташ has no state facts in this chapter: the latest earlier ones are used.
    assert "Character: Рыхташ - no reference picture" in model.context
    assert "at this point: посох" in model.context
    assert "Author's note: камера снизу" in model.context
    assert "cinematic realism" in model.system


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
    assert saved["text"].startswith("Внутри его ждала Люта")
    assert [r["role"] for r in saved["references"]] == ["main", "look"]
    # The card's every picture can be paged through, not only those sent to the video.
    assert len(saved["participants"][0]["images"]) >= len(saved["references"])

    response = client.get(f"/api/scenes/{made['id']}/archive")
    assert response.headers["content-disposition"] == 'attachment; filename="test_klyuch.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert sorted(bundle.namelist()) == [
            "README.txt",
            "prompt.txt",
            "ref01_lyuta_main.png",
            "ref02_lyuta_v_platke.png",
        ]
        assert bundle.read("prompt.txt").decode() == "A key changes hands."
        assert (
            "ref02_lyuta_v_platke.png: reference 2 - Люта, look (в платке)"
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
    assert service.slug("Зіхцінка ў лесе") == "zikhtsinka_u_lese"
    assert service.slug("!!!") == "x"


def test_writer_can_describe_a_card_and_a_scene_in_words(client, book):
    luta = client.get(f"/api/projects/{book.id}/entities", params={"kind": "character"}).json()
    luta_id = next(c["id"] for c in luta if c["name"] == "Люта")
    assert client.get(f"/api/entities/{luta_id}").json()["description"] == ""
    saved = client.put(f"/api/entities/{luta_id}/description", json={"text": "  Рыжая и упрямая.  "})
    assert saved.status_code == 200
    assert saved.json()["description"] == "Рыжая и упрямая."
    assert client.get(f"/api/entities/{luta_id}").json()["description"] == "Рыжая и упрямая."
    assert client.put("/api/entities/nope/description", json={"text": "x"}).status_code == 404

    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 0, "paragraph_to": 0, "title": "Ключ"},
    ).json()
    scene = client.put(f"/api/scenes/{made['id']}/summary", json={"text": " Люта отдаёт ключ. "})
    assert scene.status_code == 200
    assert scene.json()["summary"] == "Люта отдаёт ключ."
    assert client.get(f"/api/scenes/{made['id']}").json()["summary"] == "Люта отдаёт ключ."
