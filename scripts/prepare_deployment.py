"""Create private demo configuration without printing signing secrets or bearer tokens."""
import argparse
import json
import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", re.ASCII)
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", re.ASCII)


def initialize(path: Path, hostname: str):
    hostname = hostname.strip().lower()
    if (not HOST.fullmatch(hostname) or ".." in hostname
            or len(hostname) > 253 or any(not LABEL.fullmatch(label) for label in hostname.split("."))):
        raise ValueError("Use a DNS hostname without a scheme, port, wildcard or path")
    values = {"PM_DEMO_DOMAIN": hostname, "PM_FRONTEND_HOSTS": hostname,
              "PM_JWT_SECRET": secrets.token_hex(32), "PM_DEMO_TOKEN": ""}
    template = (ROOT / "deploy/demo.env.example").read_text(encoding="utf-8")
    lines = []
    for line in template.splitlines():
        key = line.partition("=")[0]
        lines.append(f"{key}={values[key]}" if key in values else line)
    # O_EXCL also refuses existing files and symlinks; never replace an operator's config.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")


def store_credentials(path: Path, credentials: dict):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Initialize a regular private environment file first")
    updates = {}
    for role, variable in (("nurse", "PM_DEMO_TOKEN"), ("psw", "PM_DEMO_PSW_TOKEN")):
        token = credentials.get(role)
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError(f"Bootstrap did not supply a valid-shaped {role} token")
        updates[variable] = token
    # Token signature/identity/expiry are verified by server startup, not by this file writer.
    lines, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0]
        if key in updates:
            if key in seen:
                raise ValueError("Duplicate credential variable in environment file")
            line = f"{key}={updates[key]}"
            seen.add(key)
        lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    descriptor, temporary = tempfile.mkstemp(prefix=".demo-env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("hostname")
    commands.add_parser("credentials", help="Read bootstrap JSON on stdin; never print tokens")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.env_file, args.hostname)
        else:
            payload = json.loads(sys.stdin.read(16 * 1024))
            if not isinstance(payload, dict):
                raise ValueError("Bootstrap JSON must be an object")
            store_credentials(args.env_file, payload)
    except (OSError, ValueError, TypeError):
        # Do not echo input, file contents, provider errors or bearer material.
        print("Configuration not written: check hostname, existing file and bootstrap format.",
              file=sys.stderr)
        return 1
    print(f"Private configuration updated: {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
