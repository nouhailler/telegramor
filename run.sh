#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Lancez d'abord ./install.sh"; exit 1; }
exec .venv/bin/python main.py "$@"
