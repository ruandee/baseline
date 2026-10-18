"""Execute the actual reset wrapper against offline shell fakes, never Docker/data."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))


def shell_path(path):
    value = path.as_posix()
    return "/" + value[0].lower() + value[2:] if os.name == "nt" else value


@pytest.fixture
def wrapper(tmp_path):
    if not BASH or not Path(BASH).exists():
        pytest.skip("Bash unavailable; Linux CI executes the shell regression")
    (tmp_path / "deploy").mkdir()
    shutil.copyfile(ROOT / "deploy/reset-demo.sh", tmp_path / "deploy/reset-demo.sh")
    (tmp_path / ".env.demo").write_text("PM_DEMO_DOMAIN=synthetic.invalid\n")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    scripts = {
        "python3": '''#!/usr/bin/env bash
set -eu
if [ "${1:-}" = - ]; then cat >/dev/null; exit 0; fi
case "${*: -1}" in
 credentials|kaze-credentials)
   cat >/dev/null
   [ "$FAIL_STAGE" != credentials ] || exit 17;;
esac
''',
        "docker": '''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$COMPOSE_LOG"
case " $* " in
 *" run --rm -T migrate "*) [ "$FAIL_STAGE" != migrate ] || exit 31;;
 *" scripts.demo_reset "*)
   if [ "$FAIL_STAGE" = reset ] || [ "$FAIL_STAGE" = recovery ]; then
     echo 'Strict fixture guard refused unknown check; no deletion.' >&2
     exit 23
   fi;;
 *" --force-recreate api worker kaze-worker caddy "*)
   [ "$FAIL_STAGE" != recovery ] || exit 47;;
esac
''',
    }
    for name, body in scripts.items():
        file = bin_path / name
        file.write_text(body, encoding="utf-8", newline="\n")
        file.chmod(0o755)

    def run(stage="none"):
        log = tmp_path / "compose.log"
        result = subprocess.run(
            [BASH, "-c", 'export PATH="$1:$PATH"; exec bash deploy/reset-demo.sh',
             "wrapper-test", shell_path(bin_path)],
            cwd=tmp_path, capture_output=True, text=True,
            env={**os.environ, "FAIL_STAGE": stage, "COMPOSE_LOG": shell_path(log)},
            timeout=30,
        )
        return result, log.read_text().splitlines()

    return run


def test_refused_reset_restarts_services_but_preserves_original_failure(wrapper):
    result, calls = wrapper("reset")
    assert result.returncode == 23
    assert "Strict fixture guard refused" in result.stderr
    assert "Services restarted; reset still failed" in result.stderr
    assert "Data was not certified as reset" in result.stderr
    assert "scripts.demo_reset" in calls[-2]
    assert "--force-recreate api worker kaze-worker caddy" in calls[-1]
    assert sum("scripts.demo_reset" in call for call in calls) == 1


def test_successful_reset_starts_services_once_without_recovery_warning(wrapper):
    result, calls = wrapper()
    assert result.returncode == 0, result.stderr
    assert "recovery" not in result.stderr
    assert sum("--force-recreate" in call for call in calls) == 1
    assert "scripts.demo_reset" in calls[-2]


def test_failed_recovery_reports_unconfirmed_availability_and_original_reset_status(wrapper):
    result, calls = wrapper("recovery")
    assert result.returncode == 23
    assert "Service recovery failed (status 47)" in result.stderr
    assert "availability is unconfirmed" in result.stderr
    assert "Services restarted" not in result.stderr
    assert "--force-recreate" in calls[-1]


def test_migration_failure_never_attempts_reset_or_service_start(wrapper):
    result, calls = wrapper("migrate")
    assert result.returncode == 31
    assert "migrate" in calls[-1]
    assert not any("scripts.demo_reset" in call or "--force-recreate" in call for call in calls)
    assert "recovery" not in result.stderr


def test_private_credential_preparation_failure_does_not_restart_services(wrapper):
    result, calls = wrapper("credentials")
    assert result.returncode == 17
    assert not any("scripts.demo_reset" in call or "--force-recreate" in call for call in calls)
    assert "recovery" not in result.stderr
