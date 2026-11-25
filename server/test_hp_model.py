import unittest
from datetime import date, datetime, timedelta, timezone

from hp_model import (DEFAULT_PARAMS, Cell, Profile, anchor_value, build_cells,
                      build_profile, data_horizon, main_sleeps, make_params,
                      nap_periods, parse_ts, quiet_hr, replay)

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


if __name__ == "__main__":
    unittest.main()
