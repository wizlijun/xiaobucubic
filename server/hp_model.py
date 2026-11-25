"""HP energy model: pure functions, no IO."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DEFAULT_PARAMS = {
    "basal": 2.0, "k_act": 0.15, "k_met": 1.5, "k_stress": 20.0,
    "theta_stress": 0.08, "stress_cap": 8.0, "theta_rest": -0.05,
    "rest_gain": 2.0, "tau_sleep": 4.2, "exp_load": 0.8,
    "trend_band": 2.5, "kappa": 1.0,
}

NAP_TYPES = ("sleep", "late_nap", "long_sleep")


def make_params(overrides=None):
    p = dict(DEFAULT_PARAMS)
    for k, v in (overrides or {}).items():
        if k not in DEFAULT_PARAMS:
            raise ValueError(f"unknown param: {k}")
        p[k] = v
    return p


def parse_ts(value):
    return int(datetime.fromisoformat(value).timestamp())


def local_date(ts, tz):
    return datetime.fromtimestamp(ts, tz).date()


def main_sleeps(sleeps):
    best = {}
    for s in sleeps:
        if s.get("type") != "long_sleep":
            continue
        cur = best.get(s["day"])
        if cur is None or (s.get("total_sleep_duration") or 0) > (cur.get("total_sleep_duration") or 0):
            best[s["day"]] = s
    return best


def nap_periods(sleeps, main_by_day, t0, now):
    out = []
    for s in sleeps:
        if s.get("type") not in NAP_TYPES:
            continue
        if s["type"] == "long_sleep" and main_by_day.get(s.get("day")) is s:
            continue
        total = s.get("total_sleep_duration") or 0
        if total < 900:
            continue
        start, end = parse_ts(s["bedtime_start"]), parse_ts(s["bedtime_end"])
        if start >= t0 and end <= now:
            out.append((start, end, total))
    return sorted(out)


def quiet_hr(rows):
    vals = [r["bpm"] for r in rows if r.get("source") == "awake" and r.get("bpm") is not None]
    return float(statistics.median(vals)) if vals else None


@dataclass
class Profile:
    valid_days: int
    rhr: float | None
    rhr_mad: float
    hr_quiet: float | None
    ln_hrv_med: float | None
    ln_hrv_mad: float
    bed_min: int
    wake_min: int
    habitual_h: float
    need_min: float
    anchor_median: float | None
    hrmax: float | None
    trimp_a: float
    trimp_b: float


def _med_mad(vals):
    if not vals:
        return None, 0.0
    m = statistics.median(vals)
    return float(m), float(statistics.median(abs(v - m) for v in vals))


def _circular_median(mins):
    ang = [m / 1440 * 2 * math.pi for m in mins]
    mu = math.atan2(sum(math.sin(a) for a in ang), sum(math.cos(a) for a in ang))
    mu = (mu / (2 * math.pi) * 1440) % 1440
    offs = []
    for m in mins:
        d = (m - mu) % 1440
        if d > 720:
            d -= 1440
        offs.append(d)
    return int(round(statistics.median(offs) + mu)) % 1440


def _local_min(value, tz):
    dt = datetime.fromtimestamp(parse_ts(value), tz)
    return dt.hour * 60 + dt.minute


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def readiness_score(day, readiness_by_day, main):
    score = (readiness_by_day.get(day) or {}).get("score")
    if score is None and main:
        score = (main.get("readiness") or {}).get("score")
    return score


def _r_to_hp(r):
    return _clamp(40 + 1.5 * (r - 50), 20, 100)


def build_profile(day, main_by_day, readiness_by_day, hr_quiet, age, sex, p, tz):
    days = []
    for i in range(28, 0, -1):
        key = (day - timedelta(days=i)).isoformat()
        if key in main_by_day:
            days.append(key)
    mains = [main_by_day[k] for k in days]
    n = len(mains)

    rhr, rhr_mad = _med_mad([m["lowest_heart_rate"] for m in mains if m.get("lowest_heart_rate") is not None])
    ln_med, ln_mad = _med_mad([math.log(m["average_hrv"]) for m in mains if m.get("average_hrv")])
    hq = hr_quiet if n >= 14 else (1.25 * rhr if rhr is not None else None)

    bed_min, wake_min, habitual_h, need_min = 1410, 450, 7.5, 480
    totals = [m["total_sleep_duration"] for m in mains if m.get("total_sleep_duration") is not None]
    if mains:
        bed_min = _circular_median([_local_min(m["bedtime_start"], tz) for m in mains])
        wake_min = _circular_median([_local_min(m["bedtime_end"], tz) for m in mains])
    if totals:
        habitual_h = statistics.median(totals) / 3600
        q = statistics.quantiles(totals, n=4, method="inclusive")[2] if len(totals) > 1 else totals[0]
        need_min = _clamp(q / 60, 420, 540)

    anchors = []
    for k in days:
        r = readiness_score(k, readiness_by_day, main_by_day[k])
        if r is not None:
            anchors.append(_r_to_hp(r))
    anchor_median = float(statistics.median(anchors)) if anchors else None

    hrmax = 208 - 0.7 * age if age is not None else None
    female = (sex or "").lower() == "female"
    return Profile(n, rhr, rhr_mad, hq, ln_med, ln_mad, bed_min, wake_min, habitual_h,
                   need_min, anchor_median, hrmax,
                   0.86 if female else 0.64, 1.67 if female else 1.92)


def _z(x, med, mad):
    if x is None or med is None or mad == 0:
        return 0.0
    return _clamp((x - med) / (1.4826 * mad), -2.5, 2.5)


def anchor_value(day, main, readiness_by_day, profile, p):
    r = readiness_score(day, readiness_by_day, main)
    if r is not None:
        return _r_to_hp(r), r
    d = _clamp((main.get("total_sleep_duration") or 0) / (profile.need_min * 60), 0.4, 1.0)
    hrv = main.get("average_hrv")
    z_hrv = _z(math.log(hrv) if hrv else None, profile.ln_hrv_med, profile.ln_hrv_mad)
    z_rhr = _z(main.get("lowest_heart_rate"), profile.rhr, profile.rhr_mad)
    return _clamp(100 * d ** 0.8 + 8 * z_hrv - 8 * z_rhr, 20, 100), None
