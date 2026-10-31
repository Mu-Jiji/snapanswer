from pathlib import Path

from snapanswer import config as config_module


def test_fallback_config_is_reused_when_user_dir_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    fallback = tmp_path / "fallback" / "config.toml"
    monkeypatch.setattr(
        config_module, "resolve_config_path", lambda explicit=None: blocker / "config.toml"
    )
    monkeypatch.setattr(config_module, "fallback_config_path", lambda: fallback)

    cfg, path = config_module.load_config()
    assert path == fallback
    assert fallback.exists()

    cfg.llm.model = "fallback-model"
    config_module.save_config(cfg, fallback)

    loaded, loaded_path = config_module.load_config()
    assert loaded_path == fallback
    assert loaded.llm.model == "fallback-model"
