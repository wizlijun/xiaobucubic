"""Oura OAuth2 (PKCE) login and single-use refresh token handling (stdlib only)."""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, 'oura_token.json')
ENV_FILE = os.path.join(HERE, 'oura.env')
AUTHORIZE_URL = 'https://cloud.ouraring.com/oauth/authorize'
TOKEN_URL = 'https://api.ouraring.com/oauth/token'
USER_AGENT = 'xiaobucubic-hp/1'
SCOPE = 'personal daily heartrate workout'
REFRESH_MARGIN = 300
LOCK_TIMEOUT = 30


class AuthRequired(RuntimeError):
    """Refresh token unusable; run `python3 oura_auth.py login`."""


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__('HTTP %s' % status)
        self.status = status
        self.body = body if isinstance(body, dict) else {}


def load_config(env_file=ENV_FILE):
    values = {}
    try:
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    values[k.strip()] = v.strip().strip('"\'')
    except OSError:
        pass

    def pick(name):
        return os.environ.get(name) or values.get(name, '')
    return {'client_id': pick('OURA_CLIENT_ID'), 'client_secret': pick('OURA_CLIENT_SECRET'),
            'redirect_uri': pick('OURA_REDIRECT_URI') or 'http://127.0.0.1:8765/callback'}


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def pkce_pair():
    verifier = _b64(secrets.token_bytes(48))
    return verifier, _b64(hashlib.sha256(verifier.encode('ascii')).digest())


def authorize_url(cfg, state, challenge):
    return AUTHORIZE_URL + '?' + urlencode({
        'response_type': 'code', 'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'],
        'scope': SCOPE, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})


def post_form(url, data):
    req = urllib.request.Request(url, data=urlencode(data).encode(), method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json',
        'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(8192))
        except (ValueError, OSError):
            body = {}
        raise HttpError(exc.code, body) from None


def _call_token(data):
    try:
        return post_form(TOKEN_URL, data)
    except HttpError as exc:
        err = exc.body.get('error')
        if err == 'invalid_grant':
            raise AuthRequired('Oura refresh token invalid; run `python3 oura_auth.py login`') from None
        raise RuntimeError('Oura token request failed: HTTP %s %s' % (exc.status, err or '')) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise RuntimeError('Oura token request failed (network or bad response)') from None


def _save(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.oura-token-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise AuthRequired('Oura token missing or unreadable; run `python3 oura_auth.py login`') from None
    if not isinstance(data, dict) or not data.get('access_token') or not data.get('refresh_token'):
        raise AuthRequired('Oura token file invalid; run `python3 oura_auth.py login`')
    return data


def _store(path, resp, old, now):
    if not isinstance(resp, dict) or not resp.get('access_token'):
        raise RuntimeError('Oura token response missing access_token')
    new = {'access_token': resp['access_token'],
           'refresh_token': resp.get('refresh_token') or old.get('refresh_token'),
           'expires_at': int(now + int(resp.get('expires_in') or 3600)),
           'scope': resp.get('scope') or old.get('scope', SCOPE)}
    _save(path, new)
    return new


def exchange_code(cfg, code, verifier, now=None, path=TOKEN_FILE):
    now = time.time() if now is None else now
    resp = _call_token({'grant_type': 'authorization_code', 'code': code, 'code_verifier': verifier,
                        'redirect_uri': cfg['redirect_uri'], 'client_id': cfg['client_id'],
                        'client_secret': cfg['client_secret']})
    return _store(path, resp, {}, now)


@contextmanager
def _lock(path):
    fd = os.open(path + '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Oura token lock timeout') from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _fresh(data, now):
    return data.get('expires_at', 0) - REFRESH_MARGIN > now


def access_token(path=TOKEN_FILE, cfg=None, now=None, force_refresh=False):
    now = time.time() if now is None else now
    data = _read(path)
    if not force_refresh and _fresh(data, now):
        return data['access_token']
    with _lock(path):
        data = _read(path)  # another process may have refreshed meanwhile
        if not force_refresh and _fresh(data, now):
            return data['access_token']
        cfg = cfg or load_config()
        if not cfg.get('client_id') or not cfg.get('client_secret'):
            raise RuntimeError('Set OURA_CLIENT_ID and OURA_CLIENT_SECRET in oura.env')
        resp = _call_token({'grant_type': 'refresh_token', 'refresh_token': data['refresh_token'],
                            'client_id': cfg['client_id'], 'client_secret': cfg['client_secret']})
        return _store(path, resp, data, now)['access_token']


def _login():
    cfg = load_config()
    if not cfg['client_id'] or not cfg['client_secret']:
        sys.exit('Set OURA_CLIENT_ID and OURA_CLIENT_SECRET in oura.env')
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce_pair()
    redirect = urlparse(cfg['redirect_uri'])
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            if u.path != redirect.path:
                self.send_response(404)
                self.end_headers()
                return
            result['q'] = {k: v[0] for k, v in parse_qs(u.query).items()}
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Oura login done. You can close this tab.')

        def log_message(self, *args):
            pass

    print('Open this URL in a browser:\n' + authorize_url(cfg, state, challenge))
    with HTTPServer(('127.0.0.1', redirect.port or 8765), Handler) as server:
        while 'q' not in result:
            server.handle_request()
    q = result['q']
    if not secrets.compare_digest(q.get('state', ''), state):
        sys.exit('state mismatch')
    if not q.get('code'):
        sys.exit('authorization failed: %s' % q.get('error', 'no code'))
    exchange_code(cfg, q['code'], verifier)
    print('Token saved to', TOKEN_FILE)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ['login']:
        sys.exit('usage: oura_auth.py login')
    _login()


if __name__ == '__main__':
    main()
