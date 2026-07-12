"""Tests for the clearancekit CLI."""

from unittest.mock import MagicMock, patch

from clearancekit.cli import build_parser, cmd_selftest


def test_build_parser_subcommands():
    p = build_parser()
    args = p.parse_args(["selftest"])
    assert args.command == "selftest"
    args = p.parse_args(["test", "https://x.com"])
    assert args.command == "test" and args.url == "https://x.com"
    args = p.parse_args(["shell", "--warmup", "https://x.com"])
    assert args.command == "shell" and args.warmup == "https://x.com"


def test_selftest_reports_missing_deps(capsys):
    mock_run_result = MagicMock(returncode=1)
    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run", return_value=mock_run_result),
    ):
        rc = cmd_selftest(MagicMock())
    out = capsys.readouterr().out
    assert "chromium" in out.lower() or "missing" in out.lower()
    assert rc != 0


def test_selftest_reports_ok_when_all_present(capsys):
    mock_run_result = MagicMock(returncode=0)
    with (
        patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"),
        patch("subprocess.run", return_value=mock_run_result),
    ):
        rc = cmd_selftest(MagicMock())
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok" in out.lower() or "ready" in out.lower()
