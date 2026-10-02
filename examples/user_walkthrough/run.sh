#!/usr/bin/env bash
set -euo pipefail
tutorial_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"${PYTHON:-python3}" "$tutorial_dir/run.py"
