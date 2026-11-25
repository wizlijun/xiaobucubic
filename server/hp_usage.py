#!/usr/bin/env python3
"""用 Oura 数据估算 HP（个人能量），可单次计算、推送，或常驻按显示服务调度计算。

用法:
    python3 hp_usage.py                  # 计算一次，打印摘要
    python3 hp_usage.py --json           # 打印 payload
    python3 hp_usage.py --explain        # 打印当日每格明细
    python3 hp_usage.py --push --follow  # 常驻：由 display_server 调度，有终端读取时才访问 Oura
"""
from __future__ import annotations

import argparse
import json
import statistics
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

import display_push
import energy_usage
import hp_model
import oura_auth
import oura_client

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hp_cache.json")
ENERGY_PATH = "/v1/energy"
STALE_AFTER = 1800

_PERSONAL_INFO = None  # 进程内只取一次


def log(msg):
    print("%s hp_usage: %s" % (time.strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)


def build_item(result, now):
    return energy_usage.build_payload(
        level=result.level, status=result.line or result.status, trend=result.trend,
        note=None if result.line else result.note,
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
    try:
        hr_quiet, valid_days = fetch(day)
    except oura_auth.AuthRequired:
        raise
    except Exception as exc:  # 基线取不到：沿用旧缓存，不改写
        log("基线获取失败 (%s): %s" % (type(exc).__name__, exc))
        return cached["hr_quiet"] if cached else None
    if hr_quiet is None:  # 暂时拿不到基线：不缓存，下一轮重试
        return None
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


def compute_result(args, now, p=None, tz=None):
    """取数并计算，返回 Result；异常原样抛出，由调用方映射。"""
    global _PERSONAL_INFO
    tz = tz or local_tz()
    p = p if p is not None else hp_model.make_params()
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


def cycle(args, now, p=None):
    try:
        return build_item(compute_result(args, now, p), now)
    except oura_auth.AuthRequired:
        return auth_item(now)
    except oura_client.RateLimited as exc:
        log("Oura 限流，本轮放弃 (retry_after=%s)" % exc.retry_after)
    except (RuntimeError, OSError) as exc:
        log("本轮放弃: %s" % exc)
    return None


def collect(args, p=None, clock=time.time):
    """供 display_push.run 调用：仅在服务端发放租约时计算一轮；失败一律转成 RuntimeError 以上报 /failure。"""
    try:
        item = cycle(args, int(clock()), p)
    except Exception as exc:  # 单轮出错只上报失败，进程继续
        raise RuntimeError("本轮出错: %s: %s" % (type(exc).__name__, exc))
    if item is None:
        raise RuntimeError("本轮未取得数据")
    return item


def _stress_series(rows, key):
    """每日 key 值（分钟）与单位判定；无值时 ({}, None)。"""
    raw = {r["day"]: r[key] for r in rows if r.get(key) is not None and r.get("day")}
    if not raw:
        return {}, None
    minutes = hp_model.stress_in_minutes(list(raw.values()))
    return {d: (v if minutes else v / 60) for d, v in raw.items()}, minutes


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _med(vals):
    return statistics.median(vals) if vals else None


def _num(v, fmt="%.0f"):
    return "--" if v is None else fmt % v


def _report_data(now, tz, today, n):
    one = timedelta(days=1)
    lo, hi = (today - (n + 1) * one).isoformat(), (today + one).isoformat()
    lo_long = (today - (n + 29) * one).isoformat()  # 每个报告日都要有完整的 28 天画像
    data = {name: oura_client.get(name, start_date=lo_long if name in ("sleep", "daily_readiness") else lo,
                                  end_date=hi)
            for name in ("sleep", "daily_readiness", "daily_activity", "workout")}
    start = datetime(today.year, today.month, today.day, tzinfo=tz) - (n + 1) * one
    data["heartrate"] = oura_client.get("heartrate", start_datetime=start.isoformat(),
                                        end_datetime=datetime.fromtimestamp(now, tz).isoformat())
    try:
        data["personal_info"] = oura_client.personal_info()
    except oura_auth.AuthRequired:
        raise
    except (RuntimeError, OSError) as exc:
        log("personal_info 获取失败，继续: %s" % exc)
    return data


def report(args, now, p=None):
    tz = local_tz()
    p = p if p is not None else hp_model.make_params()
    today = hp_model.local_date(now, tz)
    n = args.days
    try:
        data = _report_data(now, tz, today, n)
        stress_rows = oura_client.fetch_stress(today - timedelta(days=1), n)
        hr_quiet = hp_model.quiet_hr(oura_client.fetch_baseline_hr(today, tz))
    except oura_auth.AuthRequired:
        raise SystemExit("--report: Oura 未授权，请先运行 oura_auth 登录")
    except oura_client.RateLimited as exc:
        raise SystemExit("--report: Oura 限流 (retry_after=%s)，请稍后重试" % exc.retry_after)
    except (RuntimeError, OSError) as exc:
        raise SystemExit("--report: %s" % exc)

    stress, s_min = _stress_series(stress_rows, "stress_high")
    recov, r_min = _stress_series(stress_rows, "recovery_high")
    sums = []
    for i in range(n, 0, -1):
        day = (today - timedelta(days=i)).isoformat()
        s = hp_model.day_summary(day, data, hr_quiet, p, tz, age=args.age)
        if s is not None:
            sums.append(s)
    lines = []
    for s in sums:
        lines.append("%s anchor=%.0f(%s) bed_hp=%.0f stress=%d/%s recovery=%d/%s zero=%.0f%% full=%.0f%%" % (
            s["day"], s["anchor"], s["anchor_source"], s["bed_hp"],
            s["stress_min"], _num(stress.get(s["day"])), s["recovery_min"], _num(recov.get(s["day"])),
            100 * s["pct_zero"], 100 * s["pct_full"]))
    units = {None: "无数据", True: "分钟", False: "秒"}
    loads = [s["mean_load"] for s in sums if s["mean_load"] is not None]
    lines.append("汇总 %d 天: bed_hp 中位 %s, stress 模型 %s vs stress_high %s (stress_high 单位: %s), "
                 "recovery 模型 %s vs recovery_high %s (recovery_high 单位: %s), exp_load=%s" % (
                     len(sums), _num(_med([s["bed_hp"] for s in sums])),
                     _num(_med([s["stress_min"] for s in sums])), _num(_med(list(stress.values()))), units[s_min],
                     _num(_med([s["recovery_min"] for s in sums])), _num(_med(list(recov.values()))), units[r_min],
                     _num(_mean(loads), "%.2f")))
    return "\n".join(lines)


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
    p = load_params(args.params)  # 只加载一次；错误在此退出
    if args.report:
        print(report(args, now, p))
        return
    if args.push and args.follow:
        try:
            display_push.run(args, lambda: collect(args, p), path=ENERGY_PATH, describe=energy_usage.summary)
        except KeyboardInterrupt:
            pass
        return
    if args.explain:
        try:
            res = compute_result(args, now, p)
        except (RuntimeError, OSError) as exc:
            sys.exit(str(exc))
        print(explain(res, local_tz()))
        item = build_item(res, now)
    else:
        item = cycle(args, now, p)
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
