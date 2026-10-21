"""Opt-in real Docker upgrade: preserve a legacy volume's data and identity."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import pytest

from scripts.compose.preserve_volumes import preserve_volumes
from scripts.ops.compose_ownership import CHECKOUT_LABEL


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_LIFECYCLE_TESTS") != "1",
                    reason="Set RUN_DOCKER_LIFECYCLE_TESTS=1 on a Docker host")
def test_legacy_volume_survives_label_change_and_repeated_down_up():
    project = f"volume-reuse-test-{uuid.uuid4().hex[:12]}"
    image = os.environ.get("VOLUME_REUSE_TEST_IMAGE", "ai-model-serving-platform:0.0.1")
    volume = f"{project}_cache"

    def run(*args):
        return subprocess.run(["docker", *args], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=45, check=True).stdout

    with tempfile.TemporaryDirectory(prefix="volume-reuse-test-") as directory:
        root = Path(directory)
        source = root / "ops/compose/compose.json"
        source.parent.mkdir(parents=True)
        config = {"services": {"check": {
            "image": image, "user": "0:0", "entrypoint": ["python", "-c"],
            "command": ["from pathlib import Path; Path('/cache/sentinel').write_text('keep-me')"],
            "volumes": ["cache:/cache"],
        }}, "volumes": {"cache": {}}}
        command = ["compose", "--project-name", project, "-f", str(source)]
        try:
            source.write_text(json.dumps(config))
            run(*command, "up", "--abort-on-container-exit", "--exit-code-from", "check")
            before = json.loads(run("volume", "inspect", volume))[0]

            config["volumes"]["cache"] = {"labels": {CHECKOUT_LABEL: str(root)}}
            config["services"]["check"]["command"] = [
                "from pathlib import Path; assert Path('/cache/sentinel').read_text() == 'keep-me'"
            ]
            source.write_text(json.dumps(config))
            effective = json.loads(run(*command, "config", "--format", "json"))
            override = preserve_volumes(root, project, effective)
            protected = [*command, "-f", str(override)]
            run(*protected, "up", "--abort-on-container-exit", "--exit-code-from", "check", "--force-recreate")
            run(*protected, "down")
            # No container remains to prove ownership; the manifest must suffice.
            preserve_volumes(root, project, effective)
            run(*protected, "up", "--abort-on-container-exit", "--exit-code-from", "check")
            after = json.loads(run("volume", "inspect", volume))[0]
            assert before == after
        finally:
            # Only the unique project and volume created by this test are removed.
            run(*command, "down")
            run("volume", "rm", volume)
