import base64
import json

import httpx
import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.images.generate import ImageGenerationFailed, ImageModel
from app.images.prompts import build_image_prompt, chapters_between
from app.images.reference_sort import PictureVerdict, SortVerdict, decide
from app.images.style_check import StyleVerdict
from app.models import AppSetting, Chapter, Connection, Entity, EntityFact, Project, text_hash

# The smallest valid PNG: one transparent pixel.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def session(client):
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db


@pytest.fixture
def project(session):
    book = Project(title="Тест", mode="reader")
    for position, title in enumerate(["Мельница", "Дорога", "Замок"]):
        book.chapters.append(
            Chapter(position=position, title=title, text=title, content_hash=text_hash(title))
        )
    session.add(book)
    session.flush()
    hero = Entity(project_id=book.id, kind="character", name="Люта", aliases=[])
    first, _, third = book.chapters
    hero.facts = [
        EntityFact(chapter_id=first.id, chapter_hash="", category="permanent", text="рыжие волосы"),
        EntityFact(chapter_id=first.id, chapter_hash="", category="state", text="красный платок"),
        EntityFact(chapter_id=third.id, chapter_hash="", category="state", text="кольчуга"),
    ]
    session.add(hero)
    session.commit()
    book.hero_id = hero.id
    return book


def upload(client, project, entity_id="", count=1):
    files = [("files", (f"ref{n}.png", PNG, "image/png")) for n in range(count)]
    response = client.post(
        f"/api/projects/{project.id}/images", files=files, data={"entity_id": entity_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_style_labels_decide_which_pictures_are_current(client, project):
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    first = upload(client, project, project.hero_id)[0]
    assert (first["style_key"], first["current_style"], first["is_main"]) == ("anime", True, True)

    # A new style: the old picture stays, but is no longer a reference for the current one.
    client.put(
        f"/api/projects/{project.id}/style",
        json={"style_id": "custom", "style_text": "grainy 16mm film"},
    )
    listed = client.get(
        f"/api/projects/{project.id}/images", params={"entity_id": project.hero_id}
    ).json()
    assert [(i["id"], i["current_style"]) for i in listed] == [(first["id"], False)]
    second = upload(client, project, project.hero_id)[0]
    assert second["style_key"].startswith("custom:")
    assert second["is_main"] is True  # the first picture in the new style leads it


def test_a_card_keeps_several_main_pictures_with_views(client, project):
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    first, second = upload(client, project, project.hero_id, count=2)
    assert (first["is_main"], second["is_main"]) == (True, False)
    changed = client.patch(
        f"/api/images/{second['id']}", json={"is_main": True, "angle": "face_profile"}
    ).json()
    assert (changed["is_main"], changed["angle"]) == (True, "face_profile")
    listed = client.get(
        f"/api/projects/{project.id}/images", params={"entity_id": project.hero_id}
    ).json()
    assert {i["id"]: i["is_main"] for i in listed} == {first["id"]: True, second["id"]: True}

    bad = client.patch(f"/api/images/{first['id']}", json={"angle": "upside_down"})
    assert (bad.status_code, bad.json()["detail"]) == (422, "bad_angle")
    unmarked = client.patch(f"/api/images/{first['id']}", json={"is_main": False}).json()
    assert unmarked["is_main"] is False


def test_project_level_references_and_file_serving(client, project):
    general = upload(client, project)[0]
    assert general["entity_id"] is None
    assert client.get(f"/api/projects/{project.id}/images").json()[0]["id"] == general["id"]
    served = client.get(general["url"])
    assert (served.status_code, served.headers["content-type"], served.content) == (
        200,
        "image/png",
        PNG,
    )
    assert client.delete(f"/api/images/{general['id']}").status_code == 204
    assert client.get(general["url"]).status_code == 404


def test_upload_must_be_a_picture(client, project):
    response = client.post(
        f"/api/projects/{project.id}/images",
        files=[("files", ("notes.png", b"just text", "image/png"))],
    )
    assert (response.status_code, response.json()["detail"]) == (422, "not_an_image")


def test_card_made_by_hand_is_reused_by_name(client, project):
    created = client.post(
        f"/api/projects/{project.id}/entities", json={"kind": "character", "name": "Рыхташ"}
    ).json()
    again = client.post(
        f"/api/projects/{project.id}/entities", json={"kind": "character", "name": "рыхташ"}
    ).json()
    assert created["id"] == again["id"]
    assert upload(client, project, created["id"])[0]["is_main"] is True


def test_look_prompt_uses_the_state_of_its_chapters(session, project):
    class Recorder:
        def invoke(self, operation, messages):
            self.system, self.facts = messages[0].content, messages[1].content
            return " A red-haired woman in chain mail. "

    hero = session.get(Entity, project.hero_id)
    project.style_id = "dark_fantasy"
    model = Recorder()
    last = project.chapters[2].id
    chapters = chapters_between(project, last, "")
    assert [c.title for c in chapters] == ["Замок"]
    prompt = build_image_prompt(model, project, hero, chapters, "в кольчуге", has_reference=True)
    assert prompt == "A red-haired woman in chain mail."
    assert "рыжие волосы" in model.facts and "кольчуга" in model.facts
    assert "красный платок" not in model.facts  # that was two chapters earlier
    assert "must match the reference" in model.system and "dark fantasy" in model.system

    # The base picture: permanent traits only.
    build_image_prompt(model, project, hero, None, "", has_reference=False)
    assert "кольчуга" not in model.facts and "рыжие волосы" in model.facts

    # A main picture in a chosen view is framed for that view.
    build_image_prompt(model, project, hero, None, "", has_reference=True, angle="full_back")
    assert "seen from behind" in model.system and "must match the references" in model.system


def image_model(session, project, handler):
    connection = Connection(name="Router", base_url="https://router.test/v1")
    session.add(connection)
    session.flush()
    session.merge(AppSetting(key="image_connection_id", value=connection.id))
    session.merge(AppSetting(key="image_model", value="painter"))
    session.commit()
    return ImageModel(session, project.id, transport=httpx.MockTransport(handler))


def test_generation_through_chat_completions_with_a_reference(session, project, tmp_path):
    reference = tmp_path / "main.png"
    reference.write_bytes(PNG)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
        message = {"role": "assistant", "content": "", "images": [{"image_url": {"url": data_url}}]}
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"prompt_tokens": 7}}
        )

    result = image_model(session, project, handler).generate("a woman", [reference])
    assert (result.data, result.mime) == (PNG, "image/png")
    assert seen["path"] == "/v1/chat/completions"
    content = seen["body"]["messages"][0]["content"]
    assert [part["type"] for part in content] == ["text", "image_url"]
    assert seen["body"]["modalities"] == ["image", "text"]


def test_generation_falls_back_to_the_images_endpoint(session, project):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(404, json={"error": "no such route"})
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    assert image_model(session, project, handler).generate("a castle").data == PNG


def test_generation_passes_the_chosen_size_to_both_endpoints(session, project):
    bodies = {}

    def handler(request: httpx.Request) -> httpx.Response:
        bodies[request.url.path.rsplit("/", 1)[-1]] = json.loads(request.content)
        if request.url.path.endswith("/completions"):
            return httpx.Response(404, json={"error": "no such route"})
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    image_model(session, project, handler).generate("a castle", size="16:9")
    assert bodies["completions"]["image_config"] == {"aspect_ratio": "16:9"}
    assert bodies["generations"]["size"] == "1792x1024"
    with pytest.raises(ValueError):
        image_model(session, project, handler).generate("a castle", size="7:3")


def test_generation_reports_a_provider_error(session, project, tmp_path):
    reference = tmp_path / "main.png"
    reference.write_bytes(PNG)
    model = image_model(session, project, lambda request: httpx.Response(402, text="no credits"))
    with pytest.raises(ImageGenerationFailed, match="402"):
        model.generate("a woman", [reference])


def test_generate_endpoint_needs_style_and_model(client, session, project):
    session.query(AppSetting).filter(AppSetting.key.like("image_%")).delete()
    session.commit()
    url = f"/api/entities/{project.hero_id}/images/generate"
    assert client.post(url, json={"prompt": "x"}).json()["detail"] == "style_not_chosen"
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    assert client.post(url, json={"prompt": "x"}).json()["detail"] == "image_model_not_configured"


def test_pictures_uploaded_before_a_style_adopt_the_first_one(client, project):
    early = upload(client, project, project.hero_id)[0]
    assert (early["style_key"], early["is_main"]) == ("", True)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "cinematic"})
    listed = client.get(
        f"/api/projects/{project.id}/images", params={"entity_id": project.hero_id}
    ).json()
    assert [(i["style_key"], i["current_style"], i["is_main"]) for i in listed] == [
        ("cinematic", True, True)
    ]


def test_a_base_set_shares_one_prompt_and_adds_each_view(client, session, project, monkeypatch):
    class Recorder:
        def invoke(self, operation, messages):
            self.system = messages[0].content
            return "A red-haired woman."

    hero = session.get(Entity, project.hero_id)
    model = Recorder()
    build_image_prompt(model, project, hero, None, "", has_reference=False, view_free=True)
    assert "appearance only" in model.system and "Head-and-shoulders" not in model.system

    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append((prompt, len(references)))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.images.ImageModel", Painter)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    url = f"/api/entities/{project.hero_id}/images/generate"
    for angle in ("face_front", "face_three_quarter"):
        made = client.post(
            url, json={"prompt": "A red-haired woman.", "angle": angle, "add_view": True}
        )
        assert made.status_code == 200, made.text
        assert (made.json()["is_main"], made.json()["angle"]) == (True, angle)
    # Each picture gets its own view in front; the second one is drawn from the first.
    assert drawn[0][0].startswith("Head-and-shoulders portrait, face turned straight")
    assert drawn[1][0].startswith("Head-and-shoulders portrait, face turned three-quarters")
    assert drawn[0][0].endswith("A red-haired woman.")
    assert [references for _, references in drawn] == [0, 1]


def test_card_list_carries_a_blurb_the_first_chapter_and_a_picture(client, project):
    brief = lambda: client.get(f"/api/projects/{project.id}/entities?kind=character").json()[0]
    assert (brief()["first_chapter"], brief()["cover"]) == ("Мельница", "")
    client.put(
        f"/api/entities/{project.hero_id}/description", json={"text": "Дочь мельника. " * 30}
    )
    image = upload(client, project, project.hero_id)[0]
    shown = brief()
    assert shown["cover"] == image["url"]
    assert shown["blurb"].startswith("Дочь мельника.") and shown["blurb"].endswith("…")
    assert len(shown["blurb"]) <= 161


def test_pictures_are_drawn_from_the_appearance_and_the_users_own_wins(client, session, project):
    class Recorder:
        def invoke(self, operation, messages):
            self.facts = messages[1].content
            return "prompt"

    hero = session.get(Entity, project.hero_id)
    hero.appearance = "Худая девушка лет двадцати, рыжая коса, серый плащ."
    session.commit()
    model = Recorder()
    build_image_prompt(model, project, hero, None, "", has_reference=False)
    assert "Appearance: Худая девушка лет двадцати" in model.facts

    saved = client.put(f"/api/entities/{hero.id}/appearance", json={"text": "Высокая, в кольчуге."})
    assert saved.json()["appearance_own"] == "Высокая, в кольчуге."
    session.refresh(hero)
    build_image_prompt(model, project, hero, None, "", has_reference=False)
    assert "Appearance: Высокая, в кольчуге." in model.facts and "Худая" not in model.facts


def test_deleting_a_card_keeps_its_pictures(client, session, project):
    image = upload(client, project, project.hero_id)[0]
    assert client.delete(f"/api/entities/{project.hero_id}").status_code == 204
    assert client.get(f"/api/entities/{project.hero_id}").status_code == 404
    left = client.get(f"/api/projects/{project.id}/images").json()
    assert [(i["id"], i["entity_id"]) for i in left] == [(image["id"], None)]


def test_the_users_samples_go_to_the_image_model_first(client, project, monkeypatch):
    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append([path.name for path in references])
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.images.ImageModel", Painter)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    base = upload(client, project, project.hero_id)[0]  # the first upload is a main picture
    sample = upload(client, project, project.hero_id)[0]
    client.patch(f"/api/images/{sample['id']}", json={"is_main": False})
    url = f"/api/entities/{project.hero_id}/images/generate"
    made = client.post(
        url, json={"prompt": "x", "angle": "face_front", "reference_ids": [sample["id"]]}
    )
    assert made.status_code == 200, made.text
    names = drawn[0]
    assert len(names) == 2 and names[0].startswith(sample["id"]) and names[1].startswith(base["id"])
    assert client.post(url, json={"prompt": "x", "reference_ids": ["nope"]}).status_code == 404


def test_a_picture_put_in_as_it_is_is_checked_against_the_style(client, project, monkeypatch):
    url = f"/api/projects/{project.id}/style-check"
    files = {"file": ("x.png", PNG, "image/png")}
    assert client.post(url, files=files).json()["matches"] is True  # no style yet
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    seen = {}

    def judge(model, style, data, mime):
        seen["style"], seen["mime"] = style, mime
        return StyleVerdict(matches=False, reason="Фото, а не аниме.")

    class Model:
        def __init__(self, session, project_id, task=None):
            pass

    monkeypatch.setattr("app.api.images.check_style", judge)
    monkeypatch.setattr("app.api.images.TextModel", Model)
    verdict = client.post(url, files=files).json()
    assert verdict == {"matches": False, "reason": "Фото, а не аниме."}
    assert seen["mime"] == "image/png" and seen["style"]


def test_references_go_into_empty_slots_only_when_clean_and_in_style():
    verdict = SortVerdict(
        pictures=[
            PictureVerdict(n=1, view="face_front", clean=True, style_ok=True),
            PictureVerdict(n=2, view="face_front", clean=True, style_ok=True),  # view taken by 1
            PictureVerdict(n=3, view="full_front", clean=True, style_ok=False),  # photo: redrawn
            PictureVerdict(n=4, view="face_profile", clean=False, style_ok=True),  # busy picture
            PictureVerdict(n=5, view="full_back", clean=True, style_ok=True),  # slot filled
            PictureVerdict(n=6, view="sideways", clean=True, style_ok=True),  # unknown view
        ]
    )
    result = decide(verdict, 6, taken={"full_back"})
    assert result.same_person
    assert [(p.index, p.angle) for p in result.placed] == [(0, "face_front")]
    assert result.views[5] == "" and result.views[2] == "full_front"


def test_references_of_different_people_are_refused():
    named = decide(SortVerdict(same_person=False, others=[2, 9], reason="№2 — другой"), 3, set())
    assert (named.same_person, named.others, named.placed) == (False, [1], [])
    unnamed = decide(SortVerdict(same_person=False), 2, set())
    assert unnamed.others == [0, 1]


def test_the_references_are_looked_at_together(client, project, monkeypatch):
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    seen = {}

    def look(model, style, pictures, character):
        seen["count"], seen["character"] = len(pictures), character
        return SortVerdict(
            pictures=[PictureVerdict(n=1, view="face_front", clean=True, style_ok=True)]
        )

    class Model:
        def __init__(self, session, project_id, task=None):
            pass

    monkeypatch.setattr("app.api.images.ask_model", look)
    monkeypatch.setattr("app.api.images.TextModel", Model)
    url = f"/api/entities/{project.hero_id}/references/sort"
    files = [("files", (f"r{n}.png", PNG, "image/png")) for n in range(2)]
    result = client.post(url, files=files)
    assert result.status_code == 200, result.text
    assert result.json()["placed"] == [{"index": 0, "angle": "face_front"}]
    assert seen == {"count": 2, "character": "Люта"}
    too_many = [("files", (f"r{n}.png", PNG, "image/png")) for n in range(7)]
    assert client.post(url, files=too_many).status_code == 422
