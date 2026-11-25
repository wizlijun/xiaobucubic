import base64
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import grok_auth
import grok_usage


def jwt(exp):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return 'header.' + payload + '.signature'


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'auth.json'
        self.entry = {'key': jwt(time.time() - 10), 'refresh_token': 'old-refresh-secret',
                      'auth_mode': 'oidc', 'oidc_issuer': grok_auth.ISSUER,
                      'oidc_client_id': grok_auth.CLIENT_ID, 'principal_type': 'user',
                      'principal_id': 'test-user', 'email': 'preserved@example.test',
                      'expires_at': '2000-01-01T00:00:00Z'}
        self.other = {'key': 'other-secret'}
        self.write(self.entry)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, entry):
        self.path.write_text(json.dumps({grok_auth.OIDC_SCOPE: entry, 'other-scope': self.other}))

    def response(self, **extra):
        return dict({'access_token': jwt(time.time() + 21600), 'refresh_token': 'new-refresh-secret', 'expires_in': 21600}, **extra)

    def mock_response(self, payload):
        opener = patch.object(grok_auth.urllib.request, 'build_opener')
        mocked = opener.start()
        self.addCleanup(opener.stop)
        mocked.return_value.open.return_value = io.StringIO(json.dumps(payload))
        return mocked

    def test_expired_refresh_rotates_and_preserves_all_other_fields(self):
        result = self.response()
        opener = self.mock_response(result)
        token = grok_auth.load_credentials(self.path)
        self.assertEqual(token, result['access_token'])
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['other-scope'], self.other)
        entry = saved[grok_auth.OIDC_SCOPE]
        self.assertEqual(entry['email'], self.entry['email'])
        self.assertEqual(entry['refresh_token'], result['refresh_token'])
        self.assertGreater(grok_auth.expires_at(entry), time.time() + 21000)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://auth.x.ai/oauth2/token')
        self.assertEqual(request.method, 'POST')
        self.assertNotIn('secret', request.full_url)
        form = parse_qs(request.data.decode())
        self.assertEqual(form['grant_type'], ['refresh_token'])
        self.assertEqual(form['refresh_token'], ['old-refresh-secret'])
        self.assertEqual(form['principal_id'], ['test-user'])

    def test_refresh_without_rotation_keeps_previous_refresh_token(self):
        result = self.response()
        del result['refresh_token']
        self.mock_response(result)
        grok_auth.load_credentials(self.path)
        self.assertEqual(json.loads(self.path.read_text())[grok_auth.OIDC_SCOPE]['refresh_token'], 'old-refresh-secret')

    def test_valid_token_has_no_network_or_lock_write(self):
        self.entry.update(key=jwt(time.time() + 3600), expires_at=None)
        self.write(self.entry)
        with patch.object(grok_auth, 'refresh_tokens') as refresh:
            self.assertEqual(grok_auth.load_credentials(self.path), self.entry['key'])
        refresh.assert_not_called()
        self.assertFalse(self.path.with_name('auth.json.lock').exists())

    def test_expiry_margin_and_jwt_fallback(self):
        self.entry.update(key=jwt(time.time() + 200), expires_at='invalid')
        self.write(self.entry)
        self.mock_response(self.response())
        self.assertNotEqual(grok_auth.load_credentials(self.path), self.entry['key'])

    def test_force_refresh_after_rejected_unexpired_token(self):
        self.entry.update(key=jwt(time.time() + 3600), expires_at=None)
        self.write(self.entry)
        self.mock_response(self.response())
        self.assertNotEqual(grok_auth.load_credentials(self.path, rejected_token=self.entry['key']), self.entry['key'])

    def test_adopts_cli_refresh_instead_of_spending_again(self):
        self.entry.update(key=jwt(time.time() + 3600), expires_at=None)
        self.write(self.entry)
        with patch.object(grok_auth, 'refresh_tokens') as refresh:
            self.assertEqual(grok_auth.load_credentials(self.path, rejected_token='old-token'), self.entry['key'])
        refresh.assert_not_called()

    def test_concurrent_collectors_refresh_once(self):
        updated = dict(self.entry, key=jwt(time.time() + 21600), expires_at=None,
                       refresh_token='rotated', create_time='2026-10-26T06:00:00Z')
        def exchange(entry):
            time.sleep(0.05)
            return updated
        with patch.object(grok_auth, 'refresh_tokens', side_effect=exchange) as refresh:
            with ThreadPoolExecutor(max_workers=5) as pool:
                tokens = list(pool.map(lambda _: grok_auth.load_credentials(self.path), range(5)))
        self.assertEqual(tokens, [updated['key']] * 5)
        self.assertEqual(refresh.call_count, 1)

    def test_refresh_errors_preserve_credentials_and_hide_response(self):
        for status, code, login in ((400, 'invalid_grant', True), (503, 'invalid_grant', False),
                                    (429, 'rate_limited', False), (403, 'forbidden', False)):
            with self.subTest(status=status):
                before = self.path.read_bytes()
                body = json.dumps({'error': code, 'error_description': 'old-refresh-secret'}).encode()
                error = urllib.error.HTTPError(grok_auth.TOKEN_ENDPOINT, status, 'secret', {}, io.BytesIO(body))
                with patch.object(grok_auth.urllib.request, 'build_opener') as opener:
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(RuntimeError) as caught:
                        grok_auth.load_credentials(self.path)
                self.assertEqual('grok login' in str(caught.exception), login)
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(self.path.read_bytes(), before)

    def test_network_and_malformed_response_preserve_credentials(self):
        for result in ({}, {'access_token': None}, {'access_token': 'new', 'refresh_token': ''}):
            with self.subTest(result=result), patch.object(grok_auth.urllib.request, 'build_opener') as opener:
                before = self.path.read_bytes()
                opener.return_value.open.return_value = io.StringIO(json.dumps(result))
                with self.assertRaises(RuntimeError):
                    grok_auth.load_credentials(self.path)
                self.assertEqual(self.path.read_bytes(), before)
        with patch.object(grok_auth.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = urllib.error.URLError('old-refresh-secret')
            with self.assertRaises(RuntimeError) as caught:
                grok_auth.load_credentials(self.path)
            self.assertNotIn('secret', str(caught.exception))
            self.assertNotIn('login', str(caught.exception))

    def test_untrusted_issuer_never_receives_refresh_token(self):
        self.entry['oidc_issuer'] = 'https://untrusted.example'
        self.write(self.entry)
        with patch.object(grok_auth.urllib.request, 'build_opener') as opener:
            with self.assertRaises(RuntimeError):
                grok_auth.load_credentials(self.path)
            opener.assert_not_called()

    def test_atomic_save_failure_does_not_truncate_old_credentials(self):
        before = self.path.read_bytes()
        self.mock_response(self.response())
        with patch.object(grok_auth.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                grok_auth.load_credentials(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('.grok-auth-*')), [])

    def test_environment_auth_paths(self):
        with patch.dict(os.environ, {'GROK_AUTH_PATH': '/tmp/custom-auth', 'GROK_HOME': '/tmp/custom-home'}):
            self.assertEqual(grok_auth.default_auth_path(), '/tmp/custom-auth')
        with patch.dict(os.environ, {'GROK_AUTH_PATH': '', 'GROK_HOME': '/tmp/custom-home'}):
            self.assertEqual(grok_auth.default_auth_path(), '/tmp/custom-home/auth.json')


class RetryTests(unittest.TestCase):
    def test_401_refresh_and_single_retry(self):
        with patch.object(grok_usage, 'load_credentials', side_effect=['old', 'new']) as load, \
                patch.object(grok_usage, 'fetch_usage', side_effect=[grok_usage.AuthenticationError('401'), {'billing': {}}]) as fetch:
            self.assertEqual(grok_usage.collect_usage('auth.json'), {'billing': {}})
        self.assertEqual(fetch.call_count, 2)
        load.assert_called_with('auth.json', rejected_token='old')

    def test_repeated_401_stops_without_refresh_loop(self):
        with patch.object(grok_usage, 'load_credentials', return_value='token') as load, \
                patch.object(grok_usage, 'fetch_usage', side_effect=grok_usage.AuthenticationError('401')) as fetch:
            with self.assertRaisesRegex(RuntimeError, '续期后仍返回 401'):
                grok_usage.collect_usage('auth.json')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(load.call_count, 2)

    def test_403_and_network_errors_do_not_refresh(self):
        for status in (403, 500):
            with self.subTest(status=status), patch.object(grok_usage, 'load_credentials', return_value='token') as load, \
                    patch.object(grok_usage.urllib.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = urllib.error.HTTPError('url', status, 'forbidden', {}, None)
                with self.assertRaises(RuntimeError) as caught:
                    grok_usage.collect_usage('auth.json')
                self.assertNotIn('grok login', str(caught.exception))
                self.assertEqual(load.call_count, 1)


if __name__ == '__main__':
    unittest.main()
