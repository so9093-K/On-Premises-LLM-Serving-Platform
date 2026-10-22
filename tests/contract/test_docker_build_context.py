"""실제 Docker 빌드는 중첩 모델 캐시·인증 파일을 포함하지 않는다."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import uuid

import pytest


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_LIFECYCLE_TESTS") != "1",
                    reason="RUN_DOCKER_LIFECYCLE_TESTS=1로 실제 Docker context 검증")
def test_nested_cache_and_credentials_are_excluded_from_build_context(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copy2(root / ".dockerignore", tmp_path / ".dockerignore")
    included = ["src/app.py", "LICENSE", "NOTICE", ".env.compose.example", "ops/images/fixture.txt"]
    excluded = [".env", "ops/compose/.env", "ops/compose/model_cache/weights.bin",
                "nested/models/weights.bin", "nested/.venv/secret.txt", "nested/operator.key",
                "model_cache/weights.bin", "models/weights.bin", ".venv/secret.txt", "operator.key"]
    for filename in included + excluded:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    (tmp_path / "Dockerfile").write_text("FROM scratch\nCOPY . /source\n")
    image = "context-test:" + uuid.uuid4().hex
    container = None

    def run(*args, **kwargs):
        return subprocess.run(["docker", *args], capture_output=True, check=True, timeout=120, **kwargs)

    try:
        run("build", "-t", image, str(tmp_path))
        container = run("create", image, "/unused").stdout.decode().strip()
        archive = run("export", container).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            names = {entry.name for entry in files}
        assert all("source/" + name in names for name in included)
        assert not [name for name in excluded if "source/" + name in names]
    finally:
        if container:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30, check=False)
        subprocess.run(["docker", "image", "rm", image], capture_output=True, timeout=30, check=False)
