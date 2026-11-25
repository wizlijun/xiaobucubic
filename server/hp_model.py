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
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return int(datetime.fromisoformat(value).timestamp())


def local_date(ts, tz):
    return datetime.fromtimestamp(ts, tz).date()


def _safe_ts(value):
    """parse_ts, or None for a missing / malformed timestamp."""
    try:
        return parse_ts(value)
    except (AttributeError, TypeError, ValueError):
        return None


def _sleep_ok(s):
    return (isinstance(s, dict) and isinstance(s.get("day"), str)
            and _safe_ts(s.get("bedtime_start")) is not None
            and _safe_ts(s.get("bedtime_end")) is not None)


def main_sleeps(sleeps):
    best = {}
    for s in sleeps:
        if not _sleep_ok(s) or s.get("type") != "long_sleep":
            continue
        cur = best.get(s["day"])
        if cur is None or (s.get("total_sleep_duration") or 0) > (cur.get("total_sleep_duration") or 0):
            best[s["day"]] = s
    return best


def nap_periods(sleeps, main_by_day, t0, now):
    out = []
    for s in sleeps:
        if not _sleep_ok(s) or s.get("type") not in NAP_TYPES:
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
    hq = hr_quiet if n >= 14 and hr_quiet is not None else (1.25 * rhr if rhr is not None else None)

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


STILL_SOURCES = ("awake", "rest", "live", "session")
INTENSITY_MET = {"easy": 3.0, "moderate": 5.0, "hard": 8.0}
CELL = 300
CARRY_CELLS = 6


@dataclass
class Cell:
    start: int
    hr: float | None = None
    still_hr: float | None = None
    workout_hr: bool = False
    met: float | None = None
    cls: str | None = None
    workout_met: float | None = None
    nap: bool = False
    nap_end_hours: float | None = None


@dataclass
class Step:
    start: int
    kind: str
    rate: float
    hp: float
    hr: float | None
    met: float | None
    load: float


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _hr_time(row):
    ts = row.get("timestamp_unix")
    if ts is None:
        return parse_ts(row["timestamp"])
    ts = int(ts)
    return ts // 1000 if ts > 10 ** 11 else ts


def _clean_hr(rows):
    out = []
    for row in rows:
        try:
            _hr_time(row)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        out.append(row)
    return out


def build_cells(t0, t_end, heartrate, activities, workouts, naps, tz):
    first = -(-t0 // CELL) * CELL
    starts = []
    s = first
    while s + CELL <= t_end:
        starts.append(s)
        s += CELL
    idx = {s: i for i, s in enumerate(starts)}
    cells = [Cell(s) for s in starts]
    if not cells:
        return cells

    hr_all = {s: [] for s in starts}
    hr_still = {s: [] for s in starts}
    for row in heartrate:
        bpm = row.get("bpm")
        if bpm is None or row.get("source") == "sleep":
            continue
        t = _hr_time(row)
        s = t - t % CELL
        if s not in idx:
            continue
        hr_all[s].append(bpm)
        if row.get("source") in STILL_SOURCES:
            hr_still[s].append(bpm)
        if row.get("source") == "workout":
            cells[idx[s]].workout_hr = True

    met_vals = {s: [] for s in starts}
    for act in activities:
        met = act.get("met") or {}
        if met.get("items") and met.get("timestamp"):
            base, step = parse_ts(met["timestamp"]), met.get("interval") or 60
            for k, v in enumerate(met["items"]):
                if v is None:
                    continue
                t = base + k * step
                s = t - t % CELL
                if s in idx:
                    met_vals[s].append(v)
        cls = act.get("class_5_min")
        if cls:
            base = parse_ts(act["timestamp"])
            for k, ch in enumerate(cls):
                s = base + CELL * k
                if s in idx:
                    cells[idx[s]].cls = ch

    for c in cells:
        c.hr = _mean(hr_all[c.start])
        c.still_hr = _mean(hr_still[c.start])
        c.met = _mean(met_vals[c.start])

    for w in workouts:
        if not isinstance(w, dict):
            continue
        ws, we = _safe_ts(w.get("start_datetime")), _safe_ts(w.get("end_datetime"))
        m = INTENSITY_MET.get(w.get("intensity"))
        if m is None or ws is None or we is None:
            continue
        for c in cells:
            if ws < c.start + CELL and we > c.start:
                c.workout_met = m if c.workout_met is None else max(c.workout_met, m)

    for start, end, total in naps:
        for c in cells:
            if start < c.start + CELL and end > c.start:
                c.nap = True
        last = idx.get((end - 1) - (end - 1) % CELL)
        if last is not None and cells[last].nap:
            cells[last].nap_end_hours = total / 3600
    return cells


def data_horizon(heartrate, activities):
    times = [_hr_time(r) for r in heartrate if r.get("bpm") is not None]
    for act in activities:
        met = act.get("met") or {}
        if met.get("items") and met.get("timestamp"):
            base, step = parse_ts(met["timestamp"]), met.get("interval") or 60
            times += [base + k * step for k, v in enumerate(met["items"]) if v is not None]
    return max(times) if times else None


def _trimp_load(hr, profile, p):
    x = _clamp((hr - profile.rhr) / (profile.hrmax - profile.rhr), 0, 1)
    return p["k_act"] * 60 * x * profile.trimp_a * math.exp(profile.trimp_b * x)


def replay(hp0, cells, profile, p, horizon, anchor=None):
    hp = float(hp0)
    target = hp0 if anchor is None else anchor
    kappa, basal = p["kappa"], p["basal"] * p["kappa"]
    steps = []
    carry, carry_idx = None, -10 ** 9
    for i, c in enumerate(cells):
        load = 0.0
        if c.nap:
            kind, rate = "nap", 0.0
            carry = None
            if c.nap_end_hours is not None:
                hp += max(0.0, target - hp) * (1 - math.exp(-c.nap_end_hours / p["tau_sleep"]))
        elif horizon is not None and c.start > horizon:
            kind, load = "unobserved", p["exp_load"]
            rate = -(basal + load)
        else:
            met = c.met
            moving = (c.workout_met is not None or c.workout_hr
                      or (met is not None and met >= 2.0))
            rate = None
            if moving:
                if (c.hr is not None and profile.hrmax is not None
                        and profile.rhr is not None and profile.hrmax > profile.rhr):
                    load = kappa * _trimp_load(c.hr, profile, p)
                elif met is not None:
                    load = kappa * p["k_met"] * max(0.0, met - 1.5)
                elif c.workout_met is not None:
                    load = kappa * p["k_met"] * max(0.0, c.workout_met - 1.5)
                else:
                    moving = False
                if moving:
                    kind, rate = "exercise", -(basal + load)
                    carry = None
            if rate is None:
                if c.cls == "0":
                    kind, load = "offwrist", p["exp_load"]
                    rate = -(basal + load)
                else:
                    if c.still_hr is not None:
                        carry, carry_idx = c.still_hr, i
                    hr = carry if i - carry_idx <= CARRY_CELLS else None
                    if hr is None or profile.hr_quiet is None:
                        kind, load = "unobserved", p["exp_load"]
                        rate = -(basal + load)
                    else:
                        e = (hr - profile.hr_quiet) / profile.hr_quiet
                        if e <= p["theta_rest"]:
                            kind, rate = "rest", -basal + p["rest_gain"]
                        else:
                            load = kappa * min(p["stress_cap"],
                                               p["k_stress"] * max(0.0, e - p["theta_stress"]))
                            kind = "stress" if load > 0 else "still"
                            rate = -(basal + load)
        hp = _clamp(hp + rate * CELL / 3600, 0, 100)
        step_hr = c.hr if c.hr is not None else c.still_hr
        steps.append(Step(c.start, kind, rate, hp, step_hr, c.met, load))
    return steps


AWAKE_SOURCES = ("awake", "workout", "live", "rest", "session")
NIGHT_GAP = 1800
DOZE_MAX = 3 * 3600
WOKE_HOLD = 7200


@dataclass
class NightState:
    state: str
    t_bed: int | None = None
    t_wake: int | None = None


def sleep_estimate(hp_bed, hours, a_bar, habitual_h, p):
    f = ((1 - math.exp(-hours / p["tau_sleep"]))
         / (1 - math.exp(-habitual_h / p["tau_sleep"])))
    return hp_bed + max(0.0, a_bar - hp_bed) * min(1.0, f)


def night_state(t0, now, heartrate, profile, tz):
    day = local_date(t0, tz)
    floor = int(datetime(day.year, day.month, day.day, 18, tzinfo=tz).timestamp())
    lo = max(t0, floor)
    sleeps, awakes = [], []
    for row in heartrate:
        if row.get("bpm") is None:
            continue
        t = _hr_time(row)
        if t <= lo or t > now:
            continue
        if row.get("source") == "sleep":
            sleeps.append(t)
        elif row.get("source") in AWAKE_SOURCES:
            awakes.append(t)
    sleeps.sort()
    awakes.sort()

    segs = []  # (first, last) of each run of >= 2 sleep rows with gaps <= NIGHT_GAP
    first = last = None
    n_rows = 0
    for t in sleeps + [None]:
        if t is not None and last is not None and t - last <= NIGHT_GAP:
            last, n_rows = t, n_rows + 1
            continue
        if n_rows >= 2:
            segs.append((first, last))
        first, last, n_rows = t, t, 1

    def confirmed_wake_after(end):
        return any(a > end and now >= a + NIGHT_GAP
                   and not any(a < s <= a + NIGHT_GAP for s in sleeps) for a in awakes)

    t_bed = None
    for first, last in segs:
        if last - first < DOZE_MAX and confirmed_wake_after(last):
            continue  # evening doze: a later segment is the real night
        t_bed = first
        break
    if t_bed is None and not segs:
        midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
        habitual = midnight + timedelta(minutes=profile.bed_min)
        while habitual.timestamp() < floor:
            habitual += timedelta(days=1)
        if (awakes and now >= habitual.timestamp() + NIGHT_GAP
                and awakes[-1] < now - NIGHT_GAP):
            t_bed = awakes[-1] + CELL
    if t_bed is None:
        return NightState("day")

    t_wake = None
    for a in awakes:
        if a <= t_bed or now < a + NIGHT_GAP:
            continue
        if not any(a < s <= a + NIGHT_GAP for s in sleeps):
            t_wake = a
            break
    if t_wake is None:
        return NightState("night", t_bed)
    state = "woke" if now - t_wake < WOKE_HOLD else "woke_timeout"
    return NightState(state, t_bed, t_wake)


STATUS_BANDS = ((85, "充沛"), (65, "良好"), (45, "尚可"), (20, "偏低"), (5, "告急"))
UNSYNCED_MIN_H, UNSYNCED_MAX_H = 3, 8
DAY_FALLBACK_AFTER_WAKE = 7200
DAY_FALLBACK_AGE = 20 * 3600


@dataclass
class Result:
    level: int | None
    status: str
    trend: str | None
    note: str | None
    state: str
    steps: list
    anchor_day: str | None
    readiness: int | None
    profile: Profile | None


def round_level(x):
    return math.floor(x + 0.5)


def status_word(level):
    if level is None:
        return "待同步"
    for lo, word in STATUS_BANDS:
        if level >= lo:
            return word
    return "见底"


def trend_of(rates, p):
    m = _mean(rates[-3:]) if rates else 0.0  # no steps yet: steady
    if m >= p["trend_band"]:
        return "charging"
    if m <= -p["trend_band"]:
        return "draining"
    return "steady"


def _null(state, steps, anchor_day, readiness, profile):
    return Result(None, status_word(None), None, None, state, steps, anchor_day, readiness, profile)


def _day_note(steps, level, now, t0, r, last_awake, profile):
    h = (now - last_awake) // 3600
    if UNSYNCED_MIN_H <= h < UNSYNCED_MAX_H:
        return f"{int(h)}h未同步"
    if r is not None and now - t0 < 3600:
        return f"准备度{r}"
    last3 = steps[-3:]
    if last3 and _mean([s.load if s.kind == "exercise" else 0.0 for s in last3]) >= 6:
        return "运动中"
    if len(last3) == 3 and all(s.kind == "stress" for s in last3) and _mean([s.load for s in last3]) >= 3:
        return "生理压力高"
    if any(a.kind == "nap" and b.kind != "nap" for a, b in zip(last3, last3[1:])):
        return "小憩回血"
    if steps and steps[-1].kind == "rest":
        return "静息恢复"
    if level < 20:
        return "建议休息"
    if profile.valid_days < 14:
        return "校准中"
    return None


def _anchor_state(anchor_day, anchor_date, m, main, data, hr_quiet, p, tz, age):
    t0 = parse_ts(m["bedtime_end"])
    readiness_by_day = {r["day"]: r for r in data.get("daily_readiness") or []
                        if isinstance(r, dict) and isinstance(r.get("day"), str)}
    info = data.get("personal_info") or {}
    age = info.get("age") if info.get("age") is not None else age
    profile = build_profile(anchor_date, main, readiness_by_day, hr_quiet, age,
                            info.get("biological_sex"), p, tz)
    hp0, r = anchor_value(anchor_day, m, readiness_by_day, profile, p)
    return t0, profile, hp0, r


def compute(now, data, hr_quiet, p, tz, age=None):
    sleeps = data.get("sleep") or []
    main = main_sleeps(sleeps)
    today = local_date(now, tz)
    anchor_day = None
    for d in (today, today - timedelta(days=1)):
        m = main.get(d.isoformat())
        if m is not None and parse_ts(m["bedtime_end"]) <= now:
            anchor_day, anchor_date = d.isoformat(), d
            break
    if anchor_day is None:
        return _null("none", [], None, None, None)

    m = main[anchor_day]
    t0, profile, hp0, r = _anchor_state(anchor_day, anchor_date, m, main, data, hr_quiet, p, tz, age)
    heartrate = [row for row in _clean_hr(data.get("heartrate") or []) if _hr_time(row) <= now]
    activities = data.get("daily_activity") or []
    workouts = data.get("workout") or []
    naps = nap_periods(sleeps, main, t0, now)
    horizon = data_horizon(heartrate, activities)
    ns = night_state(t0, now, heartrate, profile, tz)

    if ns.state == "day":
        cells = build_cells(t0, now, heartrate, activities, workouts, naps, tz)
        steps = replay(hp0, cells, profile, p, horizon)
        awake = [_hr_time(row) for row in heartrate
                 if row.get("bpm") is not None and row.get("source") in AWAKE_SOURCES and _hr_time(row) >= t0]
        last_awake = max(awake) if awake else t0
        wake_instant = (datetime(today.year, today.month, today.day, tzinfo=tz)
                        + timedelta(minutes=profile.wake_min)).timestamp()
        if (now - last_awake >= UNSYNCED_MAX_H * 3600
                or (now >= wake_instant + DAY_FALLBACK_AFTER_WAKE and now - t0 > DAY_FALLBACK_AGE)):
            return _null("day", steps, anchor_day, r, profile)
        hp = steps[-1].hp if steps else hp0
        level = round_level(hp)
        trend = trend_of([s.rate for s in steps], p)
        note = _day_note(steps, level, now, t0, r, last_awake, profile)
        return Result(level, status_word(level), trend, note, "day", steps, anchor_day, r, profile)

    cells = build_cells(t0, ns.t_bed, heartrate, activities, workouts, naps, tz)
    steps = replay(hp0, cells, profile, p, horizon)
    if ns.state == "woke_timeout":
        return _null(ns.state, steps, anchor_day, r, profile)
    hp_bed = steps[-1].hp if steps else hp0
    a_bar = profile.anchor_median if profile.anchor_median is not None else hp0
    end = now if ns.state == "night" else ns.t_wake
    level = round_level(sleep_estimate(hp_bed, (end - ns.t_bed) / 3600, a_bar, profile.habitual_h, p))
    trend = "charging" if ns.state == "night" else "steady"
    return Result(level, status_word(level), trend, "睡眠预估", ns.state, steps, anchor_day, r, profile)


def stress_in_minutes(values):
    """spec D8: median below 1440 means the values are minutes, not seconds."""
    return statistics.median(values) < 1440


def day_summary(day, data, hr_quiet, p, tz, age=None):
    sleeps = data.get("sleep") or []
    main = main_sleeps(sleeps)
    m = main.get(day)
    if m is None:
        return None
    anchor_date = date.fromisoformat(day)
    t0, profile, hp0, r = _anchor_state(day, anchor_date, m, main, data, hr_quiet, p, tz, age)
    nxt = main.get((anchor_date + timedelta(days=1)).isoformat())
    if nxt is not None:
        t_end = parse_ts(nxt["bedtime_start"])
    else:
        nd = anchor_date + timedelta(days=1)
        t_end = int(datetime(nd.year, nd.month, nd.day, 4, tzinfo=tz).timestamp())
    heartrate = _clean_hr(data.get("heartrate") or [])
    activities = data.get("daily_activity") or []
    cells = build_cells(t0, t_end, heartrate, activities, data.get("workout") or [],
                        nap_periods(sleeps, main, t0, t_end), tz)
    steps = replay(hp0, cells, profile, p, data_horizon(heartrate, activities))
    n = len(steps)
    loads = [s.load for s in steps if s.kind not in ("nap", "unobserved", "offwrist")]
    return {
        "day": day, "anchor": round(hp0, 1),
        "anchor_source": "readiness" if r is not None else "sleep",
        "bed_hp": steps[-1].hp if steps else hp0,
        "stress_min": 5 * sum(s.kind == "stress" for s in steps),
        "recovery_min": 5 * sum(s.kind == "rest" for s in steps),
        "pct_zero": sum(s.hp <= 0 for s in steps) / n if n else 0.0,
        "pct_full": sum(s.hp >= 100 for s in steps) / n if n else 0.0,
        "mean_load": _mean(loads),
    }
