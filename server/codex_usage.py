#!/usr/bin/env python3
"""查询当前 Codex 订阅和用量额度，不调用模型、不消耗推理 token。

通过本机 `codex app-server` 的 account/read 和 account/rateLimits/read
只读接口查询，复用 Codex 的登录状态（包括 CODEX_HOME 和系统凭据存储）。
不创建会话、不发送提示词，仅依赖 Python 标准库和已安装的 Codex CLI。
接口文档: https://learn.chatgpt.com/docs/app-server

用法:
    ./codex_usage.py          # 订阅、已用额度、重置时间
    ./codex_usage.py --json   # account 和额度接口的 JSON 结果
    ./codex_usage.py --push [URL] [--interval 300]   # 提交到显示服务
"""
import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import display_push


def fetch_usage(timeout=30):
    """仅发送初始化和两个账户查询请求，绝不启动模型 turn。"""
    try:
        proc = subprocess.Popen(
            ["codex", "app-server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        )
    except FileNotFoundError:
        raise RuntimeError("未找到 codex，请先安装 Codex CLI 并运行 `codex login`。") from None

    messages = queue.Queue()

    def read_messages():
        try:
            for line in proc.stdout:
                messages.put(json.loads(line))
        except (OSError, ValueError):
            pass
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_messages, daemon=True)
    reader.start()

    def send(message):
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise RuntimeError("Codex app-server 已断开，请检查 Codex CLI 安装和配置。") from None

    def request(request_id, method, params):
        send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("查询超时 (%s)，请检查网络或稍后重试。" % method) from None
            if not isinstance(message, dict):
                raise RuntimeError("Codex app-server 意外退出或响应无效，请检查 CLI 版本和配置。")
            # 通知可能穿插在响应之间，不能将其当作当前请求的返回值。
            if "method" in message or message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise RuntimeError("查询失败 (%s): %s\n若登录已失效，请运行 `codex login`。" % (method, detail))
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Codex 返回了无效结果 (%s)。" % method)
            return result

    try:
        request(1, "initialize", {"clientInfo": {"name": "codex_usage", "version": "1.0.0"}})
        send({"method": "initialized"})
        account = request(2, "account/read", {"refreshToken": False}).get("account")
        if not account:
            raise RuntimeError("未找到 Codex 登录账号，请运行 `codex login` 并用 ChatGPT 账号登录。")
        if account.get("type") != "chatgpt":
            raise RuntimeError("当前登录方式为 %s，无法查询 ChatGPT 订阅额度。请用 ChatGPT 账号登录 Codex。" % account.get("type"))
        usage = request(3, "account/rateLimits/read", {})
        return {"account": account, **usage}
    finally:
        # 无论成功、超时还是 Ctrl-C，都回收本次启动的子进程。
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        reader.join(timeout=1)
        proc.stdin.close()
        proc.stdout.close()


def format_reset(timestamp):
    if timestamp is None:
        return ""
    reset = datetime.fromtimestamp(timestamp, timezone.utc)
    secs = int((reset - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "已到重置时间"
    d, rem = divmod(secs, 86400)
    h, m = divmod(rem // 60, 60)
    left = ("%d天" % d if d else "") + ("%d小时" % h if h else "") + "%d分" % m
    return "%s 后重置 (%s)" % (left, reset.astimezone().strftime("%m-%d %H:%M"))


def bar(pct, width=30):
    filled = int(round(min(max(pct, 0), 100) / 100 * width))
    return "█" * filled + "░" * (width - filled)


def window_label(minutes, fallback):
    # primary 不一定是 5 小时；以服务端实际返回的窗口长度为准。
    if not minutes:
        return fallback
    if minutes == 10080:
        return "本周 (7 天)"
    if minutes % 1440 == 0:
        return "%g 天额度" % (minutes / 1440)
    if minutes % 60 == 0:
        return "%g 小时额度" % (minutes / 60)
    return "%g 分钟额度" % minutes


def print_usage(data):
    default = data.get("rateLimits") or {}
    plan = default.get("planType") or (data.get("account") or {}).get("planType") or "未知"
    print("订阅: %s\n" % plan)
    buckets = data.get("rateLimitsByLimitId") or {}
    if not buckets and default:
        buckets = {default.get("limitId") or "codex": default}
    if not buckets:
        print("服务端未返回额度信息。")
    for limit_id, limit in buckets.items():
        if not isinstance(limit, dict):
            continue
        name = limit.get("limitName") or limit_id
        rows = 0
        for key, fallback in (("primary", "主额度"), ("secondary", "次额度")):
            window = limit.get(key)
            if not window or window.get("usedPercent") is None:
                continue
            pct = float(window["usedPercent"])
            label = window_label(window.get("windowDurationMins"), fallback)
            print("%s · %s" % (name, label))
            print("  %s 已用 %5.1f%%  %s\n" % (bar(pct), pct, format_reset(window.get("resetsAt"))))
            rows += 1
        if not rows:
            print("%s: 服务端未返回用量窗口。" % name)
        credits = limit.get("credits") or {}
        if credits.get("unlimited"):
            print("%s 额外额度: 不限\n" % name)
        elif credits.get("balance") is not None:
            # 不假设 credits 的货币单位，也不自行缩放服务端余额。
            print("%s 额外额度余额: %s credits\n" % (name, credits["balance"]))
        if limit.get("rateLimitReachedType"):
            print("%s 限额状态: %s" % (name, limit["rateLimitReachedType"]))
    resets = data.get("rateLimitResetCredits") or {}
    if resets.get("availableCount") is not None:
        print("可用额度重置次数: %s" % resets["availableCount"])


def to_display(data):
    """转换为显示服务的订阅项：取默认额度的 primary / secondary 窗口。"""
    limit = data.get("rateLimits")
    if not isinstance(limit, dict):
        limit = next((v for v in (data.get("rateLimitsByLimitId") or {}).values() if isinstance(v, dict)), {})
    windows = []
    for key, fallback in (("primary", "主额度"), ("secondary", "次额度")):
        window = limit.get(key)
        if isinstance(window, dict) and window.get("usedPercent") is not None:
            windows.append({
                "label": display_push.window_label(window.get("windowDurationMins")) or fallback,
                "used_percent": window["usedPercent"],
                "reset_at": display_push.iso_to_unix(window.get("resetsAt")),
            })
    plan = limit.get("planType") or (data.get("account") or {}).get("planType")
    return {
        "id": "codex",
        "name": "Codex",
        "plan": plan.capitalize() if plan else None,
        "source": "official",
        "updated_at": int(time.time()),
        "windows": windows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出账户和额度接口的 JSON 结果")
    display_push.add_arguments(parser)
    args = parser.parse_args()
    try:
        if args.push:
            display_push.run(args, lambda: to_display(fetch_usage()))
            return
        data = fetch_usage()
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print_usage(data)
    except (RuntimeError, OSError) as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
