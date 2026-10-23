#!/usr/bin/env python3
"""查询 Grok 订阅的周额度，不调用模型、不消耗推理 token。

复用官方 Grok CLI 登录后保存的 ~/.grok/auth.json，仅 GET 账单和套餐信息。
需要先安装官方 CLI (https://docs.x.ai/build/overview) 并执行 `grok login`。
账单接口属于客户端内部接口，字段可能随 Grok 更新而变化。

用法:
    ./grok_usage.py
    ./grok_usage.py --json
    ./grok_usage.py --auth-file /path/to/auth.json
    ./grok_usage.py --push [URL] [--interval 300]   # 提交到显示服务
"""
import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import display_push

BASE_URL = "https://cli-chat-proxy.grok.com/v1"
OIDC_SCOPE = "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
LEGACY_SCOPE = "https://accounts.x.ai/sign-in"


def load_credentials(path):
    try:
        with Path(path).expanduser().open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RuntimeError("未找到 Grok 登录凭据，请先运行 `grok login`。") from None
    except (ValueError, OSError):
        raise RuntimeError("无法读取 Grok 凭据文件，请检查 --auth-file 或重新运行 `grok login`。") from None
    if isinstance(data, dict):
        for scope in (OIDC_SCOPE, LEGACY_SCOPE):
            entry = data.get(scope)
            if isinstance(entry, dict) and isinstance(entry.get("key"), str) and entry["key"].strip():
                return entry["key"].strip()
    raise RuntimeError("未找到 Grok 订阅账号凭据，请运行 `grok login`，使用订阅账号登录。")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不将登录凭据跟随重定向发往其他地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(endpoint, token):
    req = urllib.request.Request(BASE_URL + endpoint, headers={
        "Authorization": "Bearer " + token,
        "X-XAI-Token-Auth": "xai-grok-cli",
        "Accept": "application/json",
        "User-Agent": "grok-usage/1.0",
    }, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # 不输出原始响应正文，避免错误页面回显凭据。
        hint = "；登录可能已过期，请运行 `grok login`" if exc.code in (401, 403) else ""
        raise RuntimeError("请求 %s 失败: HTTP %d%s" % (endpoint, exc.code, hint)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("请求 %s 失败，请检查网络或稍后重试。" % endpoint) from None
    except ValueError:
        raise RuntimeError("接口 %s 未返回有效 JSON。" % endpoint) from None
    if not isinstance(data, dict):
        raise RuntimeError("接口 %s 返回的 JSON 格式不符合预期。" % endpoint)
    return data


def fetch_usage(token):
    billing = fetch_json("/billing?format=credits", token)
    try:
        settings = fetch_json("/settings", token)
    except RuntimeError as exc:
        # 套餐名称失败不应掩盖已成功获取的用量。
        print("提示: %s" % exc, file=sys.stderr)
        settings = None
    return {"billing": billing, "settings": settings}


def percent(value):
    """百分数字段直接按百分比展示，不猜测 0..1 是否代表比例。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def bar(pct, width=30):
    filled = int(round(min(max(pct, 0), 100) / 100 * width))
    return "█" * filled + "░" * (width - filled)


def format_reset(value):
    if not value:
        return ""
    try:
        reset = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if reset.tzinfo is None:
            reset = reset.replace(tzinfo=timezone.utc)
    except ValueError:
        return "重置时间: %s" % value
    secs = int((reset - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "已到重置时间"
    d, rem = divmod(secs, 86400)
    h, m = divmod(rem // 60, 60)
    left = ("%d天" % d if d else "") + ("%d小时" % h if h else "") + "%d分" % m
    return "%s 后重置 (%s)" % (left, reset.astimezone().strftime("%m-%d %H:%M"))


def print_usage(data):
    settings = data.get("settings") or {}
    print("订阅: %s\n" % (settings.get("subscription_tier_display") or "未知"))
    config = (data.get("billing") or {}).get("config") or {}
    period = config.get("currentPeriod") or {}
    period_type = str(period.get("type") or "").upper()
    weekly = period_type == "WEEKLY" or period_type.endswith("_WEEKLY")
    print("本周 (共享额度)" if weekly else "当前额度 (接口未确认周周期)")
    pct = percent(config.get("creditUsagePercent"))
    if pct is None:
        print("  接口未返回已用百分比，请在 Grok 设置 → Usage 查看。")
    else:
        print("  %s 已用 %5.1f%%" % (bar(pct), pct))
    reset = format_reset(period.get("end"))
    if reset:
        print("  " + reset)
    print()
    for product in config.get("productUsage") or []:
        if not isinstance(product, dict):
            continue
        used = percent(product.get("usagePercent"))
        if used is not None:
            print("  %s: %.1f%%" % (product.get("product") or "未知产品", used))


def to_display(data):
    """转换为显示服务的订阅项：Grok 只有一个共享额度窗口。"""
    config = (data.get("billing") or {}).get("config") or {}
    period = config.get("currentPeriod") or {}
    period_type = str(period.get("type") or "").upper()
    weekly = period_type == "WEEKLY" or period_type.endswith("_WEEKLY")
    return {
        "id": "grok",
        "name": "Grok",
        "plan": (data.get("settings") or {}).get("subscription_tier_display"),
        "source": "official",
        "updated_at": int(time.time()),
        "windows": [{
            "label": "7天" if weekly else "本期",
            "used_percent": percent(config.get("creditUsagePercent")),
            "reset_at": display_push.iso_to_unix(period.get("end")),
        }],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出账单和套餐接口的原始 JSON")
    parser.add_argument("--auth-file", default="~/.grok/auth.json", help="Grok CLI 凭据文件路径")
    display_push.add_arguments(parser)
    args = parser.parse_args()
    try:
        if args.push:
            display_push.run(args, lambda: to_display(fetch_usage(load_credentials(args.auth_file))))
            return
        data = fetch_usage(load_credentials(args.auth_file))
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
