import paperus_ml  # noqa: F401  (switches telemetry off)


def test_no_hugging_face_telemetry() -> None:
    from huggingface_hub import constants

    assert constants.HF_HUB_DISABLE_TELEMETRY
