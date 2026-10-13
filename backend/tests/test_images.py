import base64
import json

import httpx
import pytest
from sqlalchemy.orm import Session

from app.db import get_engine
from app.images.generate import ImageGenerationFailed, ImageModel
from app.images.prompts import build_image_prompt, chapters_between
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


def test_one_main_picture_per_card(client, project):
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    first, second = upload(client, project, project.hero_id, count=2)
    assert (first["is_main"], second["is_main"]) == (True, False)
    client.patch(f"/api/images/{second['id']}", json={"is_main": True, "look_label": "в кольчуге"})
    listed = client.get(
        f"/api/projects/{project.id}/images", params={"entity_id": project.hero_id}
    ).json()
    assert {i["id"]: i["is_main"] for i in listed} == {first["id"]: False, second["id"]: True}


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
