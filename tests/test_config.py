from pathlib import Path

import pytest

from snapanswer.config import (
    Config,
    ConfigError,
    apply_deepseek_defaults,
    config_from_dict,
    is_local_endpoint,
    load_config,
    normalize_config,
    resolve_api_key,
    save_config,
    validate_config,
)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = Config()
    cfg.llm.model = "test-model"
    cfg.llm.api_key_env = "MY_TEST_KEY"
    cfg.app.opacity = 0.8
    cfg.app.highlight_region = True
    cfg.llm.request_usage = False
    cfg.usage.show_panel = True
    cfg.usage.input_per_million = 0.5
    cfg.usage.currency = "USD"
    cfg.usage.off_peak_enabled = True
    cfg.usage.display_mode = "card"
    cfg.usage.peak_start = "22:00"
    cfg.usage.peak_end = "08:00"
    cfg.usage.lunch_break_enabled = False
    cfg.usage.peak_weekdays = [1, 5]
    cfg.usage.off_peak_dates = ["2026-10-01"]
    cfg.usage.off_peak_input_per_million = 0.1
    path = tmp_path / "config.toml"
    save_config(cfg, path)

    loaded, loaded_path = load_config(path)
    assert loaded_path == path
    assert loaded.llm.model == "test-model"
    assert loaded.llm.api_key_env == "MY_TEST_KEY"
    assert loaded.app.opacity == pytest.approx(0.8)
    assert loaded.app.verify_after_answer is True
    assert loaded.app.verify_delay_sec == pytest.approx(1.2)
    assert loaded.app.verify_similarity == pytest.approx(0.95)
    assert loaded.app.highlight_region is True
    assert loaded.llm.request_usage is False
    assert loaded.usage.show_panel is True
    assert loaded.usage.input_per_million == pytest.approx(0.5)
    assert loaded.usage.currency == "USD"
    assert loaded.usage.off_peak_enabled is True
    assert loaded.usage.display_mode == "card"
    assert loaded.usage.peak_start == "22:00"
    assert loaded.usage.peak_end == "08:00"
    assert loaded.usage.lunch_break_enabled is False
    assert loaded.usage.peak_weekdays == [1, 5]
    assert loaded.usage.off_peak_dates == ["2026-10-01"]
    assert loaded.usage.off_peak_input_per_million == pytest.approx(0.1)
    assert loaded.llm.system_prompt.startswith("你是一位")


def test_deepseek_defaults() -> None:
    cfg = Config()
    assert cfg.llm.model == "deepseek-flash"
    assert cfg.usage.off_peak_enabled is True
    assert cfg.usage.input_per_million == pytest.approx(2.0)
    assert cfg.usage.output_per_million == pytest.approx(8.0)
    assert cfg.usage.off_peak_input_per_million == pytest.approx(1.0)
    assert cfg.usage.off_peak_output_per_million == pytest.approx(4.0)
    assert cfg.usage.peak_start == "09:00"
    assert cfg.usage.peak_end == "18:00"
    assert cfg.usage.peak_weekdays == [1, 2, 3, 4, 5]


def test_legacy_deepseek_zero_prices_get_defaults() -> None:
    cfg = Config()
    cfg.usage.input_per_million = 0.0
    cfg.usage.output_per_million = 0.0
    cfg.usage.off_peak_enabled = False
    assert apply_deepseek_defaults(cfg) is True
    assert cfg.usage.input_per_million == 2.0
    assert cfg.usage.off_peak_enabled is True

    cfg.usage.input_per_million = 0.8
    assert apply_deepseek_defaults(cfg) is False
    assert cfg.usage.input_per_million == 0.8


def test_legacy_config_is_migrated_on_load(tmp_path: Path) -> None:
    cfg = Config()
    cfg.usage.input_per_million = 0.0
    cfg.usage.output_per_million = 0.0
    cfg.usage.off_peak_enabled = False
    path = tmp_path / "legacy.toml"
    save_config(cfg, path)
    loaded, _ = load_config(path)
    assert loaded.usage.input_per_million == 2.0
    assert loaded.usage.off_peak_output_per_million == 4.0
    assert loaded.usage.off_peak_enabled is True


def test_missing_config_is_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    cfg, loaded_path = load_config(path)
    assert path.exists()
    assert loaded_path == path
    assert isinstance(cfg, Config)


def test_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPANSWER_API_KEY", raising=False)
    monkeypatch.setenv("MY_TEST_KEY", "sk-from-env")
    cfg = Config()
    cfg.llm.api_key = ""
    cfg.llm.api_key_env = "MY_TEST_KEY"
    assert resolve_api_key(cfg) == "sk-from-env"

    cfg.llm.api_key = "sk-direct"
    assert resolve_api_key(cfg) == "sk-direct"


def test_invalid_value_raises() -> None:
    with pytest.raises(ConfigError):
        config_from_dict({"llm": {"temperature": "hot"}})
    with pytest.raises(ConfigError):
        config_from_dict({"app": []})
    with pytest.raises(ConfigError):
        config_from_dict({"usage": {"peak_start": "25:00"}})


def test_normalize_clamps() -> None:
    cfg = Config()
    cfg.app.opacity = 5
    cfg.app.continuous_interval_sec = 0.01
    cfg.app.verify_delay_sec = 0.0
    cfg.app.verify_similarity = 2.0
    cfg.llm.temperature = -3
    cfg.llm.max_tokens = 1
    normalize_config(cfg)
    assert cfg.app.opacity == 1.0
    assert cfg.app.continuous_interval_sec == 0.8
    assert cfg.app.verify_delay_sec == 0.2
    assert cfg.app.verify_similarity == 1.0
    assert cfg.llm.temperature == 0.0
    assert cfg.llm.max_tokens == 64


def test_local_endpoint_detection() -> None:
    assert is_local_endpoint("http://127.0.0.1:11434/v1")
    assert is_local_endpoint("http://localhost:1234/v1")
    assert is_local_endpoint("http://192.168.1.9:8000/v1")
    assert not is_local_endpoint("https://api.deepseek.com/v1")


def test_validation_reports_bad_url_and_empty_model() -> None:
    cfg = Config()
    cfg.llm.base_url = "not a url"
    cfg.llm.model = " "
    issues = validate_config(cfg)
    assert len(issues) >= 2


def test_unknown_keys_are_ignored() -> None:
    cfg = config_from_dict({"llm": {"model": "m", "unknown": 1}})
    assert cfg.llm.model == "m"
