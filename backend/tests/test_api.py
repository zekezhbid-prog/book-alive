from tests.conftest import make_book


def create(client, mode="writer", chapters=3):
    response = client.post(
        "/api/projects",
        data={"mode": mode},
        files={"file": ("Моя книга.txt", make_book(chapters), "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_import_splits_into_chapters_without_ai(client):
    project = create(client, "reader")
    assert project["title"] == "Моя книга"
    assert project["split_method"] == "pattern"
    assert [c["title"] for c in project["chapters"]] == ["Глава 1", "Глава 2", "Глава 3"]
    assert project["version"] is None  # versions exist only for writer projects


def test_reader_project_needs_a_file(client):
    assert client.post("/api/projects", data={"mode": "reader"}).status_code == 422


def test_writer_project_can_start_empty(client):
    project = client.post("/api/projects", data={"mode": "writer", "title": "Новая"}).json()
    assert project["chapters"] == []
    assert project["version"]["number"] == 1
    chapter = client.post(f"/api/projects/{project['id']}/chapters", json={"title": "Начало"})
    assert chapter.json()["position"] == 0


def test_reader_text_is_read_only_but_boundaries_can_be_fixed(client):
    project = create(client, "reader")
    first = project["chapters"][0]["id"]
    assert client.patch(f"/api/chapters/{first}", json={"text": "x"}).status_code == 409
    assert client.patch(f"/api/chapters/{first}", json={"title": "Пролог"}).status_code == 200
    assert client.post(f"/api/projects/{project['id']}/chapters", json={}).status_code == 409

    merged = client.post(f"/api/chapters/{first}/merge-next").json()
    assert "Глава 2" in merged["text"]
    assert len(client.get(f"/api/projects/{project['id']}").json()["chapters"]) == 2

    _, tail = client.post(
        f"/api/chapters/{first}/split", json={"paragraph": 4, "title": "Глава 2"}
    ).json()
    assert tail["text"].startswith("Глава 2")
    titles = [c["title"] for c in client.get(f"/api/projects/{project['id']}").json()["chapters"]]
    assert titles == ["Пролог", "Глава 2", "Глава 3"]


def test_commit_and_rollback(client):
    project = create(client)
    pid = project["id"]
    first, second, third = (c["id"] for c in project["chapters"])
    assert project["version"]["number"] == 1
    assert project["changes"]["dirty"] is False
    assert client.post(f"/api/projects/{pid}/versions", json={}).status_code == 409

    # Edits in several chapters, then one commit for the whole book.
    client.patch(f"/api/chapters/{first}", json={"text": "Новый текст первой главы."})
    client.patch(f"/api/chapters/{second}", json={"title": "Глава вторая"})
    client.delete(f"/api/chapters/{third}")
    changes = client.get(f"/api/projects/{pid}").json()["changes"]
    assert (changes["edited"], changes["renamed"], changes["removed"]) == (
        [first],
        [second],
        [third],
    )

    committed = client.post(f"/api/projects/{pid}/versions", json={"label": "правки"}).json()
    assert committed["version"]["number"] == 2
    assert committed["changes"]["dirty"] is False

    versions = client.get(f"/api/projects/{pid}/versions").json()
    v1 = next(v for v in versions if v["number"] == 1)

    # Uncommitted work is saved as its own version before rolling back.
    client.patch(f"/api/chapters/{first}", json={"text": "Не зафиксировано."})
    rolled = client.post(f"/api/projects/{pid}/versions/{v1['id']}/rollback").json()
    assert [c["id"] for c in rolled["chapters"]] == [first, second, third]
    assert [c["title"] for c in rolled["chapters"]] == ["Глава 1", "Глава 2", "Глава 3"]
    assert rolled["changes"]["dirty"] is False
    labels = [v["label"] for v in client.get(f"/api/projects/{pid}/versions").json()]
    assert labels == ["rollback:1", "autosave", "правки", "import"]
    assert client.get(f"/api/chapters/{first}").json()["text"].startswith("Абзац 0 главы 1")


def test_reorder(client):
    project = create(client)
    ids = [c["id"] for c in project["chapters"]]
    moved = client.post(
        f"/api/projects/{project['id']}/reorder", json={"chapter_ids": ids[::-1]}
    ).json()
    assert [c["id"] for c in moved["chapters"]] == ids[::-1]
    assert moved["changes"]["reordered"] is True


def test_search(client):
    project = create(client, "reader")
    hits = client.get(
        f"/api/projects/{project['id']}/search", params={"q": "абзац 2 главы 3"}
    ).json()
    assert len(hits) == 1
    assert (hits[0]["chapter_title"], hits[0]["paragraph"]) == ("Глава 3", 2)


def test_api_key_is_never_returned(client):
    created = client.post(
        "/api/connections",
        json={"name": "Router", "base_url": "https://example.test/v1", "api_key": "sk-secret-1234"},
    ).json()
    assert created["api_key_hint"] == "…1234"
    assert "sk-secret" not in client.get("/api/connections").text

    client.put("/api/settings", json={"text_connection_id": created["id"], "text_model": "m"})
    assert client.delete(f"/api/connections/{created['id']}").status_code == 204
    assert client.get("/api/settings").json()["text_connection_id"] == ""


def test_connection_needs_a_url(client):
    response = client.post("/api/connections", json={"name": "x", "base_url": "example.test"})
    assert response.status_code == 422


def test_delete_project(client):
    project = create(client)
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_damaged_upload_is_a_clean_error(client):
    response = client.post(
        "/api/projects",
        data={"mode": "reader"},
        files={"file": ("book.epub", b"PK\x03\x04 broken", "application/epub+zip")},
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("unsupported_book")


def test_title_longer_than_the_column_is_rejected(client):
    project = create(client)
    chapter = project["chapters"][0]["id"]
    response = client.patch(f"/api/chapters/{chapter}", json={"title": "я" * 301})
    assert (response.status_code, response.json()["detail"]) == (422, "title_too_long")


def test_project_list_reports_sizes(client):
    project = create(client, chapters=2)
    listed = next(p for p in client.get("/api/projects").json() if p["id"] == project["id"])
    assert listed["chapters"] == 2
    assert listed["chars"] == sum(c["chars"] for c in project["chapters"])
