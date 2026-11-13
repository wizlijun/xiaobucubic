#!/usr/bin/env bash
# Keep each board's sdkconfig, images and CMake cache separate.
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
board="${1:-}"
case "$board" in
  waveshare|qualia|qualia-480-60hz|qualia-color-test|qualia-720|qualia-720-color-test|qualia-720-pwm-test|qualia-720-sram-test|qualia-720-sram-edge-test|qualia-720-edge-test|qualia-720-sram-24mhz-test|qualia-720-24mhz-test|qualia-720-rotate) shift ;;
  *) echo 'Usage: scripts/board.sh {waveshare|qualia|qualia-480-60hz|qualia-color-test|qualia-720|qualia-720-color-test|qualia-720-pwm-test|qualia-720-sram-test|qualia-720-sram-edge-test|qualia-720-edge-test|qualia-720-sram-24mhz-test|qualia-720-24mhz-test|qualia-720-rotate} [idf.py arguments, default: build]' >&2; exit 2 ;;
esac
if [[ $# -eq 0 ]]; then set -- build; fi
build_dir="$project_dir/build/$board"
mkdir -p "$build_dir"
exec "$project_dir/scripts/idf.sh" -B "$build_dir" \
  -D "SDKCONFIG=$build_dir/sdkconfig" \
  -D "SDKCONFIG_DEFAULTS=$project_dir/sdkconfig.defaults;$project_dir/boards/$board/sdkconfig.defaults" "$@"
