"""Tests for dskity.validate – ValidationReport, validate_config(), and CLI."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path


from dskity.validate import (
    CheckStatus,
    ValidationReport,
    ValidationResult,
    validate_config,
)


# ── ValidationResult ──────────────────────────────────────────────────────────

def test_validation_result_fields() -> None:
    r = ValidationResult(name="step.one", status=CheckStatus.OK, message="passed")
    assert r.name == "step.one"
    assert r.status == CheckStatus.OK
    assert r.message == "passed"
    assert r.detail == ""


def test_validation_result_with_detail() -> None:
    r = ValidationResult(name="x", status=CheckStatus.ERROR, message="failed", detail="traceback")
    assert r.detail == "traceback"


# ── ValidationReport ──────────────────────────────────────────────────────────

def test_report_starts_empty() -> None:
    report = ValidationReport()
    assert report.results == []
    assert not report.has_errors
    assert not report.has_warnings


def test_report_add() -> None:
    report = ValidationReport()
    report.add("a", CheckStatus.OK, "ok msg")
    assert len(report.results) == 1
    assert report.results[0].status == CheckStatus.OK


def test_report_has_errors() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.ERROR, "error msg")
    assert report.has_errors


def test_report_has_warnings() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.WARNING, "warn msg")
    assert report.has_warnings
    assert not report.has_errors


def test_report_exit_code_zero_when_no_errors() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.OK, "ok")
    assert report.exit_code() == 0


def test_report_exit_code_one_when_errors() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.ERROR, "bad")
    assert report.exit_code() == 1


def test_report_exit_code_uses_parse_exit() -> None:
    report = ValidationReport()
    # Even if no errors in results, parse_exit=2 takes priority
    assert report.exit_code(parse_exit=2) == 2


def test_report_exit_code_parse_exit_zero_falls_back_to_results() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.ERROR, "bad")
    assert report.exit_code(parse_exit=0) == 1


def test_report_summary_format() -> None:
    report = ValidationReport()
    report.add("a", CheckStatus.OK, "")
    report.add("b", CheckStatus.OK, "")
    report.add("c", CheckStatus.WARNING, "")
    report.add("d", CheckStatus.ERROR, "")
    report.add("e", CheckStatus.SKIPPED, "")
    summary = report.summary()
    assert "2 passed" in summary
    assert "1 warnings" in summary
    assert "1 errors" in summary
    assert "1 skipped" in summary


def test_report_warnings_do_not_cause_error_exit() -> None:
    report = ValidationReport()
    report.add("x", CheckStatus.WARNING, "warn")
    assert report.exit_code() == 0
    assert not report.has_errors


# ── validate_config: file not found ──────────────────────────────────────────

def test_validate_config_missing_file_returns_exit_code_2() -> None:
    report, code = validate_config("/nonexistent/path/settings.yaml")
    assert code == 2
    assert report.has_errors
    assert any(r.name == "config.parse" for r in report.results)


# ── validate_config: malformed YAML ──────────────────────────────────────────

def test_validate_config_malformed_yaml_returns_exit_code_2(tmp_path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("key: [unclosed bracket\n")
    report, code = validate_config(str(bad_yaml))
    assert code == 2
    assert report.has_errors


# ── validate_config: valid settings.yaml ─────────────────────────────────────

def _write_minimal_config(path: Path) -> None:
    path.write_text(
        textwrap.dedent("""\
            name: test-service
            modules_search_paths:
              - dskity.modules
            common:
              registry:
                enabled: false
        """)
    )


def test_validate_config_valid_file_exit_zero(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, code = validate_config(str(cfg))
    assert code == 0
    assert not report.has_errors


def test_validate_config_parse_step_ok(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, _ = validate_config(str(cfg))
    parse_result = next(r for r in report.results if r.name == "config.parse")
    assert parse_result.status == CheckStatus.OK


def test_validate_config_settings_step_ok(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, _ = validate_config(str(cfg))
    settings_result = next((r for r in report.results if r.name == "config.settings"), None)
    assert settings_result is not None
    assert settings_result.status == CheckStatus.OK


# ── validate_config: module discovery ────────────────────────────────────────

def test_validate_config_module_discovery_step_present(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, _ = validate_config(str(cfg))
    # At minimum, should have a modules.discovery result
    names = [r.name for r in report.results]
    assert any("modules" in n for n in names)


def test_validate_config_module_discovery_warns_for_unknown_package(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(
        textwrap.dedent("""\
            name: svc
            modules_import_path: nonexistent.modules.package
        """)
    )
    report, code = validate_config(str(cfg))
    # Should not crash, may warn about missing package
    assert code in (0, 1)


# ── validate_config: strict mode ─────────────────────────────────────────────

def test_validate_config_strict_adds_kv_check(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, _ = validate_config(str(cfg), strict=True)
    names = [r.name for r in report.results]
    assert "kv.connectivity" in names


def test_validate_config_non_strict_no_kv_check(tmp_path) -> None:
    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)
    report, _ = validate_config(str(cfg), strict=False)
    names = [r.name for r in report.results]
    assert "kv.connectivity" not in names


# ── CLI: dskity validate ──────────────────────────────────────────────────────

def test_cli_validate_command_exit_zero(tmp_path) -> None:
    from dskity.cli import main

    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)

    code = main(["validate", "--config", str(cfg)])
    assert code == 0


def test_cli_validate_command_missing_file_exit_nonzero() -> None:
    from dskity.cli import main

    code = main(["validate", "--config", "/nonexistent/settings.yaml"])
    assert code != 0


def test_cli_validate_json_output(tmp_path, capsys) -> None:
    from dskity.cli import main

    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)

    main(["validate", "--config", str(cfg), "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "results" in data
    assert "summary" in data
    assert isinstance(data["results"], list)


def test_cli_validate_text_output_contains_summary(tmp_path, capsys) -> None:
    from dskity.cli import main

    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)

    main(["validate", "--config", str(cfg)])
    captured = capsys.readouterr()
    assert "Summary:" in captured.out
    assert "passed" in captured.out


def test_cli_validate_strict_flag_accepted(tmp_path) -> None:
    from dskity.cli import main

    cfg = tmp_path / "settings.yaml"
    _write_minimal_config(cfg)

    # Should not raise; kv connectivity may warn or fail, but shouldn't crash
    code = main(["validate", "--config", str(cfg), "--strict"])
    assert isinstance(code, int)
