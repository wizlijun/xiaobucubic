import unittest
from datetime import date, datetime, timedelta, timezone

from hp_model import (DEFAULT_PARAMS, Cell, Profile, anchor_value, build_cells,
                      build_profile, compute, data_horizon, day_summary, main_sleeps, make_params,
                      nap_periods, night_state, parse_ts, quiet_hr, replay,
                      round_level, sleep_estimate, status_word, stress_in_minutes, trend_of)

TZ = timezone(timedelta(hours=8))
P = make_params()


def sleep(day, start, end, total, type="long_sleep", **kw):
    r = {"day": day, "bedtime_start": start, "bedtime_end": end,
         "total_sleep_duration": total, "type": type}
    r.update(kw)
    return r


def days_before(day, n, **kw):
    """n valid main sleeps on the n days before `day` (date)."""
    out = {}
    for i in range(1, n + 1):
        d = (day - timedelta(days=i)).isoformat()
        f = dict(start="T23:30:00+08:00", end="T07:30:00+08:00", total=8 * 3600)
        f.update(kw)
        prev = (day - timedelta(days=i + 1)).isoformat()
        out[d] = sleep(d, prev + f["start"], d + f["end"], f["total"],
                       **{k: v for k, v in f.items() if k not in ("start", "end", "total")})
    return out


class FoundationTests(unittest.TestCase):
    def test_parse_ts_z_suffix_and_fraction(self):
        from hp_model import parse_ts
        self.assertEqual(parse_ts("2026-11-24T00:00:00Z"), parse_ts("2026-11-24T08:00:00+08:00"))
        self.assertIsInstance(parse_ts("2026-11-24T00:00:00Z"), int)
        self.assertEqual(parse_ts("2026-11-24T00:00:00.000+08:00"), parse_ts("2026-11-24T00:00:00+08:00"))

    def setUp(self):
        self.day = date(2026, 11, 25)
        self.prof = build_profile(self.day, {}, {}, None, None, None, P, TZ)
        self.prof.need_min = 480
        self.prof.ln_hrv_mad = 0
        self.prof.rhr_mad = 0

    def test_make_params(self):
        self.assertEqual(make_params()["tau_sleep"], 4.2)
        self.assertEqual(make_params({"kappa": 1.2})["kappa"], 1.2)
        with self.assertRaises(ValueError):
            make_params({"nope": 1})
        self.assertEqual(DEFAULT_PARAMS["kappa"], 1.0)

    def test_parse_ts_offsets_equal(self):
        self.assertEqual(parse_ts("2026-11-25T08:00:00+09:00"), parse_ts("2026-11-25T07:00:00+08:00"))

    def test_anchor_from_readiness(self):
        main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 28800)
        for r, hp in ((82, 88), (62, 58), (95, 100), (30, 20)):
            self.assertEqual(anchor_value("2026-11-25", main, {"2026-11-25": {"score": r}}, self.prof, P)[0], hp)

    def test_readiness_falls_back_to_embedded(self):
        main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 28800,
                     readiness={"score": 70})
        hp, r = anchor_value("2026-11-25", main, {"2026-11-25": {"score": None}}, self.prof, P)
        self.assertEqual((hp, r), (70, 70))

    def test_fallback_anchor(self):
        for secs, want in ((480 * 60, 100), (240 * 60, 57.43), (60 * 60, 48.04)):
            main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", secs)
            hp, r = anchor_value("2026-11-25", main, {}, self.prof, P)
            self.assertAlmostEqual(hp, want, places=1)
            self.assertIsNone(r)

    def test_fallback_anchor_uses_z_scores(self):
        prof = self.prof
        prof.ln_hrv_med, prof.ln_hrv_mad, prof.rhr, prof.rhr_mad = 3.0, 0.2, 50.0, 2.0
        main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 240 * 60,
                     average_hrv=20.0855369, lowest_heart_rate=50)  # ln = 3.0 -> z 0
        base = anchor_value("2026-11-25", main, {}, prof, P)[0]
        main["lowest_heart_rate"] = 56  # z_rhr = 6/2.9652 ~ 2.02
        self.assertLess(anchor_value("2026-11-25", main, {}, prof, P)[0], base - 15)

    def test_main_sleep_picks_longest_long_sleep(self):
        a = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T02:00:00+08:00", 10000)
        b = sleep("2026-11-25", "2026-11-25T03:00:00+08:00", "2026-11-25T08:00:00+08:00", 17000)
        n = sleep("2026-11-25", "2026-11-25T13:00:00+08:00", "2026-11-25T14:00:00+08:00", 3000, type="sleep")
        m = main_sleeps([a, b, n])
        self.assertIs(m["2026-11-25"], b)
        self.assertEqual(len(m), 1)

    def test_nap_selection(self):
        t0 = parse_ts("2026-11-25T07:00:00+08:00")
        now = parse_ts("2026-11-25T22:00:00+08:00")
        main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 28000)
        n1 = sleep("2026-11-25", "2026-11-25T12:00:00+08:00", "2026-11-25T12:25:00+08:00", 1200, type="sleep")
        n2 = sleep("2026-11-25", "2026-11-25T15:00:00+08:00", "2026-11-25T15:45:00+08:00", 2400, type="late_nap")
        n3 = sleep("2026-11-25", "2026-11-25T17:00:00+08:00", "2026-11-25T20:30:00+08:00", 12600)
        bad = [
            sleep("2026-11-25", "2026-11-25T09:00:00+08:00", "2026-11-25T09:30:00+08:00", 1800, type="rest"),
            sleep("2026-11-25", "2026-11-25T10:00:00+08:00", "2026-11-25T10:30:00+08:00", 1800, type="deleted"),
            sleep("2026-11-25", "2026-11-25T11:00:00+08:00", "2026-11-25T11:12:00+08:00", 600, type="sleep"),
            sleep("2026-11-24", "2026-11-24T13:00:00+08:00", "2026-11-24T13:40:00+08:00", 2400, type="sleep"),
        ]
        sleeps = [main, n3, n2, n1] + bad
        got = nap_periods(sleeps, main_sleeps(sleeps), t0, now)
        self.assertEqual([g[2] for g in got], [1200, 2400, 12600])
        self.assertEqual(got[0][:2], (parse_ts("2026-11-25T12:00:00+08:00"), parse_ts("2026-11-25T12:25:00+08:00")))

    def test_nap_must_end_by_now(self):
        t0 = parse_ts("2026-11-25T07:00:00+08:00")
        n = sleep("2026-11-25", "2026-11-25T12:00:00+08:00", "2026-11-25T12:30:00+08:00", 1800, type="sleep")
        self.assertEqual(nap_periods([n], {}, t0, parse_ts("2026-11-25T12:10:00+08:00")), [])

    def test_quiet_hr(self):
        rows = [{"source": "awake", "bpm": 60}, {"source": "awake", "bpm": 70},
                {"source": "awake", "bpm": 80}, {"source": "sleep", "bpm": 40},
                {"source": "workout", "bpm": 150}]
        self.assertEqual(quiet_hr(rows), 70)
        self.assertIsNone(quiet_hr([{"source": "sleep", "bpm": 40}]))

    def test_profile_defaults_without_valid_days(self):
        p = build_profile(date(2026, 11, 25), {}, {}, None, None, None, P, TZ)
        self.assertEqual((p.bed_min, p.wake_min, p.habitual_h, p.need_min, p.rhr, p.hr_quiet),
                         (1410, 450, 7.5, 480, None, None))
        self.assertEqual(p.valid_days, 0)

    def test_hr_quiet_falls_back_under_14_days(self):
        m = days_before(self.day, 10, lowest_heart_rate=48)
        prof = build_profile(self.day, m, {}, 70, None, None, P, TZ)
        self.assertEqual(prof.hr_quiet, 60.0)

    def test_hr_quiet_used_with_14_days(self):
        m = days_before(self.day, 14, lowest_heart_rate=48)
        prof = build_profile(self.day, m, {}, 70, None, None, P, TZ)
        self.assertEqual(prof.hr_quiet, 70)

    def test_circular_bedtime_median(self):
        m = {}
        for i, hhmm in enumerate(("23:50", "00:10", "00:20"), start=1):
            d = (self.day - timedelta(days=i)).isoformat()
            m[d] = sleep(d, f"{d}T{hhmm}:00+08:00", f"{d}T08:00:00+08:00", 28000)
        prof = build_profile(self.day, m, {}, None, None, None, P, TZ)
        self.assertEqual(prof.bed_min, 10)

    def test_need_clamped(self):
        lo = build_profile(self.day, days_before(self.day, 5, total=6 * 3600), {}, None, None, None, P, TZ)
        hi = build_profile(self.day, days_before(self.day, 5, total=10 * 3600), {}, None, None, None, P, TZ)
        self.assertEqual((lo.need_min, hi.need_min), (420, 540))

    def test_anchor_median_from_readiness_days(self):
        m = days_before(self.day, 4)
        keys = sorted(m)
        rd = {keys[0]: {"score": 70}, keys[1]: {"score": 82}, keys[2]: {"score": 90}}
        prof = build_profile(self.day, m, rd, None, None, None, P, TZ)
        self.assertEqual(prof.anchor_median, 88)
        self.assertIsNone(build_profile(self.day, m, {}, None, None, None, P, TZ).anchor_median)

    def test_hrmax_and_trimp(self):
        p = build_profile(self.day, {}, {}, None, 40, "Female", P, TZ)
        self.assertEqual((p.hrmax, p.trimp_a, p.trimp_b), (180.0, 0.86, 1.67))
        p = build_profile(self.day, {}, {}, None, None, None, P, TZ)
        self.assertEqual((p.hrmax, p.trimp_a, p.trimp_b), (None, 0.64, 1.92))

    def test_null_fields_skipped(self):
        m = days_before(self.day, 3, lowest_heart_rate=50, average_hrv=40)
        k = sorted(m)[0]
        m[k]["lowest_heart_rate"] = None
        m[k]["average_hrv"] = None
        prof = build_profile(self.day, m, {}, None, None, None, P, TZ)
        self.assertEqual(prof.rhr, 50)
        self.assertAlmostEqual(prof.ln_hrv_med, 3.6889, places=3)
        self.assertEqual(prof.valid_days, 3)

    def test_valid_days_window_excludes_today(self):
        m = days_before(self.day, 3)
        today = self.day.isoformat()
        m[today] = sleep(today, "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 28000)
        m["2026-11-26"] = sleep("2026-11-26", "2026-11-25T23:00:00+08:00", "2026-11-26T07:00:00+08:00", 28000)
        m[(self.day - timedelta(days=29)).isoformat()] = sleep("x", "2026-10-26T23:00:00+08:00", "2026-10-27T07:00:00+08:00", 28000)
        self.assertEqual(build_profile(self.day, m, {}, None, None, None, P, TZ).valid_days, 3)


def mkprofile(**kw):
    d = dict(valid_days=28, rhr=48, rhr_mad=2, hr_quiet=62, ln_hrv_med=None, ln_hrv_mad=0,
             bed_min=1410, wake_min=450, habitual_h=7.5, need_min=480, anchor_median=None,
             hrmax=172, trimp_a=0.64, trimp_b=1.92)
    d.update(kw)
    return Profile(**d)


T0 = parse_ts("2026-11-25T07:00:00+08:00")


def at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return parse_ts("2026-11-25T00:00:00+08:00") + h * 3600 + m * 60


def example_cells():
    segs = [("07:00", "08:00", 68, 0), ("08:00", "08:30", 95, 1), ("08:30", "12:00", 70, 0),
            ("12:00", "12:30", 90, 1), ("12:30", "13:00", 72, 0), ("13:00", "13:30", 57, 0),
            ("13:30", "15:30", 80, 0), ("15:30", "18:00", 68, 0), ("18:00", "18:30", 95, 1),
            ("18:30", "19:15", 140, 1), ("19:15", "20:15", 82, 0), ("20:15", "23:00", 64, 0)]
    cells = []
    for a, b, hr, moving in segs:
        for t in range(at(a), at(b), 300):
            if moving:
                cells.append(Cell(t, hr=hr, workout_hr=True, met=3.5, cls="4"))
            else:
                cells.append(Cell(t, hr=hr, still_hr=hr, met=1.2, cls="2"))
    return cells


def one(cell, prof=None, p=P, hp0=80, horizon=10 ** 12):
    return replay(hp0, [cell], prof or mkprofile(), p, horizon)[0]


class ReplayTests(unittest.TestCase):
    EXPECTED = {"08:00": 86, "08:30": 82, "12:00": 72, "12:30": 69, "13:00": 67, "13:30": 67,
                "15:30": 55, "18:00": 49, "18:30": 46, "19:15": 31, "20:15": 24, "23:00": 19}

    def test_example_day_matches_design(self):
        steps = replay(88, example_cells(), mkprofile(), P, at("23:00"))
        for hhmm, want in self.EXPECTED.items():
            hp = [s for s in steps if s.start < at(hhmm)][-1].hp
            self.assertAlmostEqual(hp, want, delta=1, msg=hhmm)

    def test_nap_recovery(self):
        cells = [Cell(T0 + 300 * i, nap=True) for i in range(6)]
        cells[-1].nap_end_hours = 0.5
        steps = replay(40, cells, mkprofile(), P, T0 + 3600, anchor=88)
        self.assertTrue(all(s.kind == "nap" for s in steps))
        self.assertAlmostEqual(steps[-1].hp, 45.4, delta=0.1)
        self.assertEqual(steps[0].hp, 40)

    def test_beyond_horizon_unobserved(self):
        s = one(Cell(T0, hr=70, still_hr=70, met=1.2, cls="2"), horizon=T0 - 1)
        self.assertEqual((s.kind, round(s.rate, 6)), ("unobserved", -2.8))

    def test_workout_intensity_only(self):
        s = one(Cell(T0, workout_met=8))
        self.assertEqual(s.kind, "exercise")
        self.assertAlmostEqual(s.rate, -(2 + 1.5 * 6.5))

    def test_met_formula_without_hr(self):
        s = one(Cell(T0, met=4.0))
        self.assertEqual(s.kind, "exercise")
        self.assertAlmostEqual(s.rate, -5.75)

    def test_offwrist(self):
        s = one(Cell(T0, cls="0"))
        self.assertEqual((s.kind, round(s.rate, 6)), ("offwrist", -2.8))

    def test_rest_and_still_and_stress(self):
        s = one(Cell(T0, still_hr=57, cls="2"))
        self.assertEqual((s.kind, s.rate), ("rest", 0.0))
        s = one(Cell(T0, still_hr=62, cls="2"))
        self.assertEqual((s.kind, s.rate), ("still", -2.0))
        s = one(Cell(T0, still_hr=80, cls="2"))
        self.assertEqual(s.kind, "stress")
        self.assertAlmostEqual(s.rate, -(2 + 20 * (18 / 62 - 0.08)))

    def test_hr_carry_forward_30_min(self):
        cells = [Cell(at("10:00") + 300 * i, still_hr=70 if i == 0 else None, cls="2")
                 for i in range(8)]
        kinds = [s.kind for s in replay(80, cells, mkprofile(), P, at("11:00"))]
        self.assertEqual(kinds[:7], ["stress"] * 7)
        self.assertEqual(kinds[7], "unobserved")

    def test_carry_cleared_by_workout_and_nap(self):
        cells = [Cell(T0, still_hr=70, cls="2"), Cell(T0 + 300, met=4.0),
                 Cell(T0 + 600, cls="2")]
        self.assertEqual(replay(80, cells, mkprofile(), P, T0 + 900)[-1].kind, "unobserved")
        cells = [Cell(T0, still_hr=70, cls="2"), Cell(T0 + 300, nap=True),
                 Cell(T0 + 600, cls="2")]
        self.assertEqual(replay(80, cells, mkprofile(), P, T0 + 900)[-1].kind, "unobserved")

    def test_no_baseline(self):
        prof = mkprofile(rhr=None, hr_quiet=None)
        s = one(Cell(T0, hr=95, workout_hr=True, met=4.0, cls="4"), prof)
        self.assertEqual(s.kind, "exercise")
        self.assertAlmostEqual(s.rate, -5.75)
        s = one(Cell(T0, hr=70, still_hr=70, met=1.2, cls="2"), prof)
        self.assertEqual(s.kind, "unobserved")

    def test_kappa_scales_basal_exercise_stress(self):
        p = make_params({"kappa": 0.5})
        self.assertAlmostEqual(one(Cell(T0, still_hr=62, cls="2"), p=p).rate, -1.0)
        self.assertAlmostEqual(one(Cell(T0, cls="2"), p=p).rate, -(1.0 + 0.8))
        self.assertAlmostEqual(one(Cell(T0, still_hr=57, cls="2"), p=p).rate, -1.0 + 2.0)
        self.assertAlmostEqual(one(Cell(T0, met=4.0), p=p).rate, -(1.0 + 0.5 * 1.5 * 2.5))

    def test_hp_clamped(self):
        self.assertEqual(one(Cell(T0, still_hr=57, cls="2"), hp0=100).hp, 100)
        self.assertEqual(one(Cell(T0, met=8.0), hp0=0.01).hp, 0)

    def test_build_cells_null_met_items(self):
        act = {"timestamp": "2026-11-25T04:00:00+08:00", "class_5_min": None,
               "met": {"interval": 60, "timestamp": "2026-11-25T07:00:00+08:00",
                       "items": [None, 2.0, 4.0, None, None, None, None, None, None, None]}}
        cells = build_cells(T0, T0 + 600, [], [act], [], [], TZ)
        self.assertEqual(len(cells), 2)
        self.assertAlmostEqual(cells[0].met, 3.0)
        self.assertIsNone(cells[1].met)
        self.assertIsNone(cells[0].cls)

    def test_build_cells_alignment_and_end(self):
        t0 = parse_ts("2026-11-25T07:02:00+08:00")
        cells = build_cells(t0, parse_ts("2026-11-25T07:24:00+08:00"), [], [], [], [], TZ)
        self.assertEqual(cells[0].start, parse_ts("2026-11-25T07:05:00+08:00"))
        self.assertEqual(cells[-1].start, parse_ts("2026-11-25T07:15:00+08:00"))

    def test_build_cells_sources_class_workout_nap(self):
        hr = [{"bpm": 60, "source": "awake", "timestamp_unix": (T0 + 10) * 1000,
               "timestamp": "x"},
              {"bpm": 100, "source": "workout", "timestamp_unix": (T0 + 20) * 1000,
               "timestamp": "x"},
              {"bpm": 50, "source": "sleep", "timestamp": "2026-11-25T07:00:30+08:00"},
              {"bpm": 70, "source": "rest", "timestamp": "2026-11-25T07:05:30+08:00"}]
        act = {"timestamp": "2026-11-25T04:00:00+08:00", "class_5_min": "0" * 36 + "12",
               "met": None}
        wk = [{"start_datetime": "2026-11-25T07:08:00+08:00",
               "end_datetime": "2026-11-25T07:12:00+08:00", "intensity": "hard"}]
        naps = [(T0 + 600, T0 + 900, 1800)]
        cells = build_cells(T0, T0 + 1200, hr, [act], wk, naps, TZ)
        self.assertEqual((cells[0].hr, cells[0].still_hr, cells[0].workout_hr), (80, 60, True))
        self.assertEqual((cells[1].hr, cells[1].still_hr), (70, 70))
        self.assertEqual([c.cls for c in cells[:3]], ["1", "2", None])
        self.assertEqual(cells[1].workout_met, 8.0)
        self.assertEqual([c.nap for c in cells], [False, False, True, False])
        self.assertEqual([c.nap_end_hours for c in cells], [None, None, 0.5, None])

    def test_data_horizon(self):
        hr = [{"bpm": 60, "source": "awake", "timestamp_unix": 5000 * 1000}]
        act = {"met": {"interval": 60, "timestamp": "2026-11-25T07:00:00+08:00",
                       "items": [1.0, None, 1.0, None]}}
        self.assertEqual(data_horizon(hr, [act]), T0 + 120)
        self.assertIsNone(data_horizon([], []))


class NightTests(unittest.TestCase):
    T0 = parse_ts("2026-11-25T07:00:00+08:00")

    @staticmethod
    def hr(ts, source, bpm=60):
        return {"timestamp": f"2026-11-{ts[:2]}T{ts[3:]}:00+08:00", "bpm": bpm, "source": source}

    @staticmethod
    def at(ts):
        return parse_ts(f"2026-11-{ts[:2]}T{ts[3:]}:00+08:00")

    @staticmethod
    def run_rows(start, end, source, day="25"):
        """rows every 5 minutes from 'day HH:MM' start to end (inclusive), end may be next day."""
        a = datetime.fromisoformat(f"2026-11-{start[:2]}T{start[3:]}:00+08:00")
        b = datetime.fromisoformat(f"2026-11-{end[:2]}T{end[3:]}:00+08:00")
        out = []
        while a <= b:
            out.append({"timestamp": a.isoformat(), "bpm": 55, "source": source})
            a += timedelta(minutes=5)
        return out

    def ns(self, rows, now):
        prof = Profile(28, 50, 2, 62, 4, 0.2, 1410, 450, 8, 480, 70, 190, 0.64, 1.92)
        return night_state(self.T0, self.at(now), rows, prof, TZ)

    def test_rule1_sleep_rows(self):
        r = self.ns([self.hr("25 23:10", "sleep"), self.hr("25 23:15", "sleep")], "25 23:30")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 23:10"), None))

    def test_rule1_needs_two_rows_within_30(self):
        r = self.ns([self.hr("25 23:10", "sleep")], "25 23:30")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("day", None, None))
        r = self.ns([self.hr("25 23:10", "sleep"), self.hr("25 23:45", "sleep")], "25 23:50")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("day", None, None))

    def test_rule2_fallback(self):
        r = self.ns([self.hr("25 23:40", "awake")], "26 00:30")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 23:45"), None))

    def test_rule2_not_yet(self):
        # 30-min quiet gap holds, but habitual bedtime + 30 min (00:00) not reached
        r = self.ns([self.hr("25 21:00", "awake")], "25 23:40")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("day", None, None))
        # habitual + 30 min reached, but last awake row is not older than now - 30 min
        r = self.ns([self.hr("25 23:40", "awake")], "26 00:05")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("day", None, None))

    def test_rule2_habitual_bed_at_floor(self):
        # bed_min == 1080 (18:00): habitual instant is the floor itself, not the next day
        prof = Profile(28, 50, 2, 62, 4, 0.2, 1080, 450, 8, 480, 70, 190, 0.64, 1.92)
        r = night_state(self.T0, self.at("25 19:00"), [self.hr("25 18:05", "awake")], prof, TZ)
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 18:10"), None))

    def test_sleep_rows_before_1800_ignored(self):
        r = self.ns(self.run_rows("25 14:00", "25 14:30", "sleep"), "25 15:00")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("day", None, None))

    def test_bathroom_trip(self):
        rows = (self.run_rows("25 23:10", "26 02:55", "sleep") + [self.hr("26 03:00", "awake")]
                + self.run_rows("26 03:20", "26 03:55", "sleep"))
        r = self.ns(rows, "26 04:00")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 23:10"), None))

    def wake_rows(self):
        return (self.run_rows("25 23:10", "26 06:55", "sleep")
                + [self.hr("26 07:00", "awake"), self.hr("26 07:10", "awake")])

    def test_wake_needs_30_min(self):
        r = self.ns(self.wake_rows(), "26 07:20")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 23:10"), None))
        r = self.ns(self.wake_rows(), "26 07:40")
        self.assertEqual((r.state, r.t_bed, r.t_wake),
                         ("woke", self.at("25 23:10"), self.at("26 07:00")))

    def test_woke_timeout(self):
        r = self.ns(self.wake_rows(), "26 08:59")
        self.assertEqual((r.state, r.t_bed, r.t_wake),
                         ("woke", self.at("25 23:10"), self.at("26 07:00")))
        r = self.ns(self.wake_rows(), "26 09:00")
        self.assertEqual((r.state, r.t_bed, r.t_wake),
                         ("woke_timeout", self.at("25 23:10"), self.at("26 07:00")))

    def test_oversleep_stays_night(self):
        r = self.ns(self.run_rows("25 23:10", "26 10:00", "sleep"), "26 10:05")
        self.assertEqual((r.state, r.t_bed, r.t_wake), ("night", self.at("25 23:10"), None))

    def test_sleep_estimate(self):
        self.assertAlmostEqual(sleep_estimate(19, 4, 88, 8, P), 68.8, places=1)
        self.assertEqual(sleep_estimate(19, 9, 88, 8, P), 88)

EXAMPLE_SEGS = [("07:00", "08:00", 68, 0), ("08:00", "08:30", 95, 1), ("08:30", "12:00", 70, 0),
                ("12:00", "12:30", 90, 1), ("12:30", "13:00", 72, 0), ("13:00", "13:30", 57, 0),
                ("13:30", "15:30", 80, 0), ("15:30", "18:00", 68, 0), ("18:00", "18:30", 95, 1),
                ("18:30", "19:15", 140, 1), ("19:15", "20:15", 82, 0), ("20:15", "23:00", 64, 0)]


def example_day_data(until="2026-11-25T23:00:00+08:00", history=16):
    """Raw-Oura style data for the example day (2026-11-25), cut at `until`."""
    cut = parse_ts(until)
    day0 = parse_ts("2026-11-25T00:00:00+08:00")

    def hm(hhmm):
        h, m = map(int, hhmm.split(":"))
        return day0 + h * 3600 + m * 60

    hr, kind = [], {}
    for a, b, bpm, moving in EXAMPLE_SEGS:
        for t in range(hm(a), hm(b), 300):
            kind[t] = moving
            if t <= cut:
                hr.append({"timestamp": datetime.fromtimestamp(t, TZ).isoformat(), "bpm": bpm,
                           "source": "workout" if moving else "awake"})
    base = hm("04:00")
    met = [(3.5 if kind.get(base + 60 * k - (base + 60 * k) % 300) else
            1.2 if hm("07:00") <= base + 60 * k < hm("23:00") else 1.0)
           for k in range(1440) if base + 60 * k <= cut]
    cls = "".join("4" if kind.get(base + 300 * k) else "2" if hm("07:00") <= base + 300 * k < hm("23:00")
                  else "1" for k in range(288) if base + 300 * k <= cut)
    main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 8 * 3600,
                 lowest_heart_rate=48)
    sleeps = [main] + list(days_before(date(2026, 11, 25), history, lowest_heart_rate=48).values())
    readiness = [{"day": s["day"], "score": 82} for s in sleeps]
    return {"sleep": sleeps, "daily_readiness": readiness,
            "daily_activity": [{"timestamp": "2026-11-25T04:00:00+08:00", "class_5_min": cls,
                                "met": {"interval": 60, "timestamp": "2026-11-25T04:00:00+08:00",
                                        "items": met}}],
            "workout": [], "heartrate": hr, "personal_info": {"age": 51, "biological_sex": "male"}}


def hr_row(ts, source, bpm=55):
    return {"timestamp": ts, "bpm": bpm, "source": source}


def hr_run(start, end, source):
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    out = []
    while a <= b:
        out.append(hr_row(a.isoformat(), source))
        a += timedelta(minutes=5)
    return out


class ComputeTests(unittest.TestCase):
    def run_at(self, now, data=None, **kw):
        d = data or example_day_data(until=now)
        return compute(parse_ts(now), d, 62, P, TZ, **kw)

    @staticmethod
    def cut_hr(data, until):
        data["heartrate"] = [r for r in data["heartrate"] if parse_ts(r["timestamp"]) <= parse_ts(until)]
        return data

    def test_day_flow_payload_fields(self):
        r = self.run_at("2026-11-25T15:30:00+08:00")
        self.assertEqual((r.level, r.status, r.state, r.readiness, r.anchor_day),
                         (55, "尚可", "day", 82, "2026-11-25"))
        self.assertEqual(r.trend, "draining")
        self.assertEqual(r.profile.valid_days, 16)
        self.assertEqual(r.steps[-1].start, parse_ts("2026-11-25T15:25:00+08:00"))

    def test_age_argument_is_fallback(self):
        d = example_day_data(until="2026-11-25T15:30:00+08:00")
        d["personal_info"] = {"biological_sex": "male"}
        r = self.run_at("2026-11-25T15:30:00+08:00", d, age=51)
        self.assertEqual(r.level, 55)
        self.assertAlmostEqual(r.profile.hrmax, 172.3)

    def test_note_readiness_first_hour(self):
        self.assertEqual(self.run_at("2026-11-25T07:30:00+08:00").note, "准备度82")

    def test_note_stress(self):
        self.assertEqual(self.run_at("2026-11-25T15:30:00+08:00").note, "生理压力高")

    def test_note_exercise(self):
        r = self.run_at("2026-11-25T19:00:00+08:00")
        self.assertEqual(r.note, "运动中")
        self.assertEqual(r.steps[-1].kind, "exercise")

    def spiked(self, now, bpm_1910):
        d = example_day_data(until=now)
        for r in d["heartrate"]:
            if r["timestamp"].startswith("2026-11-25T19:10"):
                r["bpm"] = bpm_1910
        return d

    def test_exercise_note_mean_over_last_three(self):
        # only the 19:10 cell is exercise among the last 3 (19:10, 19:15, 19:20)
        now = "2026-11-25T19:25:00+08:00"
        r = self.run_at(now, self.spiked(now, 160))
        self.assertEqual([s.kind == "exercise" for s in r.steps[-3:]], [True, False, False])
        self.assertGreaterEqual(r.steps[-3].load, 18)
        self.assertEqual(r.note, "运动中")
        r = self.run_at(now, self.spiked(now, 140))
        self.assertEqual([s.kind == "exercise" for s in r.steps[-3:]], [True, False, False])
        self.assertLess(r.steps[-3].load / 3, 6)
        self.assertNotEqual(r.note, "运动中")

    def test_note_priority_unsynced_over_exercise(self):
        now = "2026-11-25T19:00:00+08:00"
        d = self.cut_hr(example_day_data(until=now), "2026-11-25T15:30:00+08:00")
        met = d["daily_activity"][0]["met"]
        base = parse_ts(met["timestamp"])
        met["items"] = [8.0 if base + 60 * k >= parse_ts("2026-11-25T18:30:00+08:00") else v
                        for k, v in enumerate(met["items"])]
        r = self.run_at(now, d)
        last3 = r.steps[-3:]
        self.assertTrue(all(s.kind == "exercise" for s in last3))
        self.assertGreaterEqual(sum(s.load for s in last3) / 3, 6)
        self.assertEqual(r.note, "3h未同步")

    def test_note_priority_readiness_over_stress(self):
        now = "2026-11-25T07:50:00+08:00"
        d = example_day_data(until=now)
        for row in d["heartrate"]:
            row["bpm"] = 80
        r = self.run_at(now, d)
        last3 = r.steps[-3:]
        self.assertTrue(all(s.kind == "stress" for s in last3))
        self.assertGreaterEqual(sum(s.load for s in last3) / 3, 3)
        self.assertEqual(r.note, "准备度82")

    def test_note_unsynced_hours(self):
        d = self.cut_hr(example_day_data(until="2026-11-25T15:30:00+08:00"), "2026-11-25T12:00:00+08:00")
        r = self.run_at("2026-11-25T15:30:00+08:00", d)
        self.assertEqual(r.note, "3h未同步")
        self.assertIsNotNone(r.level)

    def test_null_after_8h_no_awake_hr(self):
        d = self.cut_hr(example_day_data(until="2026-11-25T15:30:00+08:00"), "2026-11-25T07:30:00+08:00")
        r = self.run_at("2026-11-25T15:30:00+08:00", d)
        self.assertEqual((r.level, r.status, r.trend, r.note), (None, "待同步", None, None))

    def test_sleep_rows_do_not_count_as_awake(self):
        d = self.cut_hr(example_day_data(until="2026-11-25T15:30:00+08:00"), "2026-11-25T07:30:00+08:00")
        d["heartrate"] += hr_run("2026-11-25T10:00:00+08:00", "2026-11-25T15:00:00+08:00", "sleep")
        # sleep rows before 18:00 are ignored by night_state and are not awake rows
        self.assertIsNone(self.run_at("2026-11-25T15:30:00+08:00", d).level)

    def test_no_main_sleep_today_or_yesterday(self):
        d = example_day_data(until="2026-11-25T15:30:00+08:00")
        d["sleep"] = [s for s in d["sleep"] if s["day"] < "2026-11-24"]
        r = self.run_at("2026-11-25T15:30:00+08:00", d)
        self.assertEqual((r.level, r.status, r.trend, r.anchor_day, r.profile), (None, "待同步", None, None, None))

    def test_bedtime_end_in_future_not_anchor(self):
        r = self.run_at("2026-11-25T06:00:00+08:00")
        self.assertEqual(r.anchor_day, "2026-11-24")

    def test_fallback_whole_night_no_data(self):
        d = example_day_data(until="2026-11-25T23:00:00+08:00")
        d["heartrate"].append(hr_row("2026-11-26T09:20:00+08:00", "awake"))
        r = self.run_at("2026-11-26T09:31:00+08:00", d)
        self.assertEqual((r.level, r.status, r.anchor_day, r.state), (None, "待同步", "2026-11-25", "day"))
        # one minute earlier the 2h-after-habitual-wake fallback has not fired yet
        self.assertIsNotNone(self.run_at("2026-11-26T09:29:00+08:00", d).level)

    def night_data(self, until_rows):
        d = example_day_data(until="2026-11-25T23:00:00+08:00")
        d["heartrate"] += until_rows
        return d

    def test_night_note_and_trend(self):
        d = self.night_data(hr_run("2026-11-25T23:10:00+08:00", "2026-11-26T03:30:00+08:00", "sleep"))
        now = "2026-11-26T03:30:00+08:00"  # last awake row (23:00) is 4.5h old
        r = self.run_at(now, d)
        self.assertEqual((r.state, r.note, r.trend), ("night", "睡眠预估", "charging"))
        self.assertIsNotNone(r.level)
        t_bed = parse_ts("2026-11-25T23:10:00+08:00")
        want = sleep_estimate(r.steps[-1].hp, (parse_ts(now) - t_bed) / 3600, 88, r.profile.habitual_h, P)
        self.assertEqual(r.level, round_level(want))
        self.assertGreater(r.level, round_level(r.steps[-1].hp))
        self.assertEqual(r.steps[-1].start, parse_ts("2026-11-25T23:05:00+08:00"))

    def woke_data(self):
        rows = (hr_run("2026-11-25T23:10:00+08:00", "2026-11-26T06:55:00+08:00", "sleep")
                + [hr_row("2026-11-26T07:00:00+08:00", "awake"), hr_row("2026-11-26T07:10:00+08:00", "awake")])
        return self.night_data(rows)

    def test_woke_frozen_then_null(self):
        d = self.woke_data()
        a = self.run_at("2026-11-26T07:40:00+08:00", d)
        b = self.run_at("2026-11-26T08:50:00+08:00", d)
        self.assertEqual((a.state, a.trend, a.note), ("woke", "steady", "睡眠预估"))
        self.assertEqual(a.level, b.level)
        hours = (parse_ts("2026-11-26T07:00:00+08:00") - parse_ts("2026-11-25T23:10:00+08:00")) / 3600
        self.assertEqual(a.level, round_level(sleep_estimate(a.steps[-1].hp, hours, 88, a.profile.habitual_h, P)))
        c = self.run_at("2026-11-26T09:00:00+08:00", d)
        self.assertEqual((c.state, c.level, c.status, c.trend, c.note), ("woke_timeout", None, "待同步", None, None))

    def test_new_anchor_after_sync(self):
        d = self.woke_data()
        d["sleep"].append(sleep("2026-11-26", "2026-11-25T23:10:00+08:00", "2026-11-26T07:00:00+08:00",
                                7 * 3600, lowest_heart_rate=48))
        d["daily_readiness"].append({"day": "2026-11-26", "score": 70})
        r = self.run_at("2026-11-26T07:40:00+08:00", d)
        self.assertEqual((r.anchor_day, r.state, r.readiness), ("2026-11-26", "day", 70))

    def test_calibrating_note(self):
        d = example_day_data(until="2026-11-25T10:00:00+08:00", history=3)
        r = self.run_at("2026-11-25T10:00:00+08:00", d)
        self.assertEqual((r.profile.valid_days, r.note), (3, "校准中"))

    def test_low_level_note(self):
        r = self.run_at("2026-11-25T23:00:00+08:00")
        self.assertEqual((r.level, r.status, r.note), (19, "告急", "建议休息"))

    def test_nap_just_ended_note(self):
        d = example_day_data(until="2026-11-25T15:30:00+08:00")
        d["sleep"].append(sleep("2026-11-25", "2026-11-25T14:30:00+08:00", "2026-11-25T15:25:00+08:00",
                                2400, type="late_nap"))
        r = self.run_at("2026-11-25T15:30:00+08:00", d)
        self.assertEqual(r.note, "小憩回血")

    def test_rest_note(self):
        d = example_day_data(until="2026-11-25T13:30:00+08:00")
        r = self.run_at("2026-11-25T13:30:00+08:00", d)  # 13:00-13:30 HR 57 is rest
        self.assertEqual((r.steps[-1].kind, r.note), ("rest", "静息恢复"))

    def test_status_boundaries(self):
        for lv, w in ((85, "充沛"), (84, "良好"), (65, "良好"), (64, "尚可"), (45, "尚可"), (44, "偏低"),
                      (20, "偏低"), (19, "告急"), (5, "告急"), (4, "见底"), (0, "见底"), (None, "待同步")):
            self.assertEqual(status_word(lv), w)

    def test_round_half_up(self):
        self.assertEqual(round_level(84.5), 85)

    def test_trend_thresholds(self):
        self.assertEqual(trend_of([-2.5] * 3, P), "draining")
        self.assertEqual(trend_of([-2.0] * 3, P), "steady")
        self.assertEqual(trend_of([2.5] * 3, P), "charging")

    def test_label_length(self):
        notes = ["睡眠预估", "7h未同步", "准备度100", "运动中", "生理压力高", "小憩回血", "静息恢复",
                 "建议休息", "校准中"]
        for s in ["充沛", "良好", "尚可", "偏低", "告急", "见底"]:
            for n in notes:
                self.assertLessEqual(len(f"{s} · {n}"), 16)


class DaySummaryTests(unittest.TestCase):
    def test_day_summary_example(self):
        data = example_day_data()
        data["sleep"] = data["sleep"] + [sleep("2026-11-26", "2026-11-25T23:00:00+08:00",
                                               "2026-11-26T07:00:00+08:00", 8 * 3600)]
        s = day_summary("2026-11-25", data, 62, P, TZ)
        self.assertAlmostEqual(s["bed_hp"], 19, delta=1)
        self.assertEqual(s["stress_min"], 630)
        self.assertEqual(s["recovery_min"], 30)
        self.assertEqual(s["pct_zero"], 0)
        self.assertEqual(s["pct_full"], 0)
        self.assertEqual(s["anchor_source"], "readiness")
        self.assertEqual(s["anchor"], 88)
        self.assertGreater(s["mean_load"], 0)

    def test_day_summary_no_main_sleep(self):
        self.assertIsNone(day_summary("2026-12-01", example_day_data(), 62, P, TZ))

    @staticmethod
    def with_next_sleep(start):
        data = example_day_data()
        data["sleep"] = data["sleep"] + [sleep("2026-11-26", start, "2026-11-26T07:00:00+08:00", 8 * 3600)]
        return data

    def test_day_summary_sleep_fallback(self):
        data = example_day_data()
        data["daily_readiness"] = []
        s = day_summary("2026-11-25", data, 62, P, TZ)
        self.assertEqual(s["anchor_source"], "sleep")
        self.assertEqual(s["stress_min"], 630)

    def test_day_summary_window_end_default_0400(self):
        # No next main sleep: replay runs to 04:00 next day; the unobserved tail drains hp.
        s = day_summary("2026-11-25", example_day_data(), 62, P, TZ)
        self.assertAlmostEqual(s["bed_hp"], 4.777, places=2)
        self.assertAlmostEqual(s["mean_load"], 2.3807, places=3)
        self.assertEqual((s["stress_min"], s["recovery_min"]), (630, 30))

    def test_day_summary_window_end_follows_next_sleep(self):
        s21 = day_summary("2026-11-25", self.with_next_sleep("2026-11-25T21:00:00+08:00"), 62, P, TZ)
        s23 = day_summary("2026-11-25", self.with_next_sleep("2026-11-25T23:00:00+08:00"), 62, P, TZ)
        self.assertAlmostEqual(s21["bed_hp"], 22.711, places=2)
        self.assertAlmostEqual(s23["bed_hp"], 18.711, places=2)
        self.assertAlmostEqual(s21["mean_load"], 2.7350, places=3)

    def test_day_summary_pct_zero(self):
        data = example_day_data()
        data["daily_readiness"] = [{"day": "2026-11-25", "score": 30}] + data["daily_readiness"][1:]
        s = day_summary("2026-11-25", data, 62, P, TZ)
        self.assertEqual(s["anchor"], 20)
        self.assertEqual(s["bed_hp"], 0)
        self.assertAlmostEqual(s["pct_zero"], 183 / 252, places=4)  # 21h window = 252 cells
        self.assertEqual(s["pct_full"], 0)

    def test_day_summary_mean_load_excludes_nap_cells(self):
        data = self.with_next_sleep("2026-11-25T23:00:00+08:00")
        data["sleep"].append(sleep("2026-11-25", "2026-11-25T13:00:00+08:00",
                                   "2026-11-25T13:30:00+08:00", 1500, type="sleep"))
        s = day_summary("2026-11-25", data, 62, P, TZ)
        self.assertAlmostEqual(s["mean_load"], 2.4703, places=3)
        self.assertEqual(s["recovery_min"], 0)  # the rest cells fall inside the nap
        self.assertAlmostEqual(s["bed_hp"], 20.665, places=2)

    def test_stress_unit(self):
        self.assertFalse(stress_in_minutes([2700, 3600, 1800]))
        self.assertTrue(stress_in_minutes([45, 60, 30]))


class FixWaveTests(unittest.TestCase):
    NS = NightTests

    def doze_data(self):
        d = date(2026, 11, 25)
        main = sleep("2026-11-25", "2026-11-24T23:30:00+08:00", "2026-11-25T07:30:00+08:00", 8 * 3600,
                     lowest_heart_rate=48)
        sleeps = [main] + list(days_before(d, 16, lowest_heart_rate=48).values())
        hr = (hr_run("2026-11-25T07:30:00+08:00", "2026-11-25T19:00:00+08:00", "awake")
              + hr_run("2026-11-25T19:05:00+08:00", "2026-11-25T19:45:00+08:00", "sleep")
              + hr_run("2026-11-25T19:55:00+08:00", "2026-11-25T23:20:00+08:00", "awake")
              + hr_run("2026-11-25T23:40:00+08:00", "2026-11-26T00:30:00+08:00", "sleep"))
        return {"sleep": sleeps, "daily_readiness": [{"day": "2026-11-25", "score": 80}],
                "daily_activity": [], "workout": [], "heartrate": hr}

    def test_evening_doze_is_skipped(self):
        data = self.doze_data()
        for now in ("2026-11-25T20:30:00+08:00", "2026-11-25T22:30:00+08:00"):
            r = compute(parse_ts(now), data, 62, P, TZ)
            self.assertEqual(r.state, "day", now)
        now = parse_ts("2026-11-25T23:59:00+08:00")
        self.assertEqual(compute(now, data, 62, P, TZ).state, "night")
        prof = Profile(28, 50, 2, 62, 4, 0.2, 1410, 450, 8, 480, 70, 190, 0.64, 1.92)
        ns = night_state(parse_ts("2026-11-25T07:30:00+08:00"), now, data["heartrate"], prof, TZ)
        self.assertEqual((ns.state, ns.t_bed, ns.t_wake),
                         ("night", parse_ts("2026-11-25T23:40:00+08:00"), None))

    def test_long_segment_then_wake_is_not_doze(self):
        rows = (NightTests.run_rows("25 20:00", "25 23:00", "sleep")  # span exactly 3h
                + [NightTests.hr("25 23:10", "awake"), NightTests.hr("25 23:20", "awake")])
        prof = Profile(28, 50, 2, 62, 4, 0.2, 1410, 450, 8, 480, 70, 190, 0.64, 1.92)
        r = night_state(NightTests.T0, NightTests.at("25 23:50"), rows, prof, TZ)
        self.assertEqual((r.state, r.t_bed, r.t_wake),
                         ("woke", NightTests.at("25 20:00"), NightTests.at("25 23:10")))

    def test_doze_without_confirmed_wake_is_night(self):
        rows = NightTests.run_rows("25 19:05", "25 19:45", "sleep") + [NightTests.hr("25 19:55", "awake")]
        prof = Profile(28, 50, 2, 62, 4, 0.2, 1410, 450, 8, 480, 70, 190, 0.64, 1.92)
        r = night_state(NightTests.T0, NightTests.at("25 20:10"), rows, prof, TZ)
        self.assertEqual((r.state, r.t_bed), ("night", NightTests.at("25 19:05")))

    def test_profile_hr_quiet_none_falls_back(self):
        d = date(2026, 11, 25)
        mains = days_before(d, 16, lowest_heart_rate=48)
        prof = build_profile(d, mains, {}, None, 40, "male", P, TZ)
        self.assertEqual(prof.hr_quiet, 1.25 * 48)
        self.assertEqual(build_profile(d, mains, {}, 55.0, 40, "male", P, TZ).hr_quiet, 55.0)

    def test_timestamp_unix_seconds_and_ms(self):
        from hp_model import _hr_time
        t = parse_ts("2026-11-25T10:00:00+08:00")
        self.assertEqual(_hr_time({"timestamp_unix": t}), t)
        self.assertEqual(_hr_time({"timestamp_unix": t * 1000}), t)
        data = example_day_data(until="2026-11-25T15:30:00+08:00")
        base = compute(parse_ts("2026-11-25T15:30:00+08:00"), data, 62, P, TZ)
        for r in data["heartrate"]:
            r["timestamp_unix"] = parse_ts(r["timestamp"])
        again = compute(parse_ts("2026-11-25T15:30:00+08:00"), data, 62, P, TZ)
        self.assertEqual((again.level, again.state), (base.level, base.state))

    def test_junk_records_do_not_abort(self):
        data = example_day_data(until="2026-11-25T15:30:00+08:00")
        now = parse_ts("2026-11-25T15:30:00+08:00")
        base = compute(now, data, 62, P, TZ)
        data["sleep"] += [{}, {"type": "long_sleep", "day": None},
                          {"type": "long_sleep", "day": "2026-11-20", "bedtime_end": None},
                          {"type": "sleep", "day": "2026-11-25", "bedtime_start": None,
                           "bedtime_end": "x", "total_sleep_duration": 3600}, "junk"]
        data["daily_readiness"] += [{"score": 50}, {"day": None, "score": 1}]
        data["workout"] += [{}, {"start_datetime": None, "end_datetime": None, "intensity": "easy"},
                            {"intensity": "hard"}]
        data["heartrate"] += [{"bpm": 60}, {"timestamp": None, "bpm": 60, "source": "awake"},
                              {"timestamp": "garbage", "bpm": 60, "source": "awake"}, {}]
        r = compute(now, data, 62, P, TZ)
        self.assertEqual((r.level, r.state), (base.level, base.state))
        self.assertIsNotNone(day_summary("2026-11-25", data, 62, P, TZ))

    def test_mean_load_excludes_offwrist(self):
        main = sleep("2026-11-25", "2026-11-24T23:00:00+08:00", "2026-11-25T07:00:00+08:00", 8 * 3600,
                     lowest_heart_rate=48)
        data = {"sleep": [main], "daily_readiness": [{"day": "2026-11-25", "score": 80}],
                "daily_activity": [{"timestamp": "2026-11-25T04:00:00+08:00", "class_5_min": "0" * 288}],
                "workout": [], "heartrate": []}
        s = day_summary("2026-11-25", data, 62, P, TZ)
        self.assertIsNone(s["mean_load"])
        self.assertLess(s["bed_hp"], s["anchor"])  # cells were replayed as offwrist


if __name__ == "__main__":
    unittest.main()


class DayLineTests(unittest.TestCase):
    """卡片第二行：按时机给出具体数值和建议，最多 16 个字。"""

    def steps(self, kind="still", rate=-2.0, hr=None, n=3):
        from hp_model import Step
        return [Step(at("12:00") + 300 * i, kind, rate, 50.0, hr, 1.0, 0.0) for i in range(n)]

    def line(self, hhmm, level=43, note=None, steps=None, bed_min=1410, **kw):
        from hp_model import day_line
        return day_line(self.steps() if steps is None else steps, level, note, at(hhmm),
                        mkprofile(bed_min=bed_min), P, TZ, **kw)

    def test_unsynced_keeps_note(self):
        self.assertEqual(self.line("15:00", note="3h未同步"), "3h未同步")

    def test_first_hour_readiness_and_sleep(self):
        self.assertEqual(self.line("08:00", note="准备度72", sleep_s=6.1 * 3600), "准备度72 · 睡6.1h")
        self.assertEqual(self.line("08:00", note="准备度72"), "准备度72")

    def test_exercise_shows_heart_rate(self):
        self.assertEqual(self.line("15:00", note="运动中", steps=self.steps("exercise", -8, 142)),
                         "心率142 · 运动中")

    def test_stress_shows_heart_rate_and_oura_minutes(self):
        s = self.steps("stress", -5, 92.4)
        self.assertEqual(self.line("15:00", note="生理压力高", steps=s, stress_s=4500), "心率92 · 压力75分")
        self.assertEqual(self.line("15:00", note="生理压力高", steps=s), "心率92 · 压力高 · 深呼吸")

    def test_charging_shows_rate(self):
        self.assertEqual(self.line("15:00", steps=self.steps("rest", 5.2)), "+5%/h · 回血中")
        self.assertEqual(self.line("15:00", note="小憩回血", steps=self.steps("nap", 1.0)), "+1%/h · 回血中")

    def test_very_low(self):
        self.assertEqual(self.line("15:00", level=18, steps=self.steps(rate=-3)), "-3%/h · 该休息了")

    def test_draining_forecast_hits_20_before_bed(self):
        # 35% −6%/h：2.5h 后到 20%，睡点 23:30 还远
        self.assertEqual(self.line("14:00", level=35, steps=self.steps(rate=-6)), "约2.5h后到20% · 宜小憩")
        self.assertEqual(self.line("19:00", level=35, steps=self.steps(rate=-6)), "约2.5h后到20% · 宜放松")

    def test_draining_forecast_at_bedtime(self):
        # 43% −2%/h，21:40，习惯 02:22 入睡：睡前约 34%
        self.assertEqual(self.line("21:40", bed_min=142), "睡前约34% · 宜放松")
        self.assertEqual(self.line("15:00", level=70, steps=self.steps(rate=-1)), "睡前约62% · 适合专注")
        self.assertEqual(self.line("15:00", level=55, steps=self.steps(rate=-1)), "睡前约47% · 适合轻任务")

    def test_near_bedtime_low_suggests_sleep(self):
        self.assertEqual(self.line("22:00", level=40, steps=self.steps(rate=-1)), "睡前约39% · 宜早睡")

    def test_past_bedtime(self):
        self.assertEqual(self.line("01:00", level=40, steps=self.steps(rate=-1)), "-1%/h · 该睡了")

    def test_steady_shows_rate(self):
        self.assertEqual(self.line("15:00", level=70, steps=self.steps(rate=0.4)), "+0%/h · 适合专注")

    def test_never_longer_than_16(self):
        from hp_model import day_line
        for note in (None, "准备度100", "运动中", "生理压力高", "小憩回血", "3h未同步"):
            for level in (0, 19, 44, 64, 100):
                for rate in (-40.0, -0.3, 0.0, 30.0):
                    for hh in ("03:00", "12:00", "19:00", "23:00"):
                        out = day_line(self.steps(rate=rate, hr=188), level, note, at(hh), mkprofile(), P, TZ,
                                       sleep_s=10.5 * 3600, stress_s=86400)
                        self.assertLessEqual(len(out), 16, out)

    def test_compute_sets_line_in_day(self):
        d = example_day_data(until="2026-11-25T15:30:00+08:00")
        d["daily_stress"] = [{"day": "2026-11-25", "stress_high": 4500}]
        r = compute(parse_ts("2026-11-25T15:30:00+08:00"), d, 62, P, TZ)
        self.assertEqual(r.note, "生理压力高")
        self.assertTrue(r.line.endswith("压力75分"), r.line)
