#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
export IDF_TOOLS_PATH="$project_dir/.tools/espressif"
export IDF_PATH="$project_dir/.tools/esp-idf"
if [[ ! -f "$IDF_PATH/export.sh" ]]; then
  echo 'Run scripts/setup.sh first.' >&2
  exit 1
fi
# Only the Xtensa toolchain is needed; CMake still validates its version.
export IDF_SKIP_TOOLS_CHECK=1
source "$IDF_PATH/export.sh" >/dev/null
unset IDF_SKIP_TOOLS_CHECK
cd "$project_dir"
exec idf.py "$@"
