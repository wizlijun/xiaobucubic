"""采集脚本共用：把订阅项或天气提交到显示服务 (display_server.py)。

写 token 从环境变量 DISPLAY_WRITE_TOKEN 读取，未设置时读取同目录 display.env
（由 start.sh 生成）；服务地址可用 --push URL
或环境变量 DISPLAY_SERVER_URL 指定，默认 http://127.0.0.1:8007。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

DEFAULT_URL = "http://127.0.0.1:8007"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "display.env")


def add_arguments(parser):
    group = parser.add_argument_group("提交到显示服务")
    group.add_argument(
        "--push", nargs="?", metavar="URL", const=os.environ.get("DISPLAY_SERVER_URL") or DEFAULT_URL,
        help="把用量提交到显示服务，默认 $DISPLAY_SERVER_URL 或 %s" % DEFAULT_URL)
    group.add_argument(
        "--interval", type=int, default=0, metavar="SECONDS",
        help="与 --push 一起使用：每隔 SECONDS 秒重新采集并提交，单次失败不退出")


def iso_to_unix(value):
    """ISO 时间或 Unix 时间戳 → Unix 秒；无法解析返回 None。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 1e11 else value)
    # 去掉小数秒，兼容 Python 3.9 的 fromisoformat
    text = re.sub(r"\.\d+", "", str(value).replace("Z", "+00:00"))
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def window_label(minutes):
    """窗口时长 → 终端上的短标签，如 300 → 5小时，10080 → 7天。"""
    if not minutes:
        return None
    if minutes % 1440 == 0:
        return "%d天" % (minutes // 1440)
    if minutes % 60 == 0:
        return "%d小时" % (minutes // 60)
    return "%d分钟" % minutes


def write_token():
    token = os.environ.get("DISPLAY_WRITE_TOKEN", "").strip()
    if token or not os.path.exists(ENV_FILE):
        return token
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            key, _, value = line.strip().partition("=")
            if key.strip() == "DISPLAY_WRITE_TOKEN":
                return value.strip().strip("'\"")
    return ""


def push(base_url, item, path=None):
    """默认提交到 /v1/subscriptions/<id>；天气等其他数据传入 path。"""
    url = base_url.rstrip("/") + (path or "/v1/subscriptions/" + quote(item["id"], safe=""))
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = write_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps({k: v for k, v in item.items() if v is not None}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError("提交到显示服务失败: HTTP %d %s" % (exc.code, detail)) from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("无法连接显示服务 %s: %s" % (base_url, getattr(exc, "reason", exc))) from None


def summary(item):
    parts = []
    for w in item.get("windows") or []:
        pct = w.get("used_percent")
        parts.append("%s 已用 %s" % (w["label"], "--" if pct is None else "%g%%" % pct))
    return "%s (%s)" % (item["name"], "，".join(parts) or "无用量窗口")


def run(args, collect, path=None, describe=summary):
    """collect() 返回要提交的数据。单次模式失败即退出；循环模式记录错误后继续，不提交伪数据。"""
    while True:
        try:
            item = collect()
            push(args.push, item, path)
            print("%s 已提交 %s" % (time.strftime("%H:%M:%S"), describe(item)))
        except RuntimeError as exc:
            if not args.interval:
                sys.exit(str(exc))
            print("%s %s" % (time.strftime("%H:%M:%S"), exc), file=sys.stderr)
        if not args.interval:
            return
        sys.stdout.flush()
        time.sleep(args.interval)
