from __future__ import annotations

import io
import json
import unittest
import urllib.error
from datetime import date, datetime
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import oura_auth
import oura_client

SH = ZoneInfo("Asia/Shanghai")
LA = ZoneInfo("America/Los_Angeles")


class Resp:
    def __init__(self, body):
        self._b = io.BytesIO(json.dumps(body).encode())

    def read(self):
        return self._b.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._b.close()


def http_error(code, headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b"{}"))


class Tok:
    def __init__(self):
        self.calls = []

    def __call__(self, force_refresh=False):
        self.calls.append(force_refresh)
        return "NEW" if force_refresh else "OLD"


def run(responses, fn, *a, **kw):
    """Call fn with urlopen mocked; returns (result, requests)."""
    reqs = []
    seq = list(responses)

    def fake(req, timeout=None):
        reqs.append((req, timeout))
        r = seq.pop(0)
        if isinstance(r, BaseException):
            raise r
        return Resp(r)

    with mock.patch("urllib.request.urlopen", fake):
        return fn(*a, **kw), reqs


def q(req):
    return parse_qs(urlsplit(req.full_url).query)


class GetTest(unittest.TestCase):
    def test_pagination(self):
        out, reqs = run([{"data": [{"a": 1}], "next_token": "abc"},
                         {"data": [{"a": 2}], "next_token": None}],
                        oura_client.get, "sleep", token=Tok(), start_date="2026-11-01")
        self.assertEqual(out, [{"a": 1}, {"a": 2}])
        self.assertNotIn("next_token", q(reqs[0][0]))
        self.assertEqual(q(reqs[1][0])["next_token"], ["abc"])
        self.assertEqual(q(reqs[1][0])["start_date"], ["2026-11-01"])
        self.assertTrue(reqs[0][0].full_url.startswith(oura_client.API + "sleep?"))

    def test_plus_encoded(self):
        _, reqs = run([{"data": []}], oura_client.get, "heartrate", token=Tok(),
                      start_datetime="2026-11-24T00:00:00+08:00")
        self.assertIn("%2B08%3A00", reqs[0][0].full_url)

    def test_user_agent_and_bearer(self):
        _, reqs = run([{"data": []}], oura_client.get, "sleep", token=Tok())
        req, timeout = reqs[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer OLD")
        self.assertEqual(req.get_header("User-agent"), oura_auth.USER_AGENT)
        self.assertEqual(timeout, 20)

    def test_429_retry_after(self):
        with self.assertRaises(oura_client.RateLimited) as c:
            run([http_error(429, {"Retry-After": "30"})], oura_client.get, "sleep", token=Tok())
        self.assertEqual(c.exception.retry_after, 30)

    def test_429_default(self):
        with self.assertRaises(oura_client.RateLimited) as c:
            run([http_error(429)], oura_client.get, "sleep", token=Tok())
        self.assertEqual(c.exception.retry_after, 60)

    def test_401_refresh_once(self):
        tok = Tok()
        out, reqs = run([http_error(401), {"data": [{"ok": 1}]}], oura_client.get, "sleep", token=tok)
        self.assertEqual(out, [{"ok": 1}])
        self.assertEqual(tok.calls, [False, True])
        self.assertEqual(reqs[1][0].get_header("Authorization"), "Bearer NEW")

    def test_401_twice_auth_required(self):
        tok = Tok()
        with self.assertRaises(oura_auth.AuthRequired) as c:
            run([http_error(401), http_error(401)], oura_client.get, "sleep", token=tok)
        self.assertEqual(tok.calls, [False, True])
        self.assertNotIn("NEW", str(c.exception))

    def test_403_names_collection(self):
        with self.assertRaises(RuntimeError) as c:
            run([http_error(403)], oura_client.get, "heartrate", token=Tok())
        self.assertIn("heartrate", str(c.exception))
        self.assertNotIsInstance(c.exception, oura_client.RateLimited)

    def test_5xx_and_network_errors(self):
        for err in (http_error(503), urllib.error.URLError("down"), OSError("x"), TimeoutError()):
            with self.assertRaises(RuntimeError) as c:
                run([err], oura_client.get, "sleep", token=Tok())
            self.assertNotIn("OLD", str(c.exception))

    def test_personal_info_not_paginated(self):
        out, reqs = run([{"age": 40, "biological_sex": "male"}], oura_client.personal_info, token=Tok())
        self.assertEqual(out["age"], 40)
        self.assertEqual(reqs[0][0].full_url, oura_client.API + "personal_info")


def now_ts(day, hh=12):
    return int(datetime(day.year, day.month, day.day, hh, tzinfo=SH).timestamp())


class FetchAllTest(unittest.TestCase):
    D = date(2026, 11, 25)

    def run_all(self, pages, tz=SH, now=None):
        return run(pages, oura_client.fetch_all, now or now_ts(self.D), tz, token=Tok())

    def days(self, *offsets):
        return [{"day": (self.D + __import__("datetime").timedelta(days=o)).isoformat()} for o in offsets]

    def test_filters_days_and_params(self):
        sleep = self.days(-31, -30, 0, 1, 2)
        ready = self.days(-31, -30, 1, 2)
        act = self.days(-2, -1, 1, 2)
        work = self.days(-2, -1, 2)
        hr = {"data": [
            {"timestamp": "2026-11-23T23:59:59+08:00"},   # before D-1 00:00
            {"timestamp": "2026-11-24T00:00:00+08:00"},   # == start, kept
            {"timestamp": "2026-11-25T03:00:00Z"},         # 11:00 local, kept
            {"timestamp": "2026-11-25T04:00:01Z"},         # 12:00:01 local > now
        ]}
        out, reqs = self.run_all([{"data": sleep}, {"data": ready}, {"data": act}, {"data": work}, hr])
        self.assertEqual([r["day"] for r in out["sleep"]],
                         ["2026-10-26", "2026-11-25", "2026-11-26"])
        self.assertEqual([r["day"] for r in out["daily_readiness"]], ["2026-10-26", "2026-11-26"])
        self.assertEqual([r["day"] for r in out["daily_activity"]], ["2026-11-24", "2026-11-26"])
        self.assertEqual([r["day"] for r in out["workout"]], ["2026-11-24"])
        self.assertEqual([r["timestamp"] for r in out["heartrate"]],
                         ["2026-11-24T00:00:00+08:00", "2026-11-25T03:00:00Z"])
        self.assertEqual(set(out), {"sleep", "daily_readiness", "daily_activity", "workout", "heartrate"})
        names = [urlsplit(r[0].full_url).path.rsplit("/", 1)[1] for r in reqs]
        self.assertEqual(names, ["sleep", "daily_readiness", "daily_activity", "workout", "heartrate"])
        # query padding D-31..D+2 for sleep, D-2..D+2 for activity
        self.assertEqual(q(reqs[0][0])["start_date"], ["2026-10-25"])
        self.assertEqual(q(reqs[0][0])["end_date"], ["2026-11-27"])
        self.assertEqual(q(reqs[2][0])["start_date"], ["2026-11-23"])
        self.assertEqual(q(reqs[2][0])["end_date"], ["2026-11-27"])
        self.assertEqual(q(reqs[4][0])["start_datetime"], ["2026-11-24T00:00:00+08:00"])
        self.assertEqual(q(reqs[4][0])["end_datetime"], ["2026-11-25T12:00:00+08:00"])

    def test_tz_decides_today_not_system(self):
        # 2026-11-25 20:00 in LA is already 11-26 in Shanghai
        now = int(datetime(2026, 11, 25, 20, tzinfo=LA).timestamp())
        empty = {"data": []}
        _, reqs = self.run_all([empty] * 5, tz=LA, now=now)
        self.assertEqual(q(reqs[0][0])["start_date"], ["2026-10-25"])
        self.assertEqual(q(reqs[4][0])["start_datetime"], ["2026-11-24T00:00:00-08:00"])
        self.assertEqual(q(reqs[4][0])["end_datetime"], ["2026-11-25T20:00:00-08:00"])


class BaselineStressTest(unittest.TestCase):
    def test_baseline_half_open(self):
        day = date(2026, 11, 25)
        rows = [{"timestamp": "2026-10-28T00:00:00+08:00"},   # == start, kept
                {"timestamp": "2026-10-27T23:59:59+08:00"},
                {"timestamp": "2026-11-24T16:00:00Z"},        # == end 11-25 00:00 local, dropped
                {"timestamp": "2026-11-24T15:59:59Z"}]
        out, reqs = run([{"data": rows}], oura_client.fetch_baseline_hr, day, SH, token=Tok())
        self.assertEqual([r["timestamp"] for r in out],
                         ["2026-10-28T00:00:00+08:00", "2026-11-24T15:59:59Z"])
        self.assertEqual(q(reqs[0][0])["start_datetime"], ["2026-10-28T00:00:00+08:00"])
        self.assertEqual(q(reqs[0][0])["end_datetime"], ["2026-11-25T00:00:00+08:00"])

    def test_stress(self):
        day = date(2026, 11, 25)
        rows = [{"day": d} for d in ("2026-10-25", "2026-10-26", "2026-11-25", "2026-11-26")]
        out, reqs = run([{"data": rows}], oura_client.fetch_stress, day, 30, token=Tok())
        self.assertEqual([r["day"] for r in out], ["2026-10-26", "2026-11-25"])
        self.assertEqual(q(reqs[0][0])["start_date"], ["2026-10-25"])
        self.assertEqual(q(reqs[0][0])["end_date"], ["2026-11-26"])
        self.assertTrue(reqs[0][0].full_url.startswith(oura_client.API + "daily_stress?"))


if __name__ == "__main__":
    unittest.main()
