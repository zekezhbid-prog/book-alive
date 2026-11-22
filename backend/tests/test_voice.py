from app import voice


def test_transcribe_returns_the_words(client, monkeypatch):
    heard = []

    def fake(audio, language=None):
        heard.append((audio, language))
        return "Рыхташ хромает"

    monkeypatch.setattr(voice, "transcribe", fake)
    response = client.post(
        "/api/transcribe",
        files={"file": ("note.webm", b"\x1a\x45\xdf\xa3 audio", "audio/webm")},
        data={"language": "ru"},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "Рыхташ хромает"}
    assert heard == [(b"\x1a\x45\xdf\xa3 audio", "ru")]


def test_empty_or_broken_audio_is_refused(client, monkeypatch):
    def broken(audio, language=None):
        raise ValueError("Invalid data found when processing input")

    monkeypatch.setattr(voice, "transcribe", broken)
    empty = client.post("/api/transcribe", files={"file": ("a.webm", b"", "audio/webm")})
    assert empty.status_code == 422 and empty.json()["detail"] == "audio_empty"
    bad = client.post("/api/transcribe", files={"file": ("a.webm", b"xx", "audio/webm")})
    assert bad.status_code == 422 and bad.json()["detail"] == "audio_unreadable"
    lang = client.post(
        "/api/transcribe",
        files={"file": ("a.webm", b"xx", "audio/webm")},
        data={"language": "xx"},
    )
    assert lang.status_code == 422
