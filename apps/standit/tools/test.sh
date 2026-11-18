#!/bin/bash
# 在模拟器上跑全部单元测试。模拟器偶尔在连续安装后拒绝启动（"failed preflight checks"），此时重试一次。
cd "$(dirname "$0")/.." || exit 1
DEST=${STANDIT_TEST_DEST:-'platform=iOS Simulator,name=iPhone 17 Pro Max'}
LOG=$(mktemp)
for attempt in 1 2; do
  xcodebuild -scheme StandIt -destination "$DEST" test >"$LOG" 2>&1
  status=$?
  if [ $status -eq 0 ] || ! grep -q "failed preflight checks" "$LOG"; then break; fi
  sleep 3
done
grep -E "error:|failed|Executed|TEST (SUCCEEDED|FAILED)" "$LOG" | sort -u | tail -15
rm -f "$LOG"
exit $status
