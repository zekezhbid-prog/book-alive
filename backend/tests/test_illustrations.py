# ruff: noqa: F401, F811 (the fixtures are imported by name)
from app import illustrations
from tests.test_images import PNG, project, session, upload

# The text model asks back first, then plans the picture.
ANSWERS = [
    {"question": "Какой момент: встреча или прощание?"},
    {
        "chapter": "Мельница",
        "cast": ["Люта", "Никто"],
        "say": "Рисую Люту у мельницы.",
        "prompt": "[[Люта]] stands by the mill wheel at dawn. Style.",
    },
]


class Planner:
    def __init__(self, session, project_id, task):
        assert task == "prompts"

    def invoke_json(self, operation, messages, schema):
        Planner.seen = messages[1].content
        return schema.model_validate(ANSWERS.pop(0))


def test_a_picture_is_planned_in_a_dialogue_and_drawn_from_card_references(
    client,
    project,
    monkeypatch,
):
    monkeypatch.setattr("app.api.illustrations.TextModel", Planner)
    monkeypatch.setattr(illustrations, "search", lambda *a, **k: [])
    monkeypatch.setattr(illustrations, "index_project", lambda *a: 0)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    face = upload(client, project, project.hero_id)[0]
    client.patch(f"/api/images/{face['id']}", json={"is_main": True, "angle": "face_front"})

    made = client.post(f"/api/projects/{project.id}/illustrations").json()
    assert made["messages"] == [] and made["title"] == ""
    url = f"/api/illustrations/{made['id']}"
    asked = client.post(f"{url}/ask", json={"text": "Люта у мельницы"}).json()
    assert asked["title"] == "Люта у мельницы"
    assert asked["messages"][-1]["text"] == "Какой момент: встреча или прощание?"
    assert client.post(f"{url}/draw").status_code == 409  # nothing planned yet

    planned = client.post(f"{url}/ask", json={"text": "встреча"}).json()["messages"][-1]
    # The card named in the request is offered with its pictures; the unknown name is dropped.
    assert "Люта (character, has pictures)" in Planner.seen
    assert planned["cast"] == ["Люта"]
    assert planned["prompt"].startswith("the figure from reference 1 stands")
    assert planned["reference_urls"] == [face["url"]]

    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append((prompt, len(references)))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    done = client.post(f"{url}/draw").json()
    assert drawn == [(planned["prompt"], 1)]
    assert done["messages"][-1]["image_url"] == done["cover"] != ""
    listed = client.get(f"/api/projects/{project.id}/illustrations").json()
    assert [i["id"] for i in listed] == [made["id"]]
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
