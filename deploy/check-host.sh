#!/usr/bin/env bash
# Read-only prerequisites; never render Compose configuration or private environment values.
set -euo pipefail
command -v python3 >/dev/null || { echo 'Install Python 3.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Install Docker Engine and Compose plugin.' >&2; exit 1; }
docker info >/dev/null
docker compose version
printf 'CPU cores: '; getconf _NPROCESSORS_ONLN
awk '/MemTotal:/ {printf "RAM: %.1f GiB\n", $2/1024/1024}' /proc/meminfo
df -h .
echo 'Host prerequisites checked. No deployment was started.'
