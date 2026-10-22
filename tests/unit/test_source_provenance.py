"""Git 없이도 소스 변경을 감지하고 검증한 로컬 이미지만 재사용한다."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import platform_cli
from scripts.lib import source_provenance as provenance

ROOT = Path(__file__).resolve().parents[2]


def fixture_source(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text("COPY src /app/src\n")
    (root / "src/app.py").write_text("print('hello')\n")


@pytest.mark.parametrize("git_failure", ["missing", "ownership", "status", "timeout"])
def test_git_failure_leaves_content_identity_available(tmp_path, monkeypatch, git_failure):
    fixture_source(tmp_path)
    (tmp_path / ".git").mkdir()

    def git(*args, **kwargs):
        command = args[0]
        if git_failure == "missing":
            raise FileNotFoundError("git")
        if git_failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if git_failure == "ownership" or command[1] == "status":
            return subprocess.CompletedProcess(command, 128, stdout="", stderr="fatal: dubious ownership")
        return subprocess.CompletedProcess(command, 0, stdout="a" * 40 + "\n", stderr="")

    monkeypatch.setattr(provenance.subprocess, "run", git)
    source = provenance.read_source_provenance(tmp_path)
    assert (source.revision, source.state) == ("", "local")
    assert source.digest == provenance.source_digest(tmp_path)


def test_archive_identity_ignores_git_secrets_caches_and_install_location(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    fixture_source(first)
    shutil.copytree(first, second)
    initial = provenance.source_digest(first)
    (first / ".env").write_text("API_KEY=private\n")
    (first / "model_cache").mkdir()
    (first / "model_cache/model.bin").write_bytes(b"model data")
    (first / "src/__pycache__").mkdir()
    (first / "src/__pycache__/app.pyc").write_bytes(b"bytecode")
    (first / "src/local.secret").write_text("private\n")
    monkeypatch.setattr(provenance.subprocess, "run", lambda *args, **kwargs: pytest.fail("archive invoked Git"))
    assert provenance.read_source_provenance(first).digest == initial == provenance.source_digest(second)
    assert provenance.read_source_provenance(first).state == "local"


def test_identity_changes_with_file_content_addition_deletion_and_executable_mode(tmp_path):
    fixture_source(tmp_path)
    path = tmp_path / "src/app.py"
    initial = provenance.source_digest(tmp_path)
    path.write_text("print('changed')\n")
    assert provenance.source_digest(tmp_path) != initial
    path.write_text("print('hello')\n")
    assert provenance.source_digest(tmp_path) == initial
    path.chmod(path.stat().st_mode | 0o111)
    assert provenance.source_digest(tmp_path) != initial
    path.chmod(path.stat().st_mode & ~0o111)
    extra = tmp_path / "src/new.py"
    extra.write_text("print('new')\n")
    assert provenance.source_digest(tmp_path) != initial
    extra.unlink()
    assert provenance.source_digest(tmp_path) == initial
    path.unlink()
    assert provenance.source_digest(tmp_path) != initial


@pytest.mark.parametrize("label_digest", [None, "sha256:stale", "sha256:matching"])
def test_local_source_reuses_only_matching_content(monkeypatch, label_digest):
    labels = {"ai_model_serving.source_digest": label_digest}
    monkeypatch.setattr(platform_cli.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(labels), stderr=""))
    monkeypatch.setattr(platform_cli, "_source_provenance", lambda:
                        provenance.SourceProvenance("", "local", "sha256:matching"))
    assert platform_cli._local_image_matches_source("local:image") is (label_digest == "sha256:matching")


def test_bash_and_python_share_content_identity_without_a_git_binary(tmp_path):
    fixture_source(tmp_path)
    library = tmp_path / "scripts/lib"
    library.mkdir(parents=True)
    for name in ("source_provenance.sh", "source_provenance.py"):
        shutil.copy2(ROOT / "scripts/lib" / name, library / name)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("dirname",):
        (tools / name).symlink_to(shutil.which(name))
    expected = provenance.read_source_provenance(tmp_path)
    result = subprocess.run(
        [shutil.which("bash"), "-c", 'set -euo pipefail; source scripts/lib/source_provenance.sh; '
         'read_source_provenance; printf "%s\\t%s\\t%s\\n" "$SOURCE_REVISION" "$SOURCE_STATE" "$SOURCE_DIGEST"'],
        cwd=tmp_path, env={**os.environ, "PYTHON_BIN": sys.executable, "PATH": str(tools)},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.rstrip("\n").split("\t") == [expected.revision, expected.state, expected.digest]
    assert result.stderr == ""


def test_invalid_build_input_reports_a_short_actionable_error(tmp_path, monkeypatch, capsys):
    fixture_source(tmp_path)
    os.mkfifo(tmp_path / "src/not-a-source-file")
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    assert provenance.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "소스 파일 확인 실패" in output.err
    assert "파일 형식과 읽기 권한" in output.err
    assert "Traceback" not in output.err
