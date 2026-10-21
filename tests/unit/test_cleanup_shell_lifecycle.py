"""Run real cleanup scripts in disposable checkouts with fake Docker/launchd boundaries."""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "repo"
    for relative in (
        "scripts/ops/down_all.sh", "scripts/ops/down_services.sh", "scripts/ops/reset_all.sh",
        "scripts/ops/purge_all.sh", "scripts/ops/clean_project.sh", "scripts/ops/compose_ownership.py",
        "scripts/runtime/macos_mlx_runtime.py", "Makefile", "VERSION",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (root / ".env").write_text("BUILD_PROFILE=local\n")
    (root / ".venv").mkdir()
    (root / ".venv/keep").write_text("environment")
    (root / ".runtime").mkdir()
    (root / ".runtime/keep").write_text("runtime")
    agent_home = tmp_path / "user"
    installed = agent_home / "Library/LaunchAgents/com.ai-model-serving.metal.plist"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(plistlib.dumps({
        "Label": "com.ai-model-serving.metal",
        "WorkingDirectory": str(root / ".runtime/metal/models"),
    }))
    state = tmp_path / "launchd.json"
    state.write_text(json.dumps({"loaded": True, "calls": []}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def executable(name, source):
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)
        return path

    runner = executable("python-emergency", '''import os, sys
os.execv(sys.executable, [sys.executable, "-S", "-c", ''' + repr('''import os, pathlib, platform, runpy, sys
pathlib.Path.home = classmethod(lambda cls: pathlib.Path(os.environ["TEST_AGENT_HOME"]))
platform.system = lambda: "Darwin"
sys.argv = sys.argv[1:]
if sys.argv[-1] == "uninstall-supervisor" and os.environ.get("TEST_UNINSTALL_FAIL"):
    raise SystemExit(2)
runpy.run_path(sys.argv[0], run_name="__main__")
''') + ''', *sys.argv[1:]])
''')
    executable("uname", 'print("Darwin")\n')
    executable("launchctl", '''import json, os, pathlib, sys
path = pathlib.Path(os.environ["TEST_LAUNCHD_STATE"])
state = json.loads(path.read_text())
state["calls"].append(sys.argv[1:])
path.write_text(json.dumps(state))
if sys.argv[1] == "print":
    if state["loaded"]: raise SystemExit(0)
    print("Could not find service", file=sys.stderr)
    raise SystemExit(113)
if sys.argv[1] == "bootout":
    if os.environ.get("TEST_BOOTOUT_FAIL"): raise SystemExit(1)
    state["loaded"] = False
    path.write_text(json.dumps(state))
''')
    executable("docker", '''import os, sys
if sys.argv[1] == "info" and os.environ.get("TEST_DOCKER_FAIL"):
    raise SystemExit(1)
''')
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "PYTHON_BIN": str(runner), "TEST_AGENT_HOME": str(agent_home),
           "TEST_LAUNCHD_STATE": str(state)}
    return root, installed, state, env


@pytest.mark.parametrize("failure", ["TEST_BOOTOUT_FAIL", "TEST_UNINSTALL_FAIL"])
def test_reset_aborts_before_deleting_state_when_native_shutdown_fails(checkout, failure):
    root, installed, state, env = checkout
    result = subprocess.run(["bash", "scripts/ops/reset_all.sh", "--confirm", "reset"],
                            cwd=root, env={**env, failure: "1"}, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert installed.exists()
    assert (root / ".env").exists()
    assert (root / ".venv/keep").exists()
    assert (root / ".runtime/keep").exists()


@pytest.mark.parametrize("venv_exists", [False, True])
def test_emergency_make_down_stops_launchd_without_env_or_dependencies(checkout, venv_exists):
    root, installed, state, env = checkout
    (root / ".env").unlink()
    if venv_exists:
        (root / ".venv/bin").mkdir()
        (root / ".venv/bin/python").symlink_to(env["PYTHON_BIN"])
    else:
        shutil.rmtree(root / ".venv")
    result = subprocess.run(["make", "down"], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(state.read_text())["loaded"] is False
    assert installed.exists()  # ordinary down preserves installation for the next start


def test_app_only_reset_accepts_absent_supervisor_without_docker(checkout):
    root, installed, state, env = checkout
    installed.unlink()
    state.write_text(json.dumps({"loaded": False, "calls": []}))
    result = subprocess.run(["bash", "scripts/ops/reset_all.sh", "--confirm", "reset"],
                            cwd=root, env={**env, "TEST_DOCKER_FAIL": "1"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / ".env").exists()
    assert not (root / ".venv").exists()
    assert not (root / ".runtime").exists()


def test_reset_uninstalls_owned_supervisor_before_removing_environment(checkout):
    root, installed, state, env = checkout
    result = subprocess.run(["bash", "scripts/ops/reset_all.sh", "--confirm", "reset"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not installed.exists()
    assert json.loads(state.read_text())["loaded"] is False
    assert not (root / ".venv").exists()
    assert not (root / ".runtime").exists()


def test_reset_preserves_other_checkouts_supervisor_including_shared_path_prefix(checkout):
    root, installed, state, env = checkout
    installed.write_bytes(plistlib.dumps({
        "Label": "com.ai-model-serving.metal",
        "WorkingDirectory": str(root.with_name("repo-backup") / ".runtime/metal/models"),
    }))
    result = subprocess.run(["bash", "scripts/ops/reset_all.sh", "--confirm", "reset"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert installed.exists()
    assert json.loads(state.read_text()) == {"loaded": True, "calls": []}


def test_purge_plan_does_not_stop_processes_or_delete_files(checkout):
    root, installed, state, env = checkout
    result = subprocess.run(["bash", "scripts/ops/purge_all.sh", "--scope", "all"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Nothing has been removed" in result.stdout
    assert json.loads(state.read_text()) == {"loaded": True, "calls": []}
    assert (root / ".runtime/keep").exists()
