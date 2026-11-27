# ruff: noqa: F401, F811 (the fixtures are imported by name)
from tests.test_images import project, session, upload


def test_the_reference_window_keeps_its_dialogue(client, project):
    # Owner's notes 27.11 (19): the references window is a dialogue; its lines are kept with
    # the card, and a picture in it is shown while it exists.
    url = f"/api/entities/{project.hero_id}/ref-chat"
    assert client.get(url).json() == []

    face = upload(client, project, project.hero_id)[0]
    lines = [
        {"role": "assistant", "kind": "offer", "text": "Рисуем анфас?", "view": "face_front"},
        {"role": "assistant", "kind": "prompt", "prompt": "A woman, face front."},
        {"role": "assistant", "kind": "image", "image_id": face["id"], "view": "face_front"},
        {"role": "user", "text": "  светлее  "},
    ]
    saved = client.post(url, json=lines).json()
    assert [m["kind"] for m in saved] == ["offer", "prompt", "image", "text"]
    assert saved[2]["image_url"] == face["url"]
    assert saved[3]["text"] == "светлее"
    assert client.get(url).json() == saved

    # A deleted picture leaves its line without a picture.
    client.delete(f"/api/images/{face['id']}")
    assert client.get(url).json()[2]["image_url"] == ""

    # Only the latest lines are kept.
    for _ in range(4):
        client.post(url, json=[{"role": "user", "text": "x"}] * 60)
    assert len(client.get(url).json()) == 200

    assert client.post(url, json=[{"role": "robot", "text": "x"}]).status_code == 422
    assert client.post(url, json=[{"role": "user", "kind": "nope"}]).status_code == 422
    assert client.get("/api/entities/nope/ref-chat").status_code == 404
