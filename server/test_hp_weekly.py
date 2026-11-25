import math
import unittest
from datetime import timedelta, timezone

import hp_weekly
from hp_model import Step, parse_ts
from test_hp_model import mkprofile

TZ = timezone(timedelta(hours=8))
NOW = parse_ts("2026-11-25T22:00:00+08:00")      # 周三
START = parse_ts("2026-11-21T12:00:00+08:00")    # 周六 12:00
RESET = parse_ts("2026-11-28T12:00:00+08:00")


def night(day, start, end, total_h, **kw):
    r = {"day": day, "bedtime_start": start, "bedtime_end": end,
         "total_sleep_duration": int(total_h * 3600), "type": "long_sleep"}
    r.update(kw)
    return r


def act(day, med=0, high=0, steps=8000):
    return {"day": day, "medium_activity_time": med * 60, "high_activity_time": high * 60, "steps": steps}


ENOUGH = [act("2026-11-22", med=100)]  # 抵消运动不足，单独测其它项


def run(now=NOW, sleeps=(), activities=ENOUGH, stress=(), steps=(), profile=None):
    return hp_weekly.compute(now, TZ, list(sleeps), list(activities), list(stress), list(steps), profile)


def cells(start_iso, n, kind="still", hp=50.0):
    t = parse_ts(start_iso)
    return [Step(t + 300 * i, kind, 0.0, hp, None, None, 0.0) for i in range(n)]


class WeekBoundsTests(unittest.TestCase):
    def test_saturday_noon_boundary(self):
        self.assertEqual(hp_weekly.week_bounds(parse_ts("2026-11-21T11:59:00+08:00"), TZ),
                         (START - 7 * 86400, START))
        self.assertEqual(hp_weekly.week_bounds(START, TZ), (START, RESET))
        self.assertEqual(hp_weekly.week_bounds(NOW, TZ), (START, RESET))

    def test_reset_at_in_result(self):
        self.assertEqual(run()["reset_at"], RESET)


class SleepTests(unittest.TestCase):
    def test_deficit_and_capped_surplus(self):
        w = run(sleeps=[night("2026-11-22", "2026-11-21T23:00:00+08:00", "2026-11-22T05:00:00+08:00", 5),
                        night("2026-11-23", "2026-11-22T22:00:00+08:00", "2026-11-23T09:00:00+08:00", 10)])
        self.assertEqual(w["items"]["sleep"], 2.0)
        self.assertEqual(w["debt_hours"], 0.0)   # 10h 只按 9h 还 2h
        self.assertEqual(w["remaining_percent"], 100)

    def test_surplus_cannot_be_banked(self):
        w = run(sleeps=[night("2026-11-22", "2026-11-21T23:00:00+08:00", "2026-11-22T08:00:00+08:00", 9),
                        night("2026-11-23", "2026-11-22T23:00:00+08:00", "2026-11-23T04:00:00+08:00", 5)])
        self.assertEqual(w["debt_hours"], 2.0)

    def test_night_before_week_start_ignored(self):
        w = run(sleeps=[night("2026-11-21", "2026-11-21T03:00:00+08:00", "2026-11-21T07:00:00+08:00", 4)])
        self.assertEqual(w["items"]["sleep"], 0.0)

    def test_nap_counts_as_sleep(self):
        nap = {"day": "2026-11-22", "bedtime_start": "2026-11-22T14:00:00+08:00",
               "bedtime_end": "2026-11-22T15:00:00+08:00", "total_sleep_duration": 3600, "type": "late_nap"}
        w = run(sleeps=[night("2026-11-22", "2026-11-21T23:00:00+08:00", "2026-11-22T05:00:00+08:00", 5), nap])
        self.assertEqual(w["items"]["sleep"], 1.0)

    def test_late_bedtime(self):
        w = run(sleeps=[night("2026-11-23", "2026-11-23T02:30:00+08:00", "2026-11-23T09:30:00+08:00", 7)])
        self.assertEqual(w["items"]["late"], 0.62)   # 2.5h × 0.25
        w = run(sleeps=[night("2026-11-23", "2026-11-22T23:30:00+08:00", "2026-11-23T06:30:00+08:00", 7)])
        self.assertEqual(w["items"]["late"], 0.0)

    def test_late_uses_ring_offset_not_system_tz(self):
        jst = timezone(timedelta(hours=9))   # 系统时区和戒指记录的时区不同
        n = night("2026-11-23", "2026-11-22T23:30:00+08:00", "2026-11-23T06:30:00+08:00", 7)
        w = hp_weekly.compute(NOW, jst, [n], ENOUGH, [], [], None)
        self.assertEqual(w["items"]["late"], 0.0)


class ActivityTests(unittest.TestCase):
    def test_exercise_shortfall_is_prorated(self):
        w = run(activities=[])
        expected = 150 * (NOW - START) / (RESET - START)
        self.assertEqual(w["items"]["exercise_low"], round(expected / 60, 2))
        w = run(now=START + 3600, activities=[])
        self.assertLess(w["items"]["exercise_low"], 0.02)

    def test_high_intensity_counts_double(self):
        w = run(activities=[act("2026-11-22", high=50)])
        self.assertEqual(w["items"]["exercise_low"], 0.0)

    def test_exercise_high_over_300(self):
        w = run(activities=[act("2026-11-22", high=200), act("2026-11-23", high=120)])
        self.assertEqual(w["items"]["exercise_high"], 0.33)

    def test_sedentary_days(self):
        w = run(activities=[act("2026-11-20", med=100, steps=1000),   # 上周
                            act("2026-11-21", steps=2000),             # 周六算本周
                            act("2026-11-22", med=100, steps=3000),
                            act("2026-11-25", steps=1000)])            # 今天未结束
        self.assertEqual(w["items"]["sedentary"], 0.5)

    def test_stress_seconds_and_minutes(self):
        for rows in ([{"day": "2026-11-22", "stress_high": 7200}, {"day": "2026-11-23", "stress_high": 3000}],
                     [{"day": "2026-11-22", "stress_high": 120}, {"day": "2026-11-23", "stress_high": 50}]):
            self.assertEqual(run(stress=rows)["items"]["stress"], 0.5)

    def test_calm_week_in_seconds_not_read_as_minutes(self):
        rows = [{"day": "2026-11-22", "stress_high": 900}, {"day": "2026-11-23", "stress_high": 900}]
        self.assertEqual(run(stress=rows)["items"]["stress"], 0.0)

    def test_unit_judged_from_all_rows(self):
        rows = [{"day": "2026-11-18", "stress_high": 8100}, {"day": "2026-11-22", "stress_high": 1350}]
        self.assertEqual(run(stress=rows)["items"]["stress"], 0.0)   # 1350 秒 = 22.5 分钟


class CellTests(unittest.TestCase):
    def test_drain_and_rest_only_inside_week(self):
        steps = (cells("2026-11-21T10:00:00+08:00", 12, hp=10)        # 周六上午，属上周
                 + cells("2026-11-22T13:00:00+08:00", 12, hp=15)      # 透支 1h → 0.5
                 + cells("2026-11-22T15:00:00+08:00", 12, kind="rest") # 休息 1h → 还 0.25
                 + cells("2026-11-22T17:00:00+08:00", 6, kind="nap", hp=5))
        w = run(steps=steps)
        self.assertEqual(w["items"]["drain"], 0.5)
        self.assertEqual(w["debt_hours"], 0.2)   # 0.25 四舍五入到 1 位


class RecoveryTests(unittest.TestCase):
    def test_low_hrv_or_high_rhr_once_per_night(self):
        prof = mkprofile(ln_hrv_med=math.log(50), ln_hrv_mad=0.1, rhr=50, rhr_mad=2)
        n = night("2026-11-23", "2026-11-22T23:00:00+08:00", "2026-11-23T06:00:00+08:00", 7,
                  average_hrv=35, lowest_heart_rate=56)
        self.assertEqual(run(sleeps=[n], profile=prof)["items"]["recovery"], 1.0)
        ok = dict(n, average_hrv=50, lowest_heart_rate=50)
        self.assertEqual(run(sleeps=[ok], profile=prof)["items"]["recovery"], 0.0)
        self.assertEqual(run(sleeps=[n], profile=None)["items"]["recovery"], 0.0)

    def test_rhr_needs_three_bpm(self):
        prof = mkprofile(ln_hrv_med=math.log(50), ln_hrv_mad=0.1, rhr=48, rhr_mad=1)
        base = night("2026-11-23", "2026-11-22T23:00:00+08:00", "2026-11-23T06:00:00+08:00", 7, average_hrv=50)
        self.assertEqual(run(sleeps=[dict(base, lowest_heart_rate=50)], profile=prof)["items"]["recovery"], 0.0)
        self.assertEqual(run(sleeps=[dict(base, lowest_heart_rate=51)], profile=prof)["items"]["recovery"], 1.0)


class OutputTests(unittest.TestCase):
    def short_nights(self, hours):
        out = []
        for i, d in enumerate(("2026-11-22", "2026-11-23", "2026-11-24")):
            prev = ("2026-11-21", "2026-11-22", "2026-11-23")[i]
            out.append(night(d, prev + "T23:00:00+08:00", d + "T05:00:00+08:00", hours))
        return out

    def test_line_when_low(self):
        w = run(sleeps=self.short_nights(5))   # 欠 6h
        self.assertEqual(w["top"], "sleep")
        self.assertEqual(w["remaining_percent"], 14)
        self.assertEqual(hp_weekly.line(w), "本周欠6.0h · 该补觉")

    def test_no_line_when_enough(self):
        w = run(sleeps=self.short_nights(6))   # 欠 3h
        self.assertIsNone(hp_weekly.line(w))
        self.assertIsNone(hp_weekly.line(None))

    def test_clamped_and_top_none(self):
        self.assertEqual(run(sleeps=self.short_nights(2))["remaining_percent"], 0)
        w = run()
        self.assertIsNone(w["top"])
        self.assertEqual(w["remaining_percent"], 100)

    def test_ledger_rows(self):
        w = run(sleeps=self.short_nights(5))
        self.assertEqual([r["day"] for r in w["days"]], ["2026-11-22", "2026-11-23", "2026-11-24"])
        self.assertEqual(w["days"][-1]["balance"], 6.0)

    def test_public_strips_ledger(self):
        self.assertNotIn("days", hp_weekly.public(run()))


if __name__ == "__main__":
    unittest.main()
