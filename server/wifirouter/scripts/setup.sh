#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
export IDF_TOOLS_PATH="$project_dir/.tools/espressif"
mkdir -p "$project_dir/.tools"
if [[ ! -d "$project_dir/.tools/esp-idf/.git" ]]; then
  git clone --branch v5.5.2 --depth 1 --shallow-submodules --recursive \
    https://github.com/espressif/esp-idf.git "$project_dir/.tools/esp-idf"
fi
python3 "$project_dir/.tools/esp-idf/tools/idf_tools.py" install --targets=esp32s3 \
  xtensa-esp-elf xtensa-esp-elf-gdb esp-rom-elfs
python3 "$project_dir/.tools/esp-idf/tools/idf_tools.py" install-python-env
# This firmware does not use the ULP coprocessor or OpenOCD. Avoid installing
# the unrelated RISC-V/ULP toolchains required by the full SDK bundle.
export IDF_SKIP_TOOLS_CHECK=1
source "$project_dir/.tools/esp-idf/export.sh" >/dev/null
unset IDF_SKIP_TOOLS_CHECK
python -m pip install 'cmake>=3.24,<4' 'ninja>=1.11,<2'
