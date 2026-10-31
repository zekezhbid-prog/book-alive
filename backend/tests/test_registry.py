from app.llm.registry import _model_info


def test_hubris_item_uses_its_own_fields():
    info = _model_info(
        {
            "id": "google/gemini-image",
            "display_name": "Google: Gemini Image",
            "output_modalities": ["image", "text"],
            "pricing": {"input_rub_per_million": 63.1, "is_free": False},
        }
    )
    assert info.name == "Google: Gemini Image"
    assert info.free is False
    assert info.image is True
    assert info.kind == "image"


def test_free_flag_from_is_free_and_text_kind():
    info = _model_info(
        {
            "id": "x/y",
            "output_modalities": ["text"],
            "pricing": {"is_free": True},
        }
    )
    assert info.free is True
    assert info.kind == "text"


def test_openrouter_style_pricing_still_works():
    paid = _model_info({"id": "a", "pricing": {"prompt": "0.001", "completion": "0.002"}})
    free = _model_info({"id": "b", "pricing": {"prompt": "0", "completion": "0"}})
    assert paid.free is False and free.free is True


def test_audio_and_video_kinds_and_unknown():
    assert _model_info({"id": "a", "output_modalities": ["text", "audio"]}).kind == "other"
    assert _model_info({"id": "v", "output_modalities": ["video"]}).kind == "video"
    assert _model_info({"id": "u"}).kind == "unknown"
