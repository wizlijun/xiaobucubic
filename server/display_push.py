"""采集脚本共用：把订阅项或天气提交到显示服务 (display_server.py)。

写 token 从环境变量 DISPLAY_WRITE_TOKEN 读取，未设置时读取同目录 display.env
（由 start.sh 生成）；服务地址可用 --push URL
或环境变量 DISPLAY_SERVER_URL 指定，默认 http://127.0.0.1:8007。
"""
import json
import math
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


def add_arguments(parser, collector):
    parser.set_defaults(collector=collector)
    group = parser.add_argument_group("提交到显示服务")
    group.add_argument(
        "--push", nargs="?", metavar="URL", const=os.environ.get("DISPLAY_SERVER_URL") or DEFAULT_URL,
        help="把用量提交到显示服务，默认 $DISPLAY_SERVER_URL 或 %s" % DEFAULT_URL)
    group.add_argument(
        "--interval", type=int, default=0, metavar="SECONDS",
        help="兼容旧参数：非零时启用服务端调度，查询间隔由服务端决定")
    group.add_argument("--follow", action="store_true", help="持续轮询服务端，仅按服务端指令查询上游")


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


def request_json(base_url, path, body, method="POST", lease=None):
    url = base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = write_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    if lease:
        headers["X-Collection-Lease"] = lease
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("显示服务请求失败: HTTP %d" % exc.code) from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("无法连接显示服务 %s: %s" % (base_url, getattr(exc, "reason", exc))) from None
    except ValueError:
        raise RuntimeError("显示服务未返回有效 JSON。") from None


def push(base_url, item, path=None, lease=None):
    """提交采集结果，返回包含 collection 调度指令的响应。"""
    return request_json(base_url, path or "/v1/subscriptions/" + quote(item["id"], safe=""),
                        {k: v for k, v in item.items() if v is not None}, method="PUT", lease=lease)


def instruction(response):
    value = response.get("collection") if isinstance(response, dict) else None
    if not isinstance(value, dict) or type(value.get("query_now")) is not bool:
        raise RuntimeError("显示服务未返回有效的 collection 调度指令，暂停上游查询。")
    delay = value.get("poll_after_seconds")
    if (isinstance(delay, bool) or not isinstance(delay, (int, float)) or
            not math.isfinite(delay) or not 1 <= delay <= 86400):
        raise RuntimeError("服务端轮询间隔无效，暂停上游查询。")
    if value["query_now"] and (not isinstance(value.get("lease_id"), str) or not value["lease_id"]):
        raise RuntimeError("服务端未授予有效采集租约，暂停上游查询。")
    return value


def summary(item):
    parts = []
    for w in item.get("windows") or []:
        pct = w.get("used_percent")
        parts.append("%s 已用 %s" % (w["label"], "--" if pct is None else "%g%%" % pct))
    return "%s (%s)" % (item["name"], "，".join(parts) or "无用量窗口")


def run(args, collect, path=None, describe=summary):
    """持续模式首次也先询问；上传后遵循返回指令，控制服务断线时不访问上游。"""
    if not getattr(args, "follow", False) and not args.interval:
        try:
            item = collect()
            push(args.push, item, path)
            print("%s 已提交 %s" % (time.strftime("%H:%M:%S"), describe(item)), flush=True)
        except RuntimeError as exc:
            sys.exit(str(exc))
        return
    control_path = "/v1/collectors/" + quote(args.collector, safe="")
    while True:
        delay = 15
        lease = None
        try:
            command = instruction(request_json(args.push, control_path + "/poll", {}))
            if command["query_now"]:
                lease = command["lease_id"]
                item = collect()
                command = instruction(push(args.push, item, path, lease=lease))
                lease = None
                print("%s 已提交 %s" % (time.strftime("%H:%M:%S"), describe(item)), flush=True)
            delay = command["poll_after_seconds"]
        except (RuntimeError, OSError) as exc:
            print("%s 采集 %s: %s" % (time.strftime("%H:%M:%S"), args.collector, exc), file=sys.stderr, flush=True)
            if lease:
                try:
                    command = instruction(request_json(args.push, control_path + "/failure", {"lease_id": lease}))
                    delay = command["poll_after_seconds"]
                except RuntimeError as report_error:
                    print("无法报告采集失败: %s" % report_error, file=sys.stderr, flush=True)
        time.sleep(delay)
