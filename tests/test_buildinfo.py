import subprocess

import pytest

from inkflow import buildinfo


# ---- format_build_time -------------------------------------------------


def test_format_build_time_formats_utc_iso_string():
    assert buildinfo.format_build_time("2026-08-10T16:32:00+00:00") == "2026-08-10 16:32 UTC"


def test_format_build_time_handles_seconds_precision():
    assert buildinfo.format_build_time("2026-01-05T09:03:45+00:00") == "2026-01-05 09:03 UTC"


def test_format_build_time_returns_input_when_unparseable():
    assert buildinfo.format_build_time("not-a-date") == "not-a-date"


# ---- _run_git ------------------------------------------------------------


def test_run_git_returns_stripped_stdout_on_success(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=b"abc1234\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert buildinfo._run_git(["rev-parse", "--short", "HEAD"]) == "abc1234"


def test_run_git_returns_none_on_nonzero_exit(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 128, stdout=b"", stderr=b"fatal")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert buildinfo._run_git(["status"]) is None


def test_run_git_returns_none_when_git_missing(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert buildinfo._run_git(["status"]) is None


def test_run_git_returns_none_on_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert buildinfo._run_git(["status"]) is None


# ---- ソース実行時（FROZEN=False） ----------------------------------------


def test_source_commit_uses_git_when_not_frozen(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: "deadbee")
    assert buildinfo.source_commit() == "deadbee"


def test_source_commit_returns_none_when_git_unavailable(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: None)
    assert buildinfo.source_commit() is None


def test_source_dirty_true_when_status_nonempty(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: " M inkflow/cli.py")
    assert buildinfo.source_dirty() is True


def test_source_dirty_false_when_status_empty(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: "")
    assert buildinfo.source_dirty() is False


def test_source_dirty_none_when_git_unavailable(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: None)
    assert buildinfo.source_dirty() is None


def test_build_time_is_none_when_not_frozen(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "BUILD_TIME", None)
    assert buildinfo.build_time() is None


# ---- パッケージ版（FROZEN=True） ------------------------------------------


def test_source_commit_uses_embedded_value_when_frozen(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", True)
    monkeypatch.setattr(buildinfo, "BUILD_COMMIT", "554c82e")
    assert buildinfo.source_commit() == "554c82e"


def test_source_dirty_uses_embedded_value_when_frozen(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", True)
    monkeypatch.setattr(buildinfo, "BUILD_DIRTY", True)
    assert buildinfo.source_dirty() is True


def test_frozen_does_not_call_git(monkeypatch):
    """フリーズ時はgitを一切呼ばない（同梱されていないため）。"""

    def boom(args):
        raise AssertionError("フリーズ時に git を呼んではいけない")

    monkeypatch.setattr(buildinfo, "FROZEN", True)
    monkeypatch.setattr(buildinfo, "BUILD_COMMIT", "abc")
    monkeypatch.setattr(buildinfo, "BUILD_DIRTY", False)
    monkeypatch.setattr(buildinfo, "_run_git", boom)
    assert buildinfo.source_commit() == "abc"
    assert buildinfo.source_dirty() is False


def test_build_time_returns_embedded_value_when_frozen(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", True)
    monkeypatch.setattr(buildinfo, "BUILD_TIME", "2026-08-10T16:32:00+00:00")
    assert buildinfo.build_time() == "2026-08-10T16:32:00+00:00"


# ---- describe() ------------------------------------------------------


def test_describe_source_run_clean_tree(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: "" if args[0] == "status" else "554c82e")
    text = buildinfo.describe()
    assert "InkFlow" in text
    assert "ソース: 554c82e" in text
    assert "未コミット" not in text
    assert "ビルド: ソース実行" in text


def test_describe_source_run_dirty_tree(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(
        buildinfo, "_run_git", lambda args: " M x.py" if args[0] == "status" else "554c82e"
    )
    assert "ソース: 554c82e（未コミットの変更あり）" in buildinfo.describe()


def test_describe_git_unavailable(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", False)
    monkeypatch.setattr(buildinfo, "_run_git", lambda args: None)
    text = buildinfo.describe()
    assert "ソース: 不明" in text
    assert "ビルド: ソース実行" in text


def test_describe_frozen_build(monkeypatch):
    monkeypatch.setattr(buildinfo, "FROZEN", True)
    monkeypatch.setattr(buildinfo, "BUILD_COMMIT", "554c82e")
    monkeypatch.setattr(buildinfo, "BUILD_DIRTY", False)
    monkeypatch.setattr(buildinfo, "BUILD_TIME", "2026-08-10T16:32:00+00:00")
    text = buildinfo.describe()
    assert "ソース: 554c82e" in text
    assert "未コミット" not in text
    assert "ビルド: 2026-08-10 16:32 UTC" in text


def test_describe_includes_version():
    from inkflow import __version__

    assert __version__ in buildinfo.describe()


def test_frozen_reflects_sys_frozen_attribute():
    """モジュール読み込み時、通常のテスト実行では FROZEN は False。"""
    assert buildinfo.FROZEN is False
