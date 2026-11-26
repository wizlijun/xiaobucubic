#!/usr/bin/env python3
"""智能终端显示数据服务（schema_version 1），仅依赖 Python 标准库。

终端只读:
    GET    /v1/display                  配置了读 token 时需 Authorization: Bearer <token>
采集脚本写入（需写 token；经 frp 转发后所有请求都来自本机，因此不能按来源 IP 放行）:
    PUT    /v1/subscriptions/<id>       提交/覆盖一个订阅的用量
    DELETE /v1/subscriptions/<id>
    PUT    /v1/messages                 用数组整体替换提醒（最多 12 条）
    POST   /v1/messages                 追加一条提醒；带已有 id 时原位更新
    DELETE /v1/messages[/<id>]          清空全部或删除一条提醒
    GET    /v1/messages                 查看当前有效提醒
机器人推送（消息 token DISPLAY_MESSAGE_TOKEN，只能管理自己推送的提醒）:
    POST   /v1/messages                 推送一条提醒，未给有效期时默认 24 小时，最长 7 天
    DELETE /v1/messages/<id>            撤回自己推送的提醒
    GET    /v1/messages                 查看自己推送且仍有效的提醒
    PUT    /v1/weather                  覆盖天气
    DELETE /v1/weather
    PUT    /v1/energy                   提交/覆盖个人能量（null 表示清空）
    DELETE /v1/energy
    GET    /healthz                     运行状态，含当前采集间隔

扩展字段（终端忽略）:
    订阅 order      主页排序，越小越靠前；默认 claude / codex / grok / gemini 在前
    提醒 id         便于更新、删除；未提供时由服务生成
    提醒 expires_at 到时后服务端不再下发（终端自身不会删除到期提醒）
    提醒 ttl_seconds 有效期秒数，服务端换算为 expires_at，与 expires_at 二选一
    提醒 sender     bot 表示由消息 token 推送
    提醒 updated_at 服务收到该提醒的时间
    天气 condition_now / forecast_hours  当前天气 / condition 所依据的预报时长
    天气 pressure_hpa   当前海平面气压，单位 hPa
    <字段>_utc      每个 *_at 时间戳都附带一份 UTC 时间，如 updated_at_utc: "2026-10-22T11:09:59Z"

按需采集: 各采集器通过 POST /v1/collectors/<id>/poll 询问服务端是否需要查询。
    默认有终端读取时每 600 秒刷新；180 秒没有读取则暂停上游查询。
    暂停或等待刷新时仍每 15 秒轮询，终端重新访问且缓存到期时获得查询指令。
    PUT 用量/天气的响应包含 collection 指令；失败通过 /failure 报告并退避。
    调度轮询与上传不计为终端访问，失败保留上一次成功数据。

数据保存在 JSON 文件中，重启后保留；各数据源的 updated_at 原样保存，不随响应刷新。

用法:
    ./start.sh                          # 先启动 frpc 再启动本服务，token 自动生成在 display.env
    DISPLAY_READ_TOKEN=xxx DISPLAY_WRITE_TOKEN=yyy DISPLAY_MESSAGE_TOKEN=zzz ./display_server.py
    ./display_server.py --host 0.0.0.0 --port 8007 --state display_state.json
"""
import argparse
import hmac
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

SCHEMA_VERSION = 1
MAX_BODY = 64 * 1024
MAX_RESPONSE = 24 * 1024
MAX_MESSAGES = 12
MAX_WINDOWS = 2
MIN_TTL = 60
BOT_DEFAULT_TTL = 24 * 3600
BOT_MAX_TTL = 7 * 24 * 3600
DEFAULT_ORDER = ("energy", "claude", "codex", "grok", "gemini", "bandwagon")
SOURCES = ("official", "manual", "estimated", "unknown")
ENERGY_TRENDS = ("charging", "draining", "steady")
ENERGY_TREND_LABELS = {"charging": "回血中", "draining": "消耗中", "steady": "平稳"}
ENERGY_MIN_TTL = 60
ENERGY_MAX_TTL = 7 * 24 * 3600
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE = os.path.join(BASE_DIR, "display_state.json")
COLLECTORS = {
    "claude": "claude_usage.py",
    "codex": "codex_usage.py",
    "grok": "grok_usage.py",
    "gemini": "gemini_usage.py",
    "bandwagon": "bandwagon_usage.py",
    "weather": "weather_shenzhen.py",
    "energy": "hp_usage.py",
}
COLLECT_TIMEOUT = 90
COLLECT_TIMEOUTS = {"energy": 300}  # HP 每日首轮要拉 28 天心率基线，约 2.5 分钟


class BadRequest(ValueError):
    status = 400


class Conflict(BadRequest):
    status = 409


def _text(obj, key, limit, required=False, default=None):
    value = obj.get(key)
    if value is not None and not isinstance(value, str):
        raise BadRequest("%s 必须是字符串" % key)
    value = (value or "").strip()
    if not value:
        if required:
            raise BadRequest("缺少 %s" % key)
        return default
    return value[:limit]


def _number(obj, key, lo=None, hi=None):
    """数字字段，缺失为 null；超出范围时截断到边界。"""
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BadRequest("%s 必须是数字或 null" % key)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return int(value) if float(value).is_integer() else round(value, 1)


def _timestamp(obj, key):
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise BadRequest("%s 必须是 Unix 秒" % key)
    if value > 1e11:
        raise BadRequest("%s 看起来是毫秒，请改用 Unix 秒" % key)
    return int(value)


def _check_id(value, what):
    if not isinstance(value, str) or not ID_RE.match(value):
        raise BadRequest("%s 只能包含字母、数字、_ . -，长度 1–64" % what)
    return value


def clean_window(body):
    if not isinstance(body, dict):
        raise BadRequest("windows 的每一项必须是对象")
    item = {
        "label": _text(body, "label", 16, required=True),
        "used_percent": _number(body, "used_percent", lo=0),
        "reset_at": _timestamp(body, "reset_at"),
    }
    # 可选流量窗口：字节数保持整数精度，剩余量由服务端计算。
    if any(key in body for key in ("total_bytes", "used_bytes", "remaining_bytes")):
        for key in ("total_bytes", "used_bytes"):
            value = body.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2**53 - 1:
                raise BadRequest("%s 必须是 0–2^53-1 的整数字节数" % key)
            item[key] = value
        if not item["total_bytes"]:
            raise BadRequest("total_bytes 必须大于 0")
        remaining = max(0, item["total_bytes"] - item["used_bytes"])
        if "remaining_bytes" in body:
            value = body["remaining_bytes"]
            if isinstance(value, bool) or not isinstance(value, int) or value != remaining:
                raise BadRequest("remaining_bytes 必须等于 max(0, total_bytes - used_bytes)")
        item["remaining_bytes"] = remaining
        item["used_percent"] = round(item["used_bytes"] / item["total_bytes"] * 100, 1)
    return item


def clean_subscription(sub_id, body, now):
    if not isinstance(body, dict):
        raise BadRequest("订阅必须是 JSON 对象")
    if body.get("id") not in (None, sub_id):
        raise BadRequest("请求体 id 与路径不一致")
    source = body.get("source") or "unknown"
    if source not in SOURCES:
        raise BadRequest("source 必须是 %s 之一" % " / ".join(SOURCES))
    windows = body.get("windows") or []
    if not isinstance(windows, list) or len(windows) > MAX_WINDOWS:
        raise BadRequest("windows 必须是数组，最多 %d 个窗口" % MAX_WINDOWS)
    item = {
        "id": sub_id,
        "name": _text(body, "name", 40, default=sub_id),
        "source": source,
        # 采集脚本应填真实采集时间；缺省时以服务收到的时间代替。
        "updated_at": _timestamp(body, "updated_at") or now,
        "windows": [clean_window(w) for w in windows],
    }
    for key in ("plan", "note"):
        value = _text(body, key, 80)
        if value:
            item[key] = value
    order = body.get("order")
    if order is not None:
        if isinstance(order, bool) or not isinstance(order, int):
            raise BadRequest("order 必须是整数")
        item["order"] = order
    return item


def clean_message(body, now, bot=False):
    if not isinstance(body, dict):
        raise BadRequest("提醒必须是 JSON 对象")
    priority = body.get("priority") or "normal"
    if priority not in ("normal", "high"):
        raise BadRequest("priority 必须是 normal 或 high")
    message = {
        "id": _check_id(body["id"], "提醒 id") if body.get("id") is not None else uuid.uuid4().hex[:12],
        "title": _text(body, "title", 40, default="提醒"),
        "text": _text(body, "text", 180, required=True),
        "priority": priority,
        "updated_at": now,
    }
    due_at = _timestamp(body, "due_at")
    if due_at is not None:
        message["due_at"] = due_at
    expires_at = _timestamp(body, "expires_at")
    ttl = body.get("ttl_seconds")
    if ttl is not None:
        if expires_at is not None:
            raise BadRequest("ttl_seconds 与 expires_at 只能二选一")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < MIN_TTL:
            raise BadRequest("ttl_seconds 必须是不小于 %d 的整数秒" % MIN_TTL)
        expires_at = now + ttl
    if expires_at is None and bot:
        expires_at = now + BOT_DEFAULT_TTL
    if expires_at is not None:
        if expires_at <= now:
            raise BadRequest("有效期已过，expires_at 必须晚于当前时间")
        if bot and expires_at > now + BOT_MAX_TTL:
            raise BadRequest("机器人推送的提醒有效期最长 %d 天" % (BOT_MAX_TTL // 86400))
        message["expires_at"] = expires_at
    if bot:
        message["sender"] = "bot"
    return message


def clean_weather(body, now):
    if not isinstance(body, dict):
        raise BadRequest("天气必须是 JSON 对象或 null")
    return {
        "city": _text(body, "city", 20),
        "condition": _text(body, "condition", 20),
        "temperature_c": _number(body, "temperature_c"),
        "feels_like_c": _number(body, "feels_like_c"),
        "low_c": _number(body, "low_c"),
        "high_c": _number(body, "high_c"),
        "humidity_percent": _number(body, "humidity_percent", 0, 100),
        "rain_percent": _number(body, "rain_percent", 0, 100),
        "wind_kmh": _number(body, "wind_kmh", lo=0),
        "pressure_hpa": _number(body, "pressure_hpa", lo=0),
        "source": _text(body, "source", 40),
        "updated_at": _timestamp(body, "updated_at") or now,
        # 扩展: 当前天气与预报时长（condition 为预报天气时使用）
        "condition_now": _text(body, "condition_now", 20),
        "forecast_hours": _number(body, "forecast_hours", 0, 240),
    }


WEEKLY_ITEMS = ("sleep", "late", "exercise_low", "sedentary", "exercise_high", "stress", "drain", "recovery")


def _clean_weekly(value):
    """HP 周限（hp_weekly），缺失为 None；字段非法时 400，不显示一个错误的数。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BadRequest("weekly 必须是 JSON 对象或 null")
    remaining = _number(value, "remaining_percent", 0, 100)
    reset_at = _timestamp(value, "reset_at")
    if remaining is None or reset_at is None:
        raise BadRequest("weekly 需要 remaining_percent 和 reset_at")
    out = {"remaining_percent": remaining, "reset_at": reset_at}
    debt = _number(value, "debt_hours", 0, 1000)
    if debt is not None:
        out["debt_hours"] = debt
    top = value.get("top")
    if top is not None:
        if top not in WEEKLY_ITEMS:
            raise BadRequest("weekly.top 必须是 %s 之一" % " / ".join(WEEKLY_ITEMS))
        out["top"] = top
    items = value.get("items")
    if items is not None:
        if not isinstance(items, dict) or any(k not in WEEKLY_ITEMS for k in items):
            raise BadRequest("weekly.items 只能包含 %s" % " / ".join(WEEKLY_ITEMS))
        out["items"] = {k: _number(items, k, 0, 1000) for k in WEEKLY_ITEMS if items.get(k) is not None}
    return out


def clean_energy(body, now):
    if not isinstance(body, dict):
        raise BadRequest("能量必须是 JSON 对象或 null")
    source = body.get("source") or "unknown"
    if source not in SOURCES:
        raise BadRequest("source 必须是 %s 之一" % " / ".join(SOURCES))
    item = {
        "name": _text(body, "name", 40, default="HP"),
        "level_percent": _number(body, "level_percent", 0, 100),
        "source": source,
        "updated_at": _timestamp(body, "updated_at") or now,
    }
    status = _text(body, "status", 16)
    if status:
        item["status"] = status
    trend = body.get("trend")
    if trend is not None:
        if not isinstance(trend, str) or trend not in ENERGY_TRENDS:
            raise BadRequest("trend 必须是 %s 之一" % " / ".join(ENERGY_TRENDS))
        item["trend"] = trend
    note = _text(body, "note", 80)
    if note:
        item["note"] = note
    ttl = body.get("stale_after_seconds")
    if ttl is not None:
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not ENERGY_MIN_TTL <= ttl <= ENERGY_MAX_TTL:
            raise BadRequest("stale_after_seconds 必须是 %d–%d 的整数秒" % (ENERGY_MIN_TTL, ENERGY_MAX_TTL))
        item["stale_after_seconds"] = ttl
    weekly = _clean_weekly(body.get("weekly"))
    if weekly:
        item["weekly"] = weekly
    return item


def _active(messages, now):
    return [m for m in messages if not m.get("expires_at") or m["expires_at"] > now]


def utc(timestamp):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def with_utc(value):
    """复制一份数据，为每个 *_at 的 Unix 秒字段附加 *_utc；存储中不保存这些字段。"""
    if isinstance(value, list):
        return [with_utc(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        out[key] = with_utc(item)
        if key.endswith("_at") and isinstance(item, int) and not isinstance(item, bool):
            out[key + "_utc"] = utc(item)
    return out


def energy_to_subscription(energy, stale_after, now):
    """将顶层 energy 投影为通用订阅卡片，现有所有设备无需升级即可动态显示。"""
    if not isinstance(energy, dict):
        return None
    base = energy.get("status") or ENERGY_TREND_LABELS.get(energy.get("trend")) or "当前"
    note = energy.get("note")
    label = ("%s · %s" % (base, note)) if (note and len(base) + len(note) + 3 <= 16) else base
    level = energy.get("level_percent")
    used = None
    if level is not None:
        raw_used = round(max(0.0, min(100.0, 100.0 - float(level))), 1)
        used = int(raw_used) if float(raw_used).is_integer() else raw_used
    updated_at = energy.get("updated_at")
    energy_ttl = energy.get("stale_after_seconds")
    # 客户端按全局 stale_after 判断是否过期；若能量仍在自身独立有效期内，保持未过期状态。
    if updated_at and energy_ttl and 0 <= now - updated_at <= energy_ttl and now - updated_at > stale_after:
        updated_at = now
    item = {
        "id": "energy",
        "name": energy.get("name") or "HP",
        "source": energy.get("source") or "unknown",
        "updated_at": updated_at or now,
        "windows": [{
            "label": label[:16],
            "used_percent": used,
            "reset_at": None,
        }],
    }
    weekly = energy.get("weekly")
    if isinstance(weekly, dict) and weekly.get("remaining_percent") is not None:
        # 标签「7天」：设备显示为「周限」，iPhone 隐藏标签，与其它卡片的周额度一致。
        item["windows"].append({"label": "7天", "used_percent": 100 - weekly["remaining_percent"],
                                "reset_at": weekly.get("reset_at")})
    if note:
        item["note"] = note
    return item


def build_display(data, stale_after, now):
    def order(sub):
        default = DEFAULT_ORDER.index(sub["id"]) if sub["id"] in DEFAULT_ORDER else len(DEFAULT_ORDER)
        return (sub.get("order", default), sub["id"])

    subs = dict(data["subscriptions"])
    energy = data.get("energy")
    if energy is not None and "energy" not in subs:
        subs["energy"] = energy_to_subscription(energy, stale_after, now)

    display = with_utc({
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "stale_after_seconds": stale_after,
        "subscriptions": sorted(subs.values(), key=order),
        "energy": energy,
        "messages": _active(data["messages"], now)[:MAX_MESSAGES],
        "weather": data["weather"],
    })
    body = json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # 终端要求正文不超过 24 KB，超出时从末尾丢弃提醒。
    while len(body) > MAX_RESPONSE and display["messages"]:
        display["messages"].pop()
        body = json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body


def log(message):
    print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message), file=sys.stderr, flush=True)


class Scheduler:
    """服务端统一控制各数据源；单调时钟计时，短租约防止重复查询。"""

    def __init__(self, min_interval=600, max_interval=3600,
                 clock=time.monotonic, wall_clock=time.time, idle_after=180,
                 poll_interval=15, initial=None):
        self.interval = min_interval
        self.max_interval = max_interval
        self.clock = clock
        self.wall_clock = wall_clock
        self.idle_after = idle_after
        self.poll_interval = poll_interval
        self.lock = threading.Lock()
        self.last_request = None
        self.last_request_at = None
        self.last_poll_at = {}
        now, wall = clock(), wall_clock()
        self.sources = {}
        for name in COLLECTORS:
            updated = (initial or {}).get(name)
            age = max(0, wall - updated) if isinstance(updated, (int, float)) else min_interval
            self.sources[name] = {
                "due": now + max(0, min_interval - age),
                "lease": None, "lease_until": 0, "failures": 0,
            }

    def on_request(self):
        with self.lock:
            self.last_request = self.clock()
            self.last_request_at = int(self.wall_clock())

    def _active(self, now):
        return self.last_request is not None and now - self.last_request < self.idle_after

    def _failed(self, source, now):
        source["lease"] = None
        source["failures"] += 1
        source["due"] = now + min(self.max_interval, self.interval * 2 ** min(source["failures"] - 1, 10))

    def _instruction(self, name, now, claim=False):
        source = self.sources[name]
        if source["lease"] and now >= source["lease_until"]:
            self._failed(source, now)
        active = self._active(now)
        query_now = False
        if not active:
            reason = "no_clients"
        elif source["lease"]:
            reason = "in_progress"
        elif source["due"] > now:
            reason = "retry_backoff" if source["failures"] else "fresh"
        else:
            reason = "due"
            if claim:
                source["lease"] = uuid.uuid4().hex
                source["lease_until"] = now + COLLECT_TIMEOUTS.get(name, COLLECT_TIMEOUT)
                query_now = True
        due = max(source["due"], source["lease_until"] if source["lease"] else now)
        delay = max(0, math.ceil(due - now)) if active else None
        return {
            "collector": name,
            "query_now": query_now,
            "paused": not active,
            "reason": reason,
            "poll_after_seconds": min(self.poll_interval, max(1, delay)) if delay is not None else self.poll_interval,
            "next_query_after_seconds": delay,
            "lease_id": source["lease"] if query_now else None,
        }

    def poll(self, name):
        with self.lock:
            self.last_poll_at[name] = int(self.wall_clock())
            return self._instruction(name, self.clock(), claim=True)

    def submit(self, name, lease, save):
        with self.lock:
            source = self.sources[name]
            now = self.clock()
            if lease and (source["lease"] != lease or now >= source["lease_until"]):
                raise Conflict("采集租约已失效，请重新轮询")
            save()
            source["due"] = now + self.interval
            source["failures"] = 0
            if lease:
                source["lease"] = None
            return self._instruction(name, now)

    def failure(self, name, lease):
        with self.lock:
            source = self.sources[name]
            if not lease or source["lease"] != lease:
                raise Conflict("采集租约已失效，请重新轮询")
            self._failed(source, self.clock())
            return self._instruction(name, self.clock())

    def status(self):
        with self.lock:
            return {
                "collect_interval_seconds": self.interval,
                "collection_paused": not self._active(self.clock()),
                "collector_poll_seconds": self.poll_interval,
                "idle_after_seconds": self.idle_after,
                "last_display_request_utc": utc(self.last_request_at) if self.last_request_at else None,
                "last_collector_poll_utc": {name: utc(at) for name, at in self.last_poll_at.items()},
            }


def supervise_collector(name, push_url, stop):
    """常驻采集器只根据 HTTP 指令访问上游；退出后重启，服务关闭时回收子进程。"""
    while not stop.is_set():
        proc = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", os.path.join(BASE_DIR, COLLECTORS[name]),
                 "--push", push_url, "--follow"], stdin=subprocess.DEVNULL,
            )
            while not stop.wait(1):
                if proc.poll() is not None:
                    log("采集器 %s 退出 (%s)，15 秒后重启" % (name, proc.returncode))
                    break
        except OSError:
            log("无法启动采集器 %s，15 秒后重试" % name)
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        stop.wait(15)


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"subscriptions": {}, "energy": None, "messages": [], "weather": None}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))

    def read(self, fn):
        with self.lock:
            return fn(self.data)

    def write(self, fn):
        with self.lock:
            result = fn(self.data)
            # 先写临时文件再替换，避免写到一半崩溃时损坏状态文件。
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.path)), prefix=".display_state.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            except BaseException:
                os.unlink(tmp)
                raise
            return result


class Handler(BaseHTTPRequestHandler):
    server_version = "DisplayServer/1"
    protocol_version = "HTTP/1.1"

    def log_request(self, code="-", size="-"):
        route = self._route()
        if (code == 200 and self.command == "POST" and route and
                len(route) == 3 and route[0] == "collectors" and route[2] == "poll"):
            return  # 正常心跳不刷日志，保留失败及实际数据更新日志。
        super().log_request(code, size)

    def _send(self, status, body):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send(status, {"error": message})

    def _token(self):
        header = self.headers.get("Authorization", "")
        return header[7:].strip() if header[:7].lower() == "bearer " else ""

    def _matches(self, expected):
        return bool(expected) and hmac.compare_digest(self._token().encode(), expected.encode())

    def _route(self):
        parts = [unquote(p) for p in urlsplit(self.path).path.split("/") if p]
        return parts[1:] if parts[:1] == ["v1"] else None

    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/")
        scheduler = self.server.scheduler
        if path == "/healthz":
            return self._send(200, dict({"ok": True}, **(scheduler.status() if scheduler else {})))
        cfg = self.server.config
        if path == "/v1/messages":
            role = self._role()
            if not role:
                return self._error(401, "需要写 token 或消息 token")
            now = int(time.time())
            messages = self.server.store.read(lambda data: [
                m for m in _active(data["messages"], now) if role == "admin" or m.get("sender") == "bot"])
            return self._send(200, with_utc({"now": now, "messages": messages,
                                              "capabilities": {"safe_create": True}}))
        if path != "/v1/display":
            return self._error(404, "not found")
        # 写 token 可读，只读 token 不可写。
        if cfg["read_token"] and not (self._matches(cfg["read_token"]) or self._matches(cfg["write_token"])):
            return self._error(401, "unauthorized")
        if scheduler:
            scheduler.on_request()
        now = int(time.time())
        self._send(200, self.server.store.read(lambda data: build_display(data, cfg["stale_after"], now)))

    def do_PUT(self):
        self._write()

    def do_POST(self):
        self._write()

    def do_DELETE(self):
        self._write()

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            raise BadRequest("请求体长度无效或超过 %d 字节" % MAX_BODY)
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, ValueError):
            raise BadRequest("请求体不是有效的 UTF-8 JSON") from None

    def _write(self):
        cfg = self.server.config
        try:
            body = self._read_json() if self.command in ("PUT", "POST") else None
        except BadRequest as exc:
            return self._error(400, str(exc))
        role = self._role()
        if not role:
            return self._error(403 if self._matches(cfg["read_token"]) else 401, "需要写 token")

        route = self._route()
        # 消息 token 只能推送提醒、撤回自己推送的提醒。
        if role == "bot" and not (route and route[0] == "messages" and (
                (self.command == "POST" and len(route) == 1) or (self.command == "DELETE" and len(route) == 2))):
            return self._error(403, "消息 token 只能 POST /v1/messages 或 DELETE /v1/messages/<id>")
        handler = {
            ("collectors", 2): self._collector,
            ("subscriptions", 1): self._subscription,
            ("energy", 0): self._energy,
            ("messages", 0): self._messages,
            ("messages", 1): self._messages,
            ("weather", 0): self._weather,
        }.get((route[0], len(route) - 1) if route else None)
        if not handler:
            return self._error(404, "not found")
        try:
            status, result = handler(route[1:], body, int(time.time()), role)
        except BadRequest as exc:
            return self._error(exc.status, str(exc))
        self._send(status, result)

    def _role(self):
        cfg = self.server.config
        if self._matches(cfg["write_token"]):
            return "admin"
        if self._matches(cfg["message_token"]):
            return "bot"
        return None

    def _subscription(self, args, body, now, role):
        sub_id = _check_id(args[0], "订阅 id")
        store = self.server.store
        if self.command == "PUT":
            item = clean_subscription(sub_id, body, now)
            save = lambda: store.write(lambda data: data["subscriptions"].__setitem__(sub_id, item))
            instruction = self._save_collection(sub_id, save)
            return 200, dict(item, collection=instruction)
        if self.command == "DELETE":
            removed = store.write(lambda data: data["subscriptions"].pop(sub_id, None))
            return (200, {"deleted": sub_id}) if removed else (404, {"error": "订阅不存在"})
        return 405, {"error": "method not allowed"}

    def _save_collection(self, name, save):
        scheduler = self.server.scheduler
        if scheduler and name in scheduler.sources:
            return scheduler.submit(name, self.headers.get("X-Collection-Lease"), save)
        save()
        return None

    def _collector(self, args, body, now, role):
        name, action = args
        scheduler = self.server.scheduler
        if not scheduler or name not in scheduler.sources or action not in ("poll", "failure"):
            return 404, {"error": "未知采集器或调度操作"}
        if self.command != "POST":
            return 405, {"error": "method not allowed"}
        if not isinstance(body, dict):
            raise BadRequest("调度请求必须是 JSON 对象")
        instruction = (scheduler.poll(name) if action == "poll" else
                       scheduler.failure(name, body.get("lease_id")))
        return 200, {"collection": instruction}

    def _messages(self, args, body, now, role):
        store = self.server.store
        bot = role == "bot"
        if args:
            if self.command != "DELETE":
                return 405, {"error": "method not allowed"}
            msg_id = args[0]

            def delete(data):
                kept = [m for m in data["messages"]
                        if m["id"] != msg_id or (bot and m.get("sender") != "bot")]
                removed = len(kept) != len(data["messages"])
                data["messages"] = kept
                return removed

            return (200, {"deleted": msg_id}) if store.write(delete) else (404, {"error": "提醒不存在"})

        if self.command == "DELETE":
            store.write(lambda data: data.__setitem__("messages", []))
            return 200, {"messages": []}
        if self.command == "PUT":
            if isinstance(body, dict):
                body = body.get("messages")
            if not isinstance(body, list):
                raise BadRequest("请提交提醒数组，或 {\"messages\": [...]}")
            messages = [clean_message(m, now) for m in body]
            if len(messages) > MAX_MESSAGES:
                raise BadRequest("提醒最多 %d 条" % MAX_MESSAGES)
            if len({m["id"] for m in messages}) != len(messages):
                raise BadRequest("提醒 id 重复")
            store.write(lambda data: data.__setitem__("messages", messages))
            return 200, {"messages": messages}

        message = clean_message(body, now, bot=bot)
        safe_create = body.get("safe_create", False)
        if not isinstance(safe_create, bool):
            raise BadRequest("safe_create 必须是布尔值")

        def upsert(data):
            messages = _active(data["messages"], now)
            for i, existing in enumerate(messages):
                if existing["id"] == message["id"]:
                    if bot and existing.get("sender") != "bot":
                        raise Conflict("该 id 已被非机器人提醒占用，请换一个 id")
                    messages[i] = message
                    break
            else:
                if len(messages) >= MAX_MESSAGES:
                    # An opted-in bot must never evict another reminder. Check
                    # capacity under the same store lock as the insertion.
                    if bot and safe_create:
                        raise Conflict("提醒已满，safe_create 不会替换已有提醒")
                    # 已满时丢弃最早的一条；机器人只会挤掉自己推送的提醒。
                    victims = [m for m in messages if m.get("sender") == "bot"] if bot else messages
                    if not victims:
                        raise Conflict("提醒已满 %d 条，且都不是机器人推送的" % MAX_MESSAGES)
                    messages.remove(victims[0])
                messages.append(message)
            data["messages"] = messages

        store.write(upsert)
        return 200, with_utc(message)

    def _weather(self, args, body, now, role):
        store = self.server.store
        if self.command == "PUT":
            weather = clean_weather(body, now) if body is not None else None
            save = lambda: store.write(lambda data: data.__setitem__("weather", weather))
            instruction = self._save_collection("weather", save)
            return 200, {"weather": weather, "collection": instruction}
        if self.command == "DELETE":
            store.write(lambda data: data.__setitem__("weather", None))
            return 200, {"weather": None}
        return 405, {"error": "method not allowed"}

    def _energy(self, args, body, now, role):
        store = self.server.store
        if self.command == "PUT":
            energy = clean_energy(body, now) if body is not None else None
            save = lambda: store.write(lambda data: data.__setitem__("energy", energy))
            instruction = self._save_collection("energy", save)
            return 200, {"energy": with_utc(energy), "collection": instruction}
        if self.command == "DELETE":
            store.write(lambda data: data.__setitem__("energy", None))
            return 200, {"energy": None}
        return 405, {"error": "method not allowed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8007, help="监听端口 (默认 8007)")
    parser.add_argument("--state", default=DEFAULT_STATE, help="数据保存文件 (默认脚本同目录 display_state.json)")
    parser.add_argument("--stale-after", type=int, default=900, help="stale_after_seconds，30–86400 (默认 900)")
    parser.add_argument("--min-interval", "--refresh-interval", type=int, default=600, help="有客户端时的刷新间隔秒数 (默认 600)")
    parser.add_argument("--max-interval", type=int, default=3600, help="查询失败时的最大退避秒数 (默认 3600)")
    parser.add_argument("--idle-after", type=int, default=180, help="多少秒无客户端读取后暂停上游查询 (默认 180)")
    parser.add_argument("--poll-interval", type=int, default=15, help="采集器询问调度指令的间隔秒数 (默认 15)")
    parser.add_argument("--collectors", default=",".join(COLLECTORS),
                        help="要定时运行的采集脚本，空字符串表示关闭 (默认 %(default)s)")
    args = parser.parse_args()
    if not 30 <= args.stale_after <= 86400:
        parser.error("--stale-after 必须在 30–86400 之间")
    collectors = [n.strip() for n in args.collectors.split(",") if n.strip()]
    unknown = [n for n in collectors if n not in COLLECTORS]
    if unknown:
        parser.error("未知的采集脚本: %s（可选 %s）" % (", ".join(unknown), ", ".join(COLLECTORS)))
    if not 60 <= args.min_interval <= args.max_interval <= 86400:
        parser.error("需满足 60 <= --min-interval <= --max-interval <= 86400，避免频繁请求订阅平台")
    if not 1 <= args.poll_interval <= args.idle_after <= 86400:
        parser.error("需满足 1 <= --poll-interval <= --idle-after <= 86400")

    # token 只从环境变量读取，避免出现在进程列表中。
    config = {
        "read_token": os.environ.get("DISPLAY_READ_TOKEN", "").strip(),
        "write_token": os.environ.get("DISPLAY_WRITE_TOKEN", "").strip(),
        "message_token": os.environ.get("DISPLAY_MESSAGE_TOKEN", "").strip(),
        "stale_after": args.stale_after,
    }
    if not config["write_token"]:
        sys.exit("必须设置 DISPLAY_WRITE_TOKEN（或使用 ./start.sh 自动生成）。")
    tokens = [t for t in (config["read_token"], config["write_token"], config["message_token"]) if t]
    if len(set(tokens)) != len(tokens):
        sys.exit("DISPLAY_READ_TOKEN / DISPLAY_WRITE_TOKEN / DISPLAY_MESSAGE_TOKEN 不能相同。")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.store = Store(args.state)
    server.config = config
    initial = server.store.read(lambda data: dict(
        {name: item.get("updated_at") for name, item in data["subscriptions"].items()},
        weather=(data.get("weather") or {}).get("updated_at"),
        energy=(data.get("energy") or {}).get("updated_at")))
    server.scheduler = Scheduler(args.min_interval, args.max_interval,
                                 idle_after=args.idle_after, poll_interval=args.poll_interval, initial=initial)
    stop = threading.Event()
    workers = []
    print("显示服务已启动: http://%s:%d/v1/display  状态文件: %s" % (args.host, args.port, args.state), file=sys.stderr)
    if not config["read_token"]:
        print("提示: 未设置 DISPLAY_READ_TOKEN，读取接口无需鉴权。", file=sys.stderr)
    if collectors:
        # 子进程继承环境变量中的 DISPLAY_WRITE_TOKEN，经本机地址提交。
        local_host = "127.0.0.1" if args.host in ("", "0.0.0.0", "::") else args.host
        push_url = "http://%s:%d" % (local_host, args.port)
        for name in collectors:
            worker = threading.Thread(target=supervise_collector, args=(name, push_url, stop), daemon=True)
            workers.append(worker)
            worker.start()
        log("按需采集: %s；刷新 %d 秒，空闲 %d 秒后暂停，每 %d 秒轮询指令" % (
            ", ".join(collectors), args.min_interval, args.idle_after, args.poll_interval))
    def shutdown(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=7)
        server.server_close()


if __name__ == "__main__":
    main()
