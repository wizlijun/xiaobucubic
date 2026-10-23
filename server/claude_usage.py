#!/usr/bin/env python3
"""查询 Claude 订阅（Pro/Max）的用量额度，等同于 Claude Code 里的 /usage。

只调用 Anthropic 的用量查询接口，不调用模型，因此不消耗任何 token。
凭据复用 Claude Code 登录后保存的 OAuth token（macOS 钥匙串或 ~/.claude/.credentials.json）。

用法:
    ./claude_usage.py          # 人类可读输出
    ./claude_usage.py --json   # 原始 JSON
    ./claude_usage.py --push [URL] [--interval 300]   # 提交到显示服务
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import display_push

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = os.path.expanduser("~/.claude/.credentials.json")

KIND_LABELS = {
    "session": "当前会话 (5 小时)",
    "weekly_all": "本周 (所有模型)",
    "weekly_scoped": "本周",
}
# 旧版响应没有 limits 列表时的回退字段
LABELS = {
    "five_hour": "当前会话 (5 小时)",
    "seven_day": "本周 (所有模型)",
    "seven_day_opus": "本周 (Opus)",
    "seven_day_sonnet": "本周 (Sonnet)",
    "seven_day_oauth_apps": "本周 (OAuth 应用)",
}


def load_credentials():
    raw = None
    if sys.platform == "darwin":
        try:
            raw = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raw = None
    if not raw and os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE) as f:
            raw = f.read()
    if not raw:
        raise RuntimeError("未找到 Claude Code 凭据，请先运行 `claude` 并用订阅账号登录。")
    return json.loads(raw)["claudeAiOauth"]


def fetch_usage(token):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claude-code/2.0.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        hint = "（token 可能已过期，运行一次 `claude` 即可自动刷新）" if e.code == 401 else ""
        raise RuntimeError("请求失败: HTTP %d %s%s" % (e.code, e.read().decode(errors="replace")[:300], hint)) from None
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误: %s" % e.reason) from None


def format_reset(iso):
    if not iso:
        return ""
    # 去掉小数秒，兼容 Python 3.9 的 fromisoformat
    iso = re.sub(r"\.\d+", "", iso.replace("Z", "+00:00"))
    reset = datetime.fromisoformat(iso)
    secs = int((reset - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "已重置"
    d, rem = divmod(secs, 86400)
    h, m = divmod(rem // 60, 60)
    left = ("%d天" % d if d else "") + ("%d小时" % h if h else "") + "%d分" % m
    return "%s 后重置 (%s)" % (left, reset.astimezone().strftime("%m-%d %H:%M"))


def bar(pct, width=30):
    filled = int(round(min(max(pct, 0), 100) / 100 * width))
    return "█" * filled + "░" * (width - filled)


def to_display(data, creds):
    """转换为显示服务的订阅项：主窗口 5 小时会话，次窗口 7 天（所有模型）。"""
    if data.get("limits"):
        by_kind = {lim.get("kind"): lim for lim in data["limits"] if isinstance(lim, dict)}
        pairs = [(by_kind.get("session"), "percent"), (by_kind.get("weekly_all"), "percent")]
    else:
        pairs = [(data.get("five_hour"), "utilization"), (data.get("seven_day"), "utilization")]
    windows = []
    for (lim, key), label in zip(pairs, ("5小时", "7天")):
        if isinstance(lim, dict):
            windows.append({
                "label": label,
                "used_percent": lim.get(key),
                "reset_at": display_push.iso_to_unix(lim.get("resets_at")),
            })
    plan = creds.get("subscriptionType")
    return {
        "id": "claude",
        "name": "Claude",
        "plan": plan.capitalize() if plan else None,
        "source": "official",
        "updated_at": int(time.time()),
        "windows": windows,
    }


def collect():
    creds = load_credentials()
    return to_display(fetch_usage(creds["accessToken"]), creds)


def print_usage(data, creds):
    plan = creds.get("subscriptionType")
    if plan:
        print("订阅: %s\n" % plan)
    rows = []
    if data.get("limits"):
        for lim in data["limits"]:
            label = KIND_LABELS.get(lim.get("kind"), lim.get("kind"))
            model = ((lim.get("scope") or {}).get("model") or {}).get("display_name")
            if model:
                label += " (%s)" % model
            rows.append((label, lim.get("percent"), lim.get("resets_at")))
    else:
        for key, val in data.items():
            if isinstance(val, dict) and val.get("utilization") is not None:
                rows.append((LABELS.get(key, key), val["utilization"], val.get("resets_at")))

    for label, pct, resets_at in rows:
        pct = float(pct or 0)
        print(label)
        print("  %s %5.1f%%  %s\n" % (bar(pct), pct, format_reset(resets_at)))

    extra = data.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled"):
        scale = 10 ** (extra.get("decimal_places") or 0)
        cur = extra.get("currency") or ""
        used = (extra.get("used_credits") or 0) / scale
        limit = extra.get("monthly_limit")
        limit_str = "%.2f" % (limit / scale) if limit is not None else "不限"
        print("额外用量: %.2f / %s %s" % (used, limit_str, cur))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    display_push.add_arguments(parser)
    args = parser.parse_args()
    try:
        if args.push:
            display_push.run(args, collect)
            return
        creds = load_credentials()
        expires_at = creds.get("expiresAt")
        if expires_at and expires_at / 1000 < time.time():
            print("提示: 本地 token 已过期，若请求失败请运行一次 `claude` 刷新。", file=sys.stderr)
        data = fetch_usage(creds["accessToken"])
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print_usage(data, creds)
    except RuntimeError as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
