#!/bin/bash
# 先启动 frpc 联网，代理建立成功后再启动显示服务；任一退出时一并停止。
# 首次运行会生成 display.env（读 / 写 token，仅本人可读）。
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=display.env
FRPC_LOG=frpc.log

# 缺哪个 token 补哪个：READ 给终端，WRITE 给采集脚本，MESSAGE 给推送提醒的机器人。
(umask 077; touch "$ENV_FILE")
for name in DISPLAY_READ_TOKEN DISPLAY_WRITE_TOKEN DISPLAY_MESSAGE_TOKEN; do
  if ! grep -q "^${name}=" "$ENV_FILE"; then
    echo "${name}=$(openssl rand -hex 24)" >> "$ENV_FILE"
    echo "已生成 ${name}，保存在 ${PWD}/${ENV_FILE}"
  fi
done
set -a; . "./$ENV_FILE"; set +a

FRPC_PID=
SERVER_PID=
cleanup() { kill $FRPC_PID $SERVER_PID 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM

frpc verify -c frpc.toml >/dev/null
frpc -c frpc.toml > "$FRPC_LOG" 2>&1 &
FRPC_PID=$!

# 等待 frpc 登录并开启代理，最多 15 秒。
for _ in $(seq 30); do
  grep -q "start proxy success" "$FRPC_LOG" && break
  if ! kill -0 "$FRPC_PID" 2>/dev/null || grep -q "start error" "$FRPC_LOG"; then
    echo "frpc 启动失败，日志如下:" >&2; cat "$FRPC_LOG" >&2; exit 1
  fi
  sleep 0.5
done
if ! grep -q "start proxy success" "$FRPC_LOG"; then
  echo "frpc 15 秒内未建立代理，日志如下:" >&2; cat "$FRPC_LOG" >&2; exit 1
fi
echo "frpc 已联网: 120.48.136.92:8007 -> 127.0.0.1:8007（日志 ${PWD}/${FRPC_LOG}）"

# 只监听本机，外部访问统一经过 frp。
python3 display_server.py --host 127.0.0.1 --port 8007 "$@" &
SERVER_PID=$!
wait "$SERVER_PID"
