#!/bin/bash
# 在模拟器上跑全部单元测试。模拟器偶尔在连续安装后拒绝启动（"failed preflight checks"），此时重试一次。
cd "$(dirname "$0")/.." || exit 1
DEST="platform=iOS Simulator,name=${STANDIT_TEST_SIM:-iPhone 17 Pro Max}"
SIM=${STANDIT_TEST_SIM:-"iPhone 17 Pro Max"}
# 关机状态的模拟器经常让测试宿主启动失败（"failed preflight checks"）：先启动并等待就绪。
xcrun simctl boot "$SIM" >/dev/null 2>&1
xcrun simctl bootstatus "$SIM" -b >/dev/null 2>&1
LOG=$(mktemp)
for attempt in 1 2; do
  xcodebuild -scheme StandIt -destination "$DEST" test >"$LOG" 2>&1
  status=$?
  if [ $status -eq 0 ] || ! grep -q "failed preflight checks" "$LOG"; then break; fi
  # 旧的测试宿主仍占着时 SpringBoard 会拒绝启动：卸载后重试。
  xcrun simctl terminate "$SIM" cn.xiaobucubic.standit >/dev/null 2>&1
  xcrun simctl uninstall "$SIM" cn.xiaobucubic.standit >/dev/null 2>&1
  sleep 2
done
grep -E "^/.*: error:|Test Case .* failed|Executed|TEST (SUCCEEDED|FAILED)|preflight" "$LOG" | sort -u | tail -15
rm -f "$LOG"
exit $status
