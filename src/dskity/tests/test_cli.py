from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "argv",
    [["-p", "8080"], ["run", "-p", "8080"], ["-p", "8080", "run"]],
)
def test_main_parses_run_port_without_subcommand(tmp_path, monkeypatch, argv) -> None:
    from dskity.cli import main

    config_path = tmp_path / "settings.yaml"
    config_path.write_text("reload: false\n", encoding="utf-8")

    calls: dict[str, object] = {}

    monkeypatch.setenv("DSKITY_ENV", "production")
    monkeypatch.setattr("dskity.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("dskity.cli.resolve_config_path", lambda _: str(config_path))
    monkeypatch.setattr("dskity.cli._read_config_file", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("dskity.cli.configure_logging", lambda **_kwargs: {})

    def fake_run(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr("dskity.cli.uvicorn.run", fake_run)

    code = main(argv)

    assert code == 0
    assert calls["args"] == ("dskity.app:app",)
    assert calls["kwargs"]["port"] == 8080
    assert calls["kwargs"]["host"] == "0.0.0.0"
    assert calls["kwargs"]["reload"] is False
