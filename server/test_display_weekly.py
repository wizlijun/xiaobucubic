import dataclasses
import unittest

import display_server
import hp_model
import hp_usage

NOW = 1795581200
WEEKLY = {"remaining_percent": 14, "debt_hours": 6.0, "reset_at": 1795834800, "top": "sleep",
          "items": {"sleep": 6.0, "late": 0.0}}


def energy(**kw):
    body = {"level_percent": 40, "status": "尚可", "source": "estimated", "updated_at": NOW}
    body.update(kw)
    return body


class CleanWeeklyTests(unittest.TestCase):
    def test_valid_weekly_kept(self):
        item = display_server.clean_energy(energy(weekly=WEEKLY), NOW)
        self.assertEqual(item["weekly"], WEEKLY)

    def test_missing_weekly_omitted(self):
        self.assertNotIn("weekly", display_server.clean_energy(energy(), NOW))
        self.assertNotIn("weekly", display_server.clean_energy(energy(weekly=None), NOW))

    def test_unknown_fields_dropped_and_clamped(self):
        item = display_server.clean_energy(energy(weekly=dict(WEEKLY, remaining_percent=130, days=[1])), NOW)
        self.assertEqual(item["weekly"]["remaining_percent"], 100)
        self.assertNotIn("days", item["weekly"])

    def test_invalid_weekly_rejected(self):
        bad = ["x", {"reset_at": 1795834800}, dict(WEEKLY, reset_at=None), dict(WEEKLY, reset_at=1795834800000),
               dict(WEEKLY, remaining_percent="14"), dict(WEEKLY, top="naps"),
               dict(WEEKLY, items={"naps": 1}), dict(WEEKLY, items=[1])]
        for w in bad:
            with self.assertRaises(display_server.BadRequest, msg=repr(w)):
                display_server.clean_energy(energy(weekly=w), NOW)


class SubscriptionTests(unittest.TestCase):
    def test_second_window(self):
        e = display_server.clean_energy(energy(weekly=WEEKLY), NOW)
        sub = display_server.energy_to_subscription(e, 900, NOW)
        self.assertEqual(len(sub["windows"]), 2)
        self.assertEqual(sub["windows"][1], {"label": "7天", "used_percent": 86, "reset_at": 1795834800})

    def test_single_window_without_weekly(self):
        sub = display_server.energy_to_subscription(display_server.clean_energy(energy(), NOW), 900, NOW)
        self.assertEqual(len(sub["windows"]), 1)

    def test_hp_usage_item_round_trip(self):
        res = hp_model.Result(level=40, status="尚可", trend="draining", note=None, state="day", steps=[],
                              anchor_day=None, readiness=None, profile=None,
                              weekly=dict(WEEKLY, days=[{"day": "2026-11-22"}]))
        e = display_server.clean_energy(hp_usage.build_item(res, NOW), NOW)
        self.assertEqual(e["weekly"]["top"], "sleep")
        sub = display_server.energy_to_subscription(e, 900, NOW)
        self.assertEqual(sub["windows"][1]["used_percent"], 86)


if __name__ == "__main__":
    unittest.main()
