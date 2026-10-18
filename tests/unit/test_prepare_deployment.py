import json
import os
import subprocess
import sys

import pytest

from scripts.prepare_deployment import initialize, store_credentials


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
