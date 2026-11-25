"""HP 周限：每周六 12:00 重置，按普通成年人标准把一周的透支折算成负债小时。纯函数，无 IO。

设计见 docs/superpowers/specs/2026-11-25-hp-weekly-limit-design.md。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from hp_model import NAP_TYPES, _fit, _safe_ts, _sleep_ok, _z, main_sleeps, stress_in_minutes

BUDGET_H = 7.0
RESET_WEEKDAY, RESET_HOUR = 5, 12          # 周六 12:00
SLEEP_NEED_H, SLEEP_CREDIT_MAX_H = 7.0, 9.0
LATE_WEIGHT = 0.25                         # 00:00 之后每小时
EXERCISE_MIN, EXERCISE_CAP_H = 150.0, 2.5  # WHO：每周 150 分钟中等强度当量
HIGH_MAX_MIN = 300.0
STEPS_MIN, SEDENTARY_H = 5000, 0.25
STRESS_ALLOW_MIN, STRESS_WEIGHT = 60.0, 0.5
DRAIN_LEVEL, DRAIN_WEIGHT = 20.0, 0.5
RECOVERY_H, REST_CREDIT = 1.0, 0.25
RHR_MIN_DELTA = 3.0                        # 静息心率至少高出 3 bpm 才算，避免 MAD 很小时 1–2 bpm 的噪声
CELL_H = 300 / 3600
LOW_PERCENT = 20

ITEMS = ("sleep", "late", "exercise_low", "sedentary", "exercise_high", "stress", "drain", "recovery")
ADVICE = {"sleep": "该补觉", "late": "今晚早睡", "exercise_low": "去动一动", "sedentary": "多走走",
          "exercise_high": "停练休息", "stress": "放松一下", "drain": "强制休息", "recovery": "强制休息"}


def week_bounds(now, tz):
    """返回 (本周开始, 重置时刻)，均为 Unix 秒。"""
    local = datetime.fromtimestamp(now, tz)
    day = local.date() - timedelta(days=(local.weekday() - RESET_WEEKDAY) % 7)
    start = datetime(day.year, day.month, day.day, RESET_HOUR, tzinfo=tz)
    if start.timestamp() > now:
        start -= timedelta(days=7)
    return int(start.timestamp()), int((start + timedelta(days=7)).timestamp())


def _wall_clock(iso, tz):
    """入睡时的当地钟点：优先用记录自带的时区偏移（戒指所在地），解析不了再换算到 tz。"""
    try:
        t = datetime.fromisoformat(iso[:-1] + "+00:00" if iso.endswith("Z") else iso)
        if t.tzinfo is not None:
            return t
    except (TypeError, ValueError):
        pass
    return datetime.fromtimestamp(_safe_ts(iso), tz)


def _num(row, key):
    v = row.get(key) if isinstance(row, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def compute(now, tz, sleeps, activities, stress_rows, steps, profile):
    start, reset = week_bounds(now, tz)
    start_day = datetime.fromtimestamp(start, tz).date().isoformat()
    reset_day = datetime.fromtimestamp(reset, tz).date().isoformat()
    today = datetime.fromtimestamp(now, tz).date().isoformat()
    ledger = {}

    def add(day, key, h):
        row = ledger.setdefault(day, {"debt": {}, "credit": 0.0})
        row["debt"][key] = row["debt"].get(key, 0.0) + h

    def credit(day, h):
        ledger.setdefault(day, {"debt": {}, "credit": 0.0})["credit"] += h

    # 夜间：主睡眠 + 同一 day 的小睡；归属看主睡眠的醒来时刻。
    slept = {}
    for s in sleeps:
        if _sleep_ok(s) and s.get("type") in NAP_TYPES and _safe_ts(s["bedtime_end"]) <= now:
            slept[s["day"]] = slept.get(s["day"], 0) + (_num(s, "total_sleep_duration") or 0)
    for key, m in main_sleeps(sleeps).items():
        end = _safe_ts(m["bedtime_end"])
        if not start <= end <= now:
            continue
        day = datetime.fromtimestamp(end, tz).date().isoformat()
        h = slept.get(key, 0) / 3600
        if h < SLEEP_NEED_H:
            add(day, "sleep", SLEEP_NEED_H - h)
        elif h > SLEEP_NEED_H:
            credit(day, min(h, SLEEP_CREDIT_MAX_H) - SLEEP_NEED_H)
        bed = _wall_clock(m["bedtime_start"], tz)
        if bed.hour < 12:
            add(day, "late", LATE_WEIGHT * (bed.hour + bed.minute / 60))
        if profile is not None:
            hrv, rhr = _num(m, "average_hrv"), _num(m, "lowest_heart_rate")
            z_hrv = _z(math.log(hrv) if hrv else None, profile.ln_hrv_med, profile.ln_hrv_mad)
            z_rhr = _z(rhr, profile.rhr, profile.rhr_mad)
            if z_hrv <= -1 or (z_rhr >= 1 and rhr - profile.rhr >= RHR_MIN_DELTA):
                add(day, "recovery", RECOVERY_H)

    def in_week(row):
        day = row.get("day") if isinstance(row, dict) else None
        return isinstance(day, str) and start_day <= day < reset_day and day <= today

    # 日汇总：周六整天算新的一周。
    moderate = high = 0.0
    for a in filter(in_week, activities):
        med_s, high_s = _num(a, "medium_activity_time") or 0, _num(a, "high_activity_time") or 0
        moderate += (med_s + 2 * high_s) / 60
        high += high_s / 60
        n = _num(a, "steps")
        if a["day"] < today and n is not None and n < STEPS_MIN:
            add(a["day"], "sedentary", SEDENTARY_H)
    rows = [r for r in filter(in_week, stress_rows) if _num(r, "stress_high") is not None]
    if rows:
        minutes = stress_in_minutes([r["stress_high"] for r in rows])
        for r in rows:
            over = (r["stress_high"] if minutes else r["stress_high"] / 60) - STRESS_ALLOW_MIN
            if over > 0:
                add(r["day"], "stress", STRESS_WEIGHT * over / 60)

    # 5 分钟格：透支与休息还款。
    for s in steps:
        if not start <= s.start < min(reset, now + 1) or s.kind == "nap":
            continue
        day = datetime.fromtimestamp(s.start, tz).date().isoformat()
        if s.hp < DRAIN_LEVEL:
            add(day, "drain", DRAIN_WEIGHT * CELL_H)
        if s.kind == "rest":
            credit(day, REST_CREDIT * CELL_H)

    balance, days = 0.0, []
    totals = dict.fromkeys(ITEMS, 0.0)
    for day in sorted(ledger):
        row = ledger[day]
        for k, h in row["debt"].items():
            totals[k] += h
        balance = max(0.0, balance + sum(row["debt"].values()) - row["credit"])
        days.append({"day": day, "debt": {k: round(h, 2) for k, h in row["debt"].items()},
                     "credit": round(row["credit"], 2), "balance": round(balance, 2)})
    expected = EXERCISE_MIN * min(1.0, (now - start) / (reset - start))
    totals["exercise_low"] = min(EXERCISE_CAP_H, max(0.0, expected - moderate) / 60)
    totals["exercise_high"] = max(0.0, high - HIGH_MAX_MIN) / 60
    balance += totals["exercise_low"] + totals["exercise_high"]

    top = max(ITEMS, key=lambda k: totals[k])
    return {
        "remaining_percent": int(round(max(0.0, min(100.0, 100 * (1 - balance / BUDGET_H))))),
        "debt_hours": round(balance, 1),
        "reset_at": reset,
        "top": top if totals[top] > 0 else None,
        "items": {k: round(v, 2) for k, v in totals.items()},
        "days": days,
    }


def public(weekly):
    """提交给显示服务的部分（去掉逐日账本）。"""
    return {k: v for k, v in weekly.items() if k != "days"}


def line(weekly):
    """周剩余低于 20% 时给出说明行，否则 None。"""
    if not weekly or weekly["remaining_percent"] >= LOW_PERCENT:
        return None
    return _fit("本周欠%.1fh" % weekly["debt_hours"], ADVICE.get(weekly["top"]))


def ledger_text(weekly):
    out = []
    for r in weekly["days"]:
        debt = " ".join("%s=%.2f" % kv for kv in sorted(r["debt"].items()))
        out.append("%s 负债 %s 还款 %.2f 结余 %.2f" % (r["day"], debt or "-", r["credit"], r["balance"]))
    out.append("运动当量不足 %.2fh 高强度过量 %.2fh → 本周负债 %.1fh，剩余 %d%%" % (
        weekly["items"]["exercise_low"], weekly["items"]["exercise_high"],
        weekly["debt_hours"], weekly["remaining_percent"]))
    return "\n".join(out)
