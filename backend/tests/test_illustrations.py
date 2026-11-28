# ruff: noqa: F401, F811 (the fixtures are imported by name)
from app import illustrations
from tests.test_images import PNG, project, session, upload

# The text model asks back first, then plans the picture.
ANSWERS = [
    {"question": "Какой момент: встреча или прощание?"},
    {
        "chapter": "Мельница",
        "cast": ["Лана", "Никто"],
        "say": "Рисую Лану у мельницы.",
        "prompt": "[[Лана]] stands by the mill wheel at dawn. Style.",
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
    asked = client.post(f"{url}/ask", json={"text": "Лана у мельницы"}).json()
    assert asked["title"] == "Лана у мельницы"
    assert asked["messages"][-1]["text"] == "Какой момент: встреча или прощание?"
    assert client.post(f"{url}/draw").status_code == 409  # nothing planned yet

    planned = client.post(f"{url}/ask", json={"text": "встреча"}).json()["messages"][-1]
    # The card named in the request is offered with its pictures; the unknown name is dropped.
    assert "Лана (character, has pictures)" in Planner.seen
    assert planned["cast"] == ["Лана"]
    assert planned["prompt"].startswith("the figure from reference 1 stands")
    assert planned["reference_urls"] == [face["url"]]

    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append((prompt, len(references), size))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    # The aspect ratio is chosen in the dialogue's field (owner's notes 27.11, item 30).
    assert client.post(f"{url}/draw", json={"size": "7:5"}).status_code == 422
    done = client.post(f"{url}/draw", json={"size": "3:2"}).json()
    assert drawn == [(planned["prompt"], 1, "3:2")]
    assert done["messages"][-1]["image_url"] == done["cover"] != ""
    # Named after the request the picture was drawn from (owner's notes 27.11, item 15).
    assert done["title"] == "Лана у мельницы, встреча"
    listed = client.get(f"/api/projects/{project.id}/illustrations").json()
    assert [i["id"] for i in listed] == [made["id"]]
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_the_planner_never_refuses_and_offers_to_draw_what_the_book_lacks():
    # Owner's notes 26.11: "not found, draw anyway?" instead of "I won't draw it";
    # anything of the book in the request is drawn from the book.
    system = illustrations.PLAN_SYSTEM
    assert "Never refuse to draw" in system
    assert "ask if you should draw it anyway" in system
    assert "even if the book has no such moment" in system


def test_a_card_without_a_reference_is_named_before_drawing(client, project, monkeypatch):
    # Owner's notes 27.11 (13): the cast had no references and the picture was drawn anyway.
    # The plan names the cards that lack one; a reference made afterwards counts at drawing.
    answers = [
        {
            "chapter": "Мельница",
            "cast": ["Лана"],
            "say": "Рисую Лану у мельницы.",
            "prompt": "[[Лана]] stands by the mill wheel at dawn.",
        }
    ]

    class OnePlan(Planner):
        def invoke_json(self, operation, messages, schema):
            return schema.model_validate(answers.pop(0))

    monkeypatch.setattr("app.api.illustrations.TextModel", OnePlan)
    monkeypatch.setattr(illustrations, "search", lambda *a, **k: [])
    monkeypatch.setattr(illustrations, "index_project", lambda *a: 0)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    url = f"/api/illustrations/{client.post(f'/api/projects/{project.id}/illustrations').json()['id']}"

    planned = client.post(f"{url}/ask", json={"text": "Лана у мельницы"}).json()["messages"][-1]
    assert planned["missing"] == [
        {"entity_id": project.hero_id, "name": "Лана", "kind": "character"}
    ]
    assert planned["reference_urls"] == []
    assert planned["prompt"] == "Лана stands by the mill wheel at dawn."

    # The user went to the card and made a reference: the plan no longer lacks it.
    face = upload(client, project, project.hero_id)[0]
    assert client.get(url).json()["messages"][-1]["missing"] == []

    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append((prompt, len(references)))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    done = client.post(f"{url}/draw").json()
    assert drawn == [("the figure from reference 1 stands by the mill wheel at dawn.", 1)]
    plan = done["messages"][-2]
    assert plan["reference_urls"] == [face["url"]] and plan["missing"] == []
    assert plan["prompt"] == drawn[0][0]
    assert client.get(url).json()["messages"][-2]["prompt"] == drawn[0][0]  # saved


def test_a_card_is_named_after_its_last_picture_until_the_user_renames_it(
    client, project, monkeypatch
):
    # Owner's notes 27.11 (15): the name comes from the request a picture was drawn from, not
    # the first words of the dialogue; a name the user wrote stays.
    plan = {"chapter": "", "cast": [], "say": "Рисую.", "prompt": "A mill at dawn."}

    class Plans(Planner):
        def invoke_json(self, operation, messages, schema):
            return schema.model_validate(plan)

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.TextModel", Plans)
    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    monkeypatch.setattr(illustrations, "search", lambda *a, **k: [])
    monkeypatch.setattr(illustrations, "index_project", lambda *a: 0)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    url = f"/api/illustrations/{client.post(f'/api/projects/{project.id}/illustrations').json()['id']}"

    client.post(f"{url}/ask", json={"text": "мельница"})
    assert client.post(f"{url}/draw").json()["title"] == "мельница"
    client.post(f"{url}/ask", json={"text": "  теперь   ночью "})
    second = client.post(f"{url}/draw").json()
    assert second["title"] == "теперь ночью"
    assert second["cover"] == second["messages"][-1]["image_url"]  # the last picture

    assert (
        client.patch(url, json={"title": "  Ночная мельница "}).json()["title"] == "Ночная мельница"
    )
    client.post(f"{url}/ask", json={"text": "днём"})
    assert client.post(f"{url}/draw").json()["title"] == "Ночная мельница"
    # An emptied name goes back to the automatic one.
    assert client.patch(url, json={"title": " "}).json()["title"] == "днём"
    assert client.patch(url, json={"title": "x" * 301}).status_code == 422


def test_the_last_picture_leans_on_the_one_before_and_a_removed_reference_is_not_sent(
    client, project, monkeypatch
):
    # Owner's notes 28.11 (58): the picture just drawn is attached to the next one; the
    # card's picture can be removed, and then its name is plain text in the prompt.
    plan = {"chapter": "", "cast": ["Лана"], "say": "Рисую.", "prompt": "[[Лана]] at the mill."}

    class Plans(Planner):
        def invoke_json(self, operation, messages, schema):
            return schema.model_validate(plan)

    drawn = []

    class Painter:
        def __init__(self, session, project_id):
            pass

        def generate(self, prompt, references, size=""):
            drawn.append((prompt, len(references)))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.TextModel", Plans)
    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    monkeypatch.setattr(illustrations, "search", lambda *a, **k: [])
    monkeypatch.setattr(illustrations, "index_project", lambda *a: 0)
    client.put(f"/api/projects/{project.id}/style", json={"style_id": "anime"})
    face = upload(client, project, project.hero_id)[0]
    client.patch(f"/api/images/{face['id']}", json={"is_main": True, "angle": "face_front"})
    url = f"/api/illustrations/{client.post(f'/api/projects/{project.id}/illustrations').json()['id']}"

    planned = client.post(f"{url}/ask", json={"text": "Лана у мельницы"}).json()["messages"][-1]
    assert planned["reference_ids"] == [face["id"]]
    first = client.post(f"{url}/draw").json()["messages"][-1]
    assert first["image_id"] and drawn[-1] == ("the figure from reference 1 at the mill.", 1)

    client.post(f"{url}/ask", json={"text": "ночью"})
    body = {"previous_id": first["image_id"], "skip_ids": [face["id"]]}
    done = client.post(f"{url}/draw", json=body).json()["messages"][-1]
    prompt, count = drawn[-1]
    assert count == 1 and prompt.startswith("Лана at the mill.")
    assert "reference 1" in prompt and done["reference_ids"] == [first["image_id"]]

    client.post(f"{url}/ask", json={"text": "днём"})
    client.post(f"{url}/draw", json={"previous_id": first["image_id"]})
    prompt, count = drawn[-1]
    assert (
        count == 2 and prompt.startswith("the figure from reference 1") and "reference 2" in prompt
    )
    foreign = {"previous_id": "nope"}
    client.post(f"{url}/ask", json={"text": "вечером"})
    assert client.post(f"{url}/draw", json=foreign).status_code == 404
