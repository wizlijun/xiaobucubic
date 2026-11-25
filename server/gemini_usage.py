#!/usr/bin/env python3
"""查询当前 Gemini 订阅用量额度，不调用模型、不消耗推理 token。

通过本机 `agy --print /usage --output-format json` 只读斜杠命令查询，
复用 Antigravity CLI 的登录状态（不创建会话、不消耗 token），
仅依赖 Python 标准库和已安装的 `agy`。

用法:
    ./gemini_usage.py          # 订阅用量与重置时间
    ./gemini_usage.py --json   # agy /usage 返回的原始 JSON
    ./gemini_usage.py --push [URL] [--follow]   # 提交到显示服务
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import display_push

DEFAULT_TIMEOUT = 30
FALLBACK_AGY_PATHS = (
    os.path.expanduser("~/.local/bin/agy"),
)
WINDOW_LABELS = {
    "5h": "5小时",
    "weekly": "7天",
}
PRETTY_WINDOW_LABELS = {
    "5h": "当前会话 (5 小时)",
    "weekly": "本周 (7 天)",
}
WINDOW_PRIORITY = {
    "5h": 0,
    "weekly": 1,
}


def resolve_agy_bin(agy_bin=None):
    """查找 agy 可执行文件，兼容守护进程未包含 ~/.local/bin 的 PATH。"""
    candidate = (agy_bin or os.environ.get("AGY_BIN") or "").strip()
    if candidate:
        if os.path.sep in candidate:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            raise RuntimeError("指定的 agy 不可执行: %s" % candidate)
        found = shutil.which(candidate)
        if found:
            return found
        raise RuntimeError("未找到指定的 agy 命令: %s" % candidate)

    found = shutil.which("agy")
    if found:
        return found
    for path in FALLBACK_AGY_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise RuntimeError("未找到 agy，请先安装 Antigravity CLI 并运行 `agy` 登录。")


def _parse_json_output(raw):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _error_detail(parsed, stderr):
    if isinstance(parsed, dict):
        for key in ("error", "message", "response"):
            val = parsed.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:200]
            if isinstance(val, dict):
                msg = val.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()[:200]
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def fetch_usage(agy_bin=None, timeout=DEFAULT_TIMEOUT):
    """仅调用只读斜杠命令 `/usage`，不发起模型 turn。"""
    cmd = resolve_agy_bin(agy_bin)
    try:
        proc = subprocess.run(
            [cmd, "--print", "/usage", "--output-format", "json"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("未找到 agy，请先安装 Antigravity CLI 并运行 `agy` 登录。") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("agy 查询超时 (%ds)，请检查网络或稍后重试。" % timeout) from None
    except OSError as exc:
        raise RuntimeError("无法执行 agy: %s" % exc) from None

    data = _parse_json_output(proc.stdout)
    if proc.returncode != 0:
        detail = _error_detail(data, proc.stderr)
        suffix = (": " + detail) if detail else ""
        raise RuntimeError("agy 查询失败 (退出码 %d)%s\n若未登录或登录已失效，请运行 `agy` 登录。" % (
            proc.returncode, suffix))
    if not isinstance(data, dict):
        raise RuntimeError("agy /usage 未返回有效的 JSON 对象。")
    status = data.get("status")
    if status is not None and status != "SUCCESS":
        detail = _error_detail(data, proc.stderr)
        suffix = (": " + detail) if detail else ""
        raise RuntimeError("agy /usage 返回异常状态 (%s)%s" % (status, suffix))
    command = data.get("command")
    if not isinstance(command, dict) or command.get("name") != "usage" or not isinstance(command.get("data"), dict):
        raise RuntimeError("agy /usage 响应缺少 command.data 额度数据。")
    return data


def find_gemini_group(data):
    groups = ((data.get("command") or {}).get("data") or {}).get("groups")
    if not isinstance(groups, list) or not groups:
        raise RuntimeError("agy /usage 未返回任何模型组额度。")
    for group in groups:
        if not isinstance(group, dict):
            continue
        buckets = group.get("buckets")
        if isinstance(buckets, list) and any(
            isinstance(b, dict) and str(b.get("id") or "").strip().lower().startswith("gemini")
            for b in buckets
        ):
            return group
    for group in groups:
        if isinstance(group, dict) and "gemini" in str(group.get("name") or "").lower():
            return group
    raise RuntimeError("agy /usage 未返回 Gemini 模型组的额度信息。")


def bucket_window_key(bucket):
    window = str(bucket.get("window") or "").strip().lower()
    if window in ("5h", "5_hour", "five_hour"):
        return "5h"
    if window in ("weekly", "7d", "7_day", "week"):
        return "weekly"
    bucket_id = str(bucket.get("id") or "").strip().lower()
    if bucket_id.endswith("-5h") or bucket_id == "5h":
        return "5h"
    if bucket_id.endswith("-weekly") or bucket_id == "weekly":
        return "weekly"
    return window


def bucket_label(bucket):
    key = bucket_window_key(bucket)
    if key in WINDOW_LABELS:
        return WINDOW_LABELS[key]
    fallback = str(bucket.get("window") or bucket.get("name") or "用量").strip()
    return fallback[:16] or "用量"


def remaining_to_used_percent(value):
    """agy 返回 0..1 的剩余比例，转换为显示服务使用的已用百分比 (0..100)。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuntimeError("agy 返回了无效的 remaining_fraction。")
    if value < 0 or value > 1:
        raise RuntimeError("agy 返回的 remaining_fraction 超出 0–1 范围。")
    used = round((1.0 - float(value)) * 100.0, 1)
    if used == 0:
        return 0
    return int(used) if float(used).is_integer() else used


def _ordered_buckets(buckets):
    valid = [b for b in buckets if isinstance(b, dict)]
    indexed = list(enumerate(valid))
    indexed.sort(key=lambda pair: (WINDOW_PRIORITY.get(bucket_window_key(pair[1]), 99), pair[0]))
    return [b for _, b in indexed]


def to_display(data):
    """转换为显示服务的订阅项：主窗口 5 小时，次窗口 7 天（与 Claude / Codex 一致）。"""
    group = find_gemini_group(data)
    buckets = _ordered_buckets(group.get("buckets") or [])
    if not buckets:
        raise RuntimeError("agy /usage 未返回 Gemini 用量窗口。")
    windows = []
    seen_keys = set()
    for bucket in buckets:
        key = bucket_window_key(bucket)
        if key in ("5h", "weekly") and key in seen_keys:
            continue
        if key in ("5h", "weekly"):
            seen_keys.add(key)
        used_percent = remaining_to_used_percent(bucket.get("remaining_fraction"))
        windows.append({
            "label": bucket_label(bucket),
            "used_percent": used_percent,
            "reset_at": display_push.iso_to_unix(bucket.get("reset_time")),
        })
        if len(windows) >= 2:
            break
    if not any(w["used_percent"] is not None for w in windows):
        raise RuntimeError("agy /usage 未返回有效的 Gemini 剩余额度。")
    return {
        "id": "gemini",
        "name": "Gemini",
        "source": "official",
        "updated_at": int(time.time()),
        "windows": windows,
    }


def format_reset(iso):
    if not iso:
        return ""
    text = re.sub(r"\.\d+", "", str(iso).replace("Z", "+00:00"))
    try:
        reset = datetime.fromisoformat(text)
    except ValueError:
        return "重置时间: %s" % iso
    if reset.tzinfo is None:
        reset = reset.replace(tzinfo=timezone.utc)
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


def print_usage(data):
    group = find_gemini_group(data)
    print("订阅组: %s\n" % (group.get("name") or "Gemini Models"))
    for bucket in _ordered_buckets(group.get("buckets") or []):
        key = bucket_window_key(bucket)
        label = PRETTY_WINDOW_LABELS.get(key) or bucket.get("name") or bucket_label(bucket)
        used_pct = remaining_to_used_percent(bucket.get("remaining_fraction"))
        print(label)
        if used_pct is None:
            print("  未返回剩余比例  %s\n" % format_reset(bucket.get("reset_time")))
        else:
            remaining_pct = max(0.0, 100.0 - float(used_pct))
            print("  %s 剩余 %5.1f%% (已用 %5.1f%%)  %s\n" % (
                bar(used_pct), remaining_pct, used_pct, format_reset(bucket.get("reset_time"))))


def collect(agy_bin=None, timeout=DEFAULT_TIMEOUT):
    return to_display(fetch_usage(agy_bin=agy_bin, timeout=timeout))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出 agy /usage 的原始 JSON")
    parser.add_argument("--agy", default=None, help="agy 可执行文件路径（也可设置 AGY_BIN）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="查询超时秒数 (默认 %d)" % DEFAULT_TIMEOUT)
    display_push.add_arguments(parser, "gemini")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须是正整数")
    try:
        if args.push:
            display_push.run(args, lambda: collect(agy_bin=args.agy, timeout=args.timeout))
            return
        data = fetch_usage(agy_bin=args.agy, timeout=args.timeout)
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
