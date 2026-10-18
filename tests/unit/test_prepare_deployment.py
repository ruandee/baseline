import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from scripts.prepare_deployment import ensure_runner_profile, initialize, store_credentials
from scripts.seed import uid


def test_initialize_is_private_unique_and_never_overwrites_existing_configuration(tmp_path):
    path = tmp_path / ".env.demo"
    initialize(path, "Demo.Example.Org")
    original = path.read_text()
    assert "PM_FRONTEND_HOSTS=demo.example.org" in original
    secret = next(line.split("=", 1)[1] for line in original.splitlines()
                  if line.startswith("PM_JWT_SECRET="))
    assert len(secret) == 64
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        initialize(path, "other.example.org")
    assert path.read_text() == original
    other = tmp_path / "other.env"
    initialize(other, "demo.example.org")
    assert secret not in other.read_text()


@pytest.mark.parametrize("hostname", ["https://demo.example.org", "demo.example.org:443",
                                      "*.example.org", "a..b", "a.-b.com", "a.b-.com", "a\nPM_PROVIDER=compatible"])
def test_hostname_cannot_inject_environment_settings(tmp_path, hostname):
    path = tmp_path / ".env.demo"
    with pytest.raises(ValueError):
        initialize(path, hostname)
    assert not path.exists()


def test_credentials_require_both_roles_and_do_not_echo_or_replace_signing_secret(tmp_path):
    path = tmp_path / ".env.demo"
    initialize(path, "demo.example.org")
    before = path.read_text()
    with pytest.raises(ValueError):
        store_credentials(path, {"nurse": "aaa.bbb.ccc"})
    assert path.read_text() == before
    tokens = {"nurse": "aaa.bbb.ccc", "psw": "ddd.eee.fff"}
    result = subprocess.run([sys.executable, "-m", "scripts.prepare_deployment", "--env-file",
                             str(path), "credentials"], input=json.dumps(tokens), text=True,
                            capture_output=True, check=True)
    assert all(token not in result.stdout + result.stderr for token in tokens.values())
    assert "PM_DEMO_TOKEN=aaa.bbb.ccc" in path.read_text()
    assert "PM_DEMO_PSW_TOKEN=ddd.eee.fff" in path.read_text()
    secret_line = next(line for line in before.splitlines() if line.startswith("PM_JWT_SECRET="))
    assert secret_line in path.read_text()


def test_invalid_token_does_not_corrupt_config_or_leak_input(tmp_path):
    path = tmp_path / ".env.demo"
    initialize(path, "demo.example.org")
    before = path.read_text()
    supplied = "private-invalid-token\nPM_PROVIDER=compatible"
    result = subprocess.run([sys.executable, "-m", "scripts.prepare_deployment", "--env-file",
                             str(path), "credentials"],
                            input=json.dumps({"nurse": supplied, "psw": "ddd.eee.fff"}),
                            text=True, capture_output=True)
    assert result.returncode == 1
    assert supplied not in result.stdout + result.stderr
    assert path.read_text() == before


@pytest.mark.parametrize("existing", [None, "", "others", "runner"])
def test_runner_profile_preserves_valid_existing_profiles_and_is_idempotent(tmp_path, existing):
    path = tmp_path / ".env.demo"
    other = str(uuid4())
    runner = str(uid("0/runner-capture"))
    original = "PM_JWT_SECRET=do-not-echo\nPM_DEMO_TOKEN=aaa.bbb.ccc\n"
    if existing is not None:
        original += "PM_NO_ESCALATE_PATIENTS=" + {
            "": "", "others": other, "runner": f"{other},{runner}"}[existing] + "\n"
    path.write_text(original)
    ensure_runner_profile(path)
    first = path.read_text()
    ensure_runner_profile(path)
    assert path.read_text() == first
    values = dict(line.split("=", 1) for line in first.splitlines())
    assert values["PM_JWT_SECRET"] == "do-not-echo"
    assert values["PM_DEMO_TOKEN"] == "aaa.bbb.ccc"
    assert values["PM_NO_ESCALATE_PATIENTS"].split(",") == (
        [other, runner] if existing in ("others", "runner") else [runner])
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("line", [
    "PM_NO_ESCALATE_PATIENTS=not-a-uuid",
    "PM_NO_ESCALATE_PATIENTS=21926d8c-0847-53df-a9b1-96fbcf21e43c,",
    "PM_NO_ESCALATE_PATIENTS=21926d8c-0847-53df-a9b1-96fbcf21e43c,21926d8c-0847-53df-a9b1-96fbcf21e43c",
    "PM_NO_ESCALATE_PATIENTS=\nPM_NO_ESCALATE_PATIENTS=",
    "PM_PROVIDER=stub\nPM_PROVIDER=compatible",
    "PM_NO_ESCALATE_PATIENTS",
    "export PM_NO_ESCALATE_PATIENTS=",
])
def test_runner_profile_rejects_malformed_or_duplicate_configuration_without_changes(tmp_path, line):
    path = tmp_path / ".env.demo"
    original = "PM_JWT_SECRET=private-secret\n" + line + "\n"
    path.write_text(original)
    with pytest.raises(ValueError):
        ensure_runner_profile(path)
    assert path.read_text() == original
    assert list(tmp_path.glob(".demo-env-*")) == []


def test_runner_profile_rejects_symlink_without_modifying_its_target(tmp_path):
    target, link = tmp_path / "private.env", tmp_path / ".env.demo"
    target.write_text("PM_NO_ESCALATE_PATIENTS=\n")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this platform")
    with pytest.raises(ValueError):
        ensure_runner_profile(link)
    assert target.read_text() == "PM_NO_ESCALATE_PATIENTS=\n"


def test_runner_profile_failed_atomic_replace_preserves_private_configuration(tmp_path, monkeypatch):
    import scripts.prepare_deployment as prepare

    path = tmp_path / ".env.demo"
    original = "PM_JWT_SECRET=preserve-secret\nPM_NO_ESCALATE_PATIENTS=\n"
    path.write_text(original)

    def fail_replace(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(prepare.os, "replace", fail_replace)
    with pytest.raises(OSError):
        ensure_runner_profile(path)
    assert path.read_text() == original
    assert list(tmp_path.glob(".demo-env-*")) == []


def test_runner_profile_cli_prints_no_credentials_and_wrapper_runs_it_before_startup(tmp_path):
    from pathlib import Path

    path = tmp_path / ".env.demo"
    path.write_text("PM_JWT_SECRET=secret-runner-test\nPM_DEMO_TOKEN=aaa.bbb.ccc\n")
    result = subprocess.run([sys.executable, "-S", "-m", "scripts.prepare_deployment", "--env-file",
                             str(path), "runner-profile"], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "secret-runner-test" not in result.stdout + result.stderr
    assert "aaa.bbb.ccc" not in result.stdout + result.stderr
    wrapper = (Path(__file__).resolve().parents[2] / "deploy/reset-demo.sh").read_text()
    assert wrapper.index("scripts.prepare_deployment runner-profile") < wrapper.index('"${C[@]}" stop')
