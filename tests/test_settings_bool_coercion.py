from src.config.settings import Settings, coerce_bool


def test_coerce_bool_handles_legacy_string_values():
    assert coerce_bool("true", default=False) is True
    assert coerce_bool("false", default=True) is False
    assert coerce_bool("1", default=False) is True
    assert coerce_bool("0", default=True) is False
    assert coerce_bool("", default=True) is False


def test_settings_get_bool_coerces_string_flags():
    settings = Settings.__new__(Settings)
    settings.settings = {"gpt_correction": "false", "offline_queue_enabled": "1"}

    assert settings.get_bool("gpt_correction", True) is False
    assert settings.get_bool("offline_queue_enabled", False) is True

