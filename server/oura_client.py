"""Oura API v2 data client: pagination, 401 refresh, error mapping."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import hp_model
import oura_auth

API = "https://api.ouraring.com/v2/usercollection/"
TIMEOUT = 20


class RateLimited(RuntimeError):
    def __init__(self, retry_after):
        super().__init__("Oura rate limited, retry after %ss" % retry_after)
        self.retry_after = retry_after


def _request(url, tok):
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + tok, "User-Agent": oura_auth.USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch(name, url, token):
    """GET one URL; refresh the token once on 401."""
    refreshed = False
    tok = token()
    while True:
        try:
            return _request(url, tok)
        except urllib.error.HTTPError as e:
            code = e.code
            retry = e.headers.get("Retry-After") if e.headers else None
            e.close()
            if code == 401:
                if refreshed:
                    raise oura_auth.AuthRequired("Oura rejected refreshed token for %s" % name) from None
                refreshed = True
                tok = token(force_refresh=True)
                continue
            if code == 429:
                try:
                    wait = int(retry or 60)
                except ValueError:
                    wait = 60
                raise RateLimited(wait) from None
            if code == 403:
                raise RuntimeError("Oura 403 for %s: check scope" % name) from None
            raise RuntimeError("Oura HTTP %s for %s" % (code, name)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise RuntimeError("Oura request for %s failed: %s" % (name, type(e).__name__)) from None


def get(collection, token=oura_auth.access_token, **params):
    rows = []
    params = dict(params)
    while True:
        url = API + collection
        if params:
            url += "?" + urllib.parse.urlencode(params)
        page = _fetch(collection, url, token)
        rows.extend(page.get("data") or [])
        nxt = page.get("next_token")
        if not nxt:
            return rows
        params["next_token"] = nxt


def personal_info(token=oura_auth.access_token):
    return _fetch("personal_info", API + "personal_info", token)


def _midnight(day, tz):
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def _by_day(rows, lo, hi):
    return [r for r in rows if lo.isoformat() <= r.get("day", "") <= hi.isoformat()]


def _daily(name, lo, hi, token):
    one = timedelta(days=1)
    rows = get(name, token, start_date=(lo - one).isoformat(), end_date=(hi + one).isoformat())
    return _by_day(rows, lo, hi)


def _heartrate(start, end, token):
    rows = get("heartrate", token, start_datetime=start.isoformat(), end_datetime=end.isoformat())
    return [r for r in rows if int(start.timestamp()) <= hp_model.parse_ts(r["timestamp"]) <= int(end.timestamp())]


def fetch_all(now, tz, token=oura_auth.access_token):
    d = datetime.fromtimestamp(now, tz).date()
    one = timedelta(days=1)
    return {
        "sleep": _daily("sleep", d - 30 * one, d + one, token),
        "daily_readiness": _daily("daily_readiness", d - 30 * one, d + one, token),
        "daily_activity": _daily("daily_activity", d - one, d + one, token),
        "workout": _daily("workout", d - one, d + one, token),
        "heartrate": _heartrate(_midnight(d - one, tz), datetime.fromtimestamp(now, tz), token),
    }


def fetch_baseline_hr(day, tz, token=oura_auth.access_token):
    start, end = _midnight(day - timedelta(days=28), tz), _midnight(day, tz)
    rows = get("heartrate", token, start_datetime=start.isoformat(), end_datetime=end.isoformat())
    return [r for r in rows if int(start.timestamp()) <= hp_model.parse_ts(r["timestamp"]) < int(end.timestamp())]


def fetch_stress(day, days, token=oura_auth.access_token):
    one = timedelta(days=1)
    rows = get("daily_stress", token, start_date=(day - timedelta(days=days) - one).isoformat(),
               end_date=(day + one).isoformat())
    return _by_day(rows, day - timedelta(days=days), day)
