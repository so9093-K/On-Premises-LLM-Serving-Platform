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


def test_git_metadata_path_permission_failure_preserves_local_execution(tmp_path, monkeypatch):
    fixture_source(tmp_path)
    exists = Path.exists

    def inaccessible_metadata(path):
        if path == tmp_path / ".git":
            raise PermissionError("Git metadata is inaccessible")
        return exists(path)

    monkeypatch.setattr(Path, "exists", inaccessible_metadata)
    source = provenance.read_source_provenance(tmp_path)
    assert (source.revision, source.state) == ("", "local")
    assert source.digest == provenance.source_digest(tmp_path)


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
    labels = {"ai_model_serving.runtime_digest": label_digest, "ai_model_serving.artifact": "platform"}
    monkeypatch.setattr(platform_cli.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(labels), stderr=""))
    monkeypatch.setattr(platform_cli, "runtime_digest", lambda *args: "sha256:matching")
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
         'read_source_provenance; printf "%s\\t%s\\t%s\\t%s\\n" "$SOURCE_REVISION" "$SOURCE_STATE" "$SOURCE_DIGEST" "$SOURCE_RUNTIME_DIGEST"'],
        cwd=tmp_path, env={**os.environ, "PYTHON_BIN": sys.executable, "PATH": str(tools)},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.rstrip("\n").split("\t") == [expected.revision, expected.state, expected.digest, expected.runtime_digest]
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


@pytest.mark.parametrize("artifact", ["platform", "vllm-unified"])
def test_document_edits_and_removal_preserve_runtime_identity(tmp_path, artifact):
    """배포 표기 파일은 출처에 기록하되 로컬 기동의 필수 입력이 아니다."""
    fixture_source(tmp_path)
    initial = provenance.runtime_digest(tmp_path, artifact)
    distribution = provenance.source_digest(tmp_path, artifact)
    for filename in ("LICENSE", "NOTICE", "README.md"):
        path = tmp_path / filename
        path.write_text("distribution text\n")
        assert provenance.runtime_digest(tmp_path, artifact) == initial
    assert provenance.source_digest(tmp_path, artifact) != distribution
    (tmp_path / "LICENSE").write_text("updated license\n")
    (tmp_path / "NOTICE").unlink()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/review.md").write_text("review note\n")
    assert provenance.runtime_digest(tmp_path, artifact) == initial
    (tmp_path / "LICENSE").unlink()
    (tmp_path / "README.md").unlink()
    assert provenance.runtime_digest(tmp_path, artifact) == initial
    assert provenance.source_digest(tmp_path, artifact) == distribution


def test_runtime_identity_does_not_read_distribution_files_or_git(tmp_path, monkeypatch):
    fixture_source(tmp_path)
    (tmp_path / "LICENSE").write_text("license\n")
    (tmp_path / ".git").mkdir()
    original_open = Path.open

    def open_runtime_only(path, *args, **kwargs):
        if path.name in {"LICENSE", "NOTICE", "README.md"}:
            pytest.fail("기동이 배포 문서를 읽었습니다")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_runtime_only)
    monkeypatch.setattr(provenance.subprocess, "run", lambda *args, **kwargs: pytest.fail("Git 조회"))
    assert provenance.runtime_digest(tmp_path).startswith("sha256:")


@pytest.mark.parametrize("path,affected", [
    ("src/app.py", {"platform"}),
    ("src/static/console.js", {"platform"}),
    ("configs/model_serving.yaml", {"platform"}),
    ("specs/schemas/chat.json", {"platform"}),
    ("pyproject.toml", {"platform"}),
    ("uv.lock", {"platform"}),
    ("ops/patches/apply_gemma4_multimodal_patches.py", {"vllm-unified"}),
    ("ops/images/vllm-unified/requirements.media.lock", {"vllm-unified"}),
    ("configs/vllm_unified_build.yaml", {"platform", "vllm-unified"}),
    ("scripts/ops/down_all.sh", set()),
    ("ui/control-plane/src/App.tsx", set()),
])
def test_runtime_changes_invalidate_only_consuming_images(tmp_path, path, affected):
    fixture_source(tmp_path)
    before = {artifact: provenance.runtime_digest(tmp_path, artifact) for artifact in provenance.ARTIFACT_INPUTS}
    file = tmp_path / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("changed runtime input\n")
    changed = {artifact for artifact, digest in before.items()
               if provenance.runtime_digest(tmp_path, artifact) != digest}
    assert changed == affected


@pytest.mark.parametrize("variable,artifact", [
    ("VLLM_BASE_IMAGE", "vllm-unified"), ("PLATFORM_BUILD_PLATFORM", "platform"),
])
def test_build_overrides_are_runtime_inputs(tmp_path, monkeypatch, variable, artifact):
    fixture_source(tmp_path)
    monkeypatch.delenv(variable, raising=False)
    initial = provenance.runtime_digest(tmp_path, artifact)
    monkeypatch.setenv(variable, "different-build-input")
    assert provenance.runtime_digest(tmp_path, artifact) != initial


def test_image_artifact_label_must_match(monkeypatch):
    labels = {"ai_model_serving.artifact": "vllm-unified", "ai_model_serving.runtime_digest": "matching"}
    monkeypatch.setattr(platform_cli.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(labels)))
    monkeypatch.setattr(platform_cli, "runtime_digest", lambda *args: "matching")
    assert not platform_cli._local_image_matches_source("local:image", "platform")


@pytest.mark.parametrize("artifact,dockerfile", [
    ("platform", "Dockerfile"), ("vllm-unified", "ops/images/vllm-unified/Dockerfile"),
])
def test_runtime_manifests_cover_docker_copy_sources(monkeypatch, artifact, dockerfile):
    """COPY 추가에 대응하지 않은 재사용 해시가 오래된 실행 파일을 허용하지 않게 한다."""
    from scripts.validation.governance import vllm_image

    monkeypatch.setattr(vllm_image, "_DOCKERFILE", ROOT / dockerfile)
    assert vllm_image._dockerfile_local_copy_sources() <= set(provenance.input_paths(artifact))
