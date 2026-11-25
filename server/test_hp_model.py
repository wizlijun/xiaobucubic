import unittest
from datetime import date, datetime, timedelta, timezone

from hp_model import (DEFAULT_PARAMS, anchor_value, build_profile, main_sleeps,
                      make_params, nap_periods, parse_ts, quiet_hr)

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


if __name__ == "__main__":
    unittest.main()
