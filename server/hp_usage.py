#!/usr/bin/env python3
"""用 Oura 数据估算 HP（个人能量），可单次计算、推送，或常驻每 10 分钟一轮。

用法:
    python3 hp_usage.py                  # 计算一次，打印摘要
    python3 hp_usage.py --json           # 打印 payload
    python3 hp_usage.py --explain        # 打印当日每格明细
    python3 hp_usage.py --push --follow  # 常驻推送到显示服务
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime

import display_push
import energy_usage
import hp_model
import oura_auth
import oura_client

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hp_cache.json")
ENERGY_PATH = "/v1/energy"
STALE_AFTER = 1800
INTERVAL = 600

_PERSONAL_INFO = None  # 进程内只取一次


def log(msg):
    print("%s hp_usage: %s" % (time.strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)


def build_item(result, now):
    return energy_usage.build_payload(
        level=result.level, status=result.status, trend=result.trend, note=result.note,
        source="estimated", stale_after=STALE_AFTER, updated_at=now)


def auth_item(now):
    return energy_usage.build_payload(
        level=None, status="待授权", source="estimated", stale_after=STALE_AFTER, updated_at=now)


def _read_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("day"), str) and "hr_quiet" in data:
            return data
    except (OSError, ValueError):
        pass
    return None


def _write_cache(path, data):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".hp_cache-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cached_hr_quiet(day, fetch, path=None):
    """每个本地日只取一次基线；fetch(day) -> (hr_quiet, valid_days)。"""
    path = path or CACHE_FILE
    cached = _read_cache(path)
    if cached and cached["day"] == day.isoformat():
        return cached["hr_quiet"]
    hr_quiet, valid_days = fetch(day)
    try:
        _write_cache(path, {"day": day.isoformat(), "hr_quiet": hr_quiet, "valid_days": valid_days})
    except OSError as exc:
        log("无法写入缓存: %s" % exc)
    return hr_quiet


def _baseline_fetcher(tz):
    def fetch(day):
        rows = oura_client.fetch_baseline_hr(day, tz)
        days = {hp_model.local_date(hp_model.parse_ts(r["timestamp"]), tz)
                for r in rows if r.get("source") == "awake" and r.get("bpm") is not None}
        return hp_model.quiet_hr(rows), len(days)
    return fetch


def local_tz():
    return datetime.now().astimezone().tzinfo


def load_params(path):
    if not path:
        return hp_model.make_params()
    try:
        with open(path, encoding="utf-8") as f:
            overrides = json.load(f)
        return hp_model.make_params(overrides)
    except (OSError, ValueError) as exc:
        sys.exit("--params %s: %s" % (path, exc))


def compute_result(args, now, tz=None):
    """取数并计算，返回 Result；异常原样抛出，由调用方映射。"""
    global _PERSONAL_INFO
    tz = tz or local_tz()
    p = load_params(getattr(args, "params", None))
    data = oura_client.fetch_all(now, tz)
    if _PERSONAL_INFO is None:
        try:
            _PERSONAL_INFO = oura_client.personal_info()
        except oura_auth.AuthRequired:
            raise
        except (RuntimeError, OSError) as exc:
            log("personal_info 获取失败，继续: %s" % exc)
    if _PERSONAL_INFO:
        data["personal_info"] = _PERSONAL_INFO
    hr_quiet = cached_hr_quiet(hp_model.local_date(now, tz), _baseline_fetcher(tz))
    return hp_model.compute(now, data, hr_quiet, p, tz, age=args.age)


def cycle(args, now):
    try:
        return build_item(compute_result(args, now), now)
    except oura_auth.AuthRequired:
        return auth_item(now)
    except oura_client.RateLimited as exc:
        log("Oura 限流，本轮放弃 (retry_after=%s)" % exc.retry_after)
    except (RuntimeError, OSError) as exc:
        log("本轮放弃: %s" % exc)
    return None


def follow(args, cycle_fn, push_fn, sleep=time.sleep, clock=time.time, max_cycles=None):
    n = 0
    while True:
        now = int(clock())
        try:
            item = cycle_fn(now)
            if item is not None:
                push_fn(item)
        except Exception as exc:  # 单轮出错只记日志
            log("本轮出错: %s" % exc)
        n += 1
        if max_cycles is not None and n >= max_cycles:
            return
        sleep(INTERVAL - (clock() % INTERVAL) or INTERVAL)


def report(args, now):
    raise SystemExit("--report: not implemented yet")


def explain(result, tz):
    lines = []
    for s in result.steps:
        t = datetime.fromtimestamp(s.start, tz).strftime("%H:%M")
        hr = "--" if s.hr is None else "%.0f" % s.hr
        met = "--" if s.met is None else "%.1f" % s.met
        lines.append("%s %s hr=%s met=%s rate=%.2f hp=%.1f" % (t, s.kind, hr, met, s.rate, s.hp))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出将提交的 JSON")
    parser.add_argument("--explain", action="store_true", help="打印当日每格的 时间 kind hr met rate hp")
    parser.add_argument("--params", metavar="FILE", help="JSON 文件，覆盖模型参数")
    parser.add_argument("--now", metavar="ISO", help="调试用：指定计算时刻")
    parser.add_argument("--age", type=int, default=None, help="personal_info 无 age 时使用")
    parser.add_argument("--report", action="store_true", help="校准报告")
    parser.add_argument("--days", type=int, default=28, help="--report 的天数 (默认 28)")
    display_push.add_arguments(parser, "energy")
    args = parser.parse_args(argv)

    now = int(time.time())
    if args.now:
        try:
            now = hp_model.parse_ts(args.now)
        except ValueError:
            sys.exit("--now: 无法解析 %r" % args.now)
    load_params(args.params)  # 尽早校验
    if args.report:
        print(report(args, now))
        return
    if args.push and args.follow:
        def push_fn(item):
            display_push.push(args.push, item, path=ENERGY_PATH)
            log("已提交 %s" % energy_usage.summary(item))
        try:
            follow(args, lambda t: cycle(args, t), push_fn)
        except KeyboardInterrupt:
            pass
        return
    if args.explain:
        try:
            res = compute_result(args, now)
        except (RuntimeError, OSError) as exc:
            sys.exit(str(exc))
        print(explain(res, local_tz()))
        item = build_item(res, now)
    else:
        item = cycle(args, now)
        if item is None:
            sys.exit("本轮未取得数据，详见 stderr。")
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    else:
        print(energy_usage.summary(item))
    if args.push:
        try:
            display_push.push(args.push, item, path=ENERGY_PATH)
        except RuntimeError as exc:
            sys.exit(str(exc))


if __name__ == "__main__":
    main()
