import io
import json
import zipfile

from app.models import Scene
from app.scenes import export
from app.scenes.export import CLIP_SECONDS, ExportOptions, Line, Plan, Shot, clips_of, tidy
from tests.test_scenes import book, session  # noqa: F401  (fixtures)

PLAN = {
    "language": "ru",
    "setting": "an old water mill at dawn, mist over the river",
    "mood": "quiet, tense",
    "palette": "cold blue dawn, warm lamp light",
    "music": "low strings",
    "subjects": [
        {"name": "Лана", "look": "a young woman with red hair in a red headscarf"},
        {"name": "Мельница", "look": "a wooden water mill with a creaking wheel"},
    ],
    "shots": [
        {
            "start": 0,
            "end": 5,
            "shot_size": "wide",
            "camera": "slow push in",
            "action": "The mill in the mist.",
            "on_screen": ["Мельница"],
            "references": [],
            "sound": "water, creaking wheel",
            "script": "Мельница на рассвете.",
        },
        {
            "start": 5,
            "end": 10,
            "shot_size": "medium",
            "camera": "static",
            "action": "The woman waits inside.",
            "on_screen": ["Лана"],
            "references": [2, 1, 99],
            "lines": [{"text": "Внутри его ждала Лана", "narration": True}],
            "script": "Лана ждёт.",
        },
        {
            "start": 10,
            "end": 14,
            "shot_size": "close-up",
            "camera": "orbital shot",
            "action": "She holds out a silver key.",
            "on_screen": ["Лана"],
            "references": [1],
            "lines": [{"speaker": "Лана", "text": "Держи, это твой ключ"}],
            "script": "Ключ.",
        },
        {
            "start": 14,
            "end": 20,
            "shot_size": "wide",
            "camera": "crane shot",
            "action": "They leave the mill.",
            "on_screen": ["Лана"],
            "references": [1],
            "script": "Уходят.",
        },
    ],
}


class PlanModel:
    request_overhead = 0

    def __init__(self):
        self.system = self.context = ""

    def invoke_json(self, operation, messages, schema):
        assert operation == "scene_export"
        self.system, self.context = messages[0].content, messages[1].content
        return schema.model_validate(PLAN)


def _scene(client, session, book):  # noqa: F811 (fixtures from test_scenes)
    made = client.post(
        f"/api/chapters/{book.mill.id}/scenes",
        json={"paragraph_from": 0, "paragraph_to": 3, "title": "Ключ"},
    ).json()
    return session.get(Scene, made["id"])


def test_shots_stay_inside_the_video_and_clips_stay_short():
    shot = {"action": "x", "shot_size": "", "camera": ""}
    plan = Plan(
        shots=[
            Shot(start=8, end=30, references=[1, 7, 1], **shot),  # longer than a clip
            Shot(start=0, end=8, **shot),
            Shot(start=40, end=50, **shot),  # after the end of the video
        ]
    )
    tidied = tidy(plan, duration=24, pictures=3)
    assert [(s.start, s.end) for s in tidied.shots] == [(0, 8), (8, 23)]
    assert tidied.shots[1].references == [1]
    assert all(s.end - s.start <= CLIP_SECONDS for s in tidied.shots)
    groups = clips_of(tidied.shots)
    assert [len(g) for g in groups] == [1, 1]  # 0-8 and 8-23 do not fit in one clip


def test_a_line_counts_as_the_books_only_if_it_stands_in_the_text():
    text = "Внутри его ждала Лана в красном платке."
    assert export.verified(Line(text="внутри его ждала Лана"), text)
    assert not export.verified(Line(text="Держи, это твой ключ"), text)


def test_export_archive_holds_clips_pictures_plan_and_instructions(client, session, book):  # noqa: F811 (fixtures from test_scenes)
    scene = _scene(client, session, book)
    options = ExportOptions(duration=20, aspect="9:16", effects="falling dust", images_per_clip=1)
    model = PlanModel()
    plan, pool = export.plan_scene(session, model, book, scene, book.mill, options)
    assert "20 seconds long, format 9:16" in model.system
    assert "Visual effects wanted: falling dust" in model.context
    assert "red" not in model.system  # appearance comes from the facts in the context only
    assert "рыжие волосы" in model.context

    data = export.export_archive(session, book, scene, book.mill, plan, pool, options)
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        names = set(bundle.namelist())
        manifest = json.loads(bundle.read("scene.json"))
        first = bundle.read("clips/clip01.txt").decode()
        start_here = bundle.read("START_HERE.md").decode()
        script = bundle.read("script.md").decode()
    assert {
        "START_HERE.md",
        "scene.json",
        "script.md",
        "clips/clip01.txt",
        "clips/clip02.txt",
    } <= names
    assert manifest["size"] == [1080, 1920] and manifest["duration"] == 20
    assert [(c["start"], c["end"]) for c in manifest["clips"]] == [(0, 14), (14, 20)]
    # One picture per clip was asked for: the first wanted one, people first.
    assert [len(c["images"]) for c in manifest["clips"]] == [1, 1]
    assert manifest["clips"][0]["images"][0]["tag"] == "@Image1"
    for clip in manifest["clips"]:
        for image in clip["images"]:
            assert image["file"] in names
    # The made-up line is flagged; the narrator's line is the book's own.
    lines = [line for shot in manifest["shots"] for line in shot["lines"]]
    assert [(line["narration"], line["verified"]) for line in lines] == [
        (True, True),
        (False, False),
    ]
    assert "@Image1 - strict identity reference for Лана" in first
    assert "a young woman with red hair in a red headscarf" in first
    assert "[0:05-0:10] medium, static." in first
    assert first.rstrip().endswith("4K cinematic.")
    assert "Format: 9:16, 14 seconds" in first
    assert "Effects: falling dust" in first
    assert "1080x1920" in start_here and "Remotion" in start_here
    assert "Лана: «Держи, это твой ключ»" in script


def test_export_api_asks_for_a_model_and_a_known_format(client, session, book):  # noqa: F811 (fixtures from test_scenes)
    scene = _scene(client, session, book)
    url = f"/api/scenes/{scene.id}/export"
    assert client.post(url, json={"aspect": "4:3"}).status_code == 422
    assert client.post(url, json={"duration": 2}).status_code == 422
    assert client.post(url, json={}).status_code == 409  # no text model chosen
