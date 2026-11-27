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
            drawn.append((prompt, len(references)))
            return type("Result", (), {"data": PNG, "mime": "image/png"})()

    monkeypatch.setattr("app.api.illustrations.ImageModel", Painter)
    done = client.post(f"{url}/draw").json()
    assert drawn == [(planned["prompt"], 1)]
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


def test_picture_ideas_of_a_chapter_come_from_its_text(client, project, session, monkeypatch):
    # Owner's notes 26.11: "Pick from the book" -> a chapter -> 3 to 20 scenes to draw.
    seen = {}

    class Ideas:
        def __init__(self, session, project_id, task):
            assert task == "prompts"

        def invoke_json(self, operation, messages, schema):
            seen["text"] = messages[1].content
            ideas = [{"title": f"S{n}", "description": f"  Сцена {n}. "} for n in range(25)]
            return schema.model_validate({"ideas": [*ideas, {"title": "", "description": ""}]})

    monkeypatch.setattr("app.api.illustrations.TextModel", Ideas)
    first, second, _ = project.chapters
    url = f"/api/projects/{project.id}/chapters/{first.id}/picture-ideas"
    ideas = client.post(url).json()
    assert len(ideas) == 20 and ideas[0] == {"title": "S0", "description": "Сцена 0."}
    assert "Мельница" in seen["text"]
    assert "up to 20" in illustrations.IDEAS_SYSTEM
    second.private = True
    session.commit()
    hidden = f"/api/projects/{project.id}/chapters/{second.id}/picture-ideas"
    assert client.post(hidden).status_code == 404
    assert client.post(f"/api/projects/{project.id}/chapters/nope/picture-ideas").status_code == 404


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
