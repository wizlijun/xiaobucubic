import base64
import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import urlparse, parse_qs

import oura_auth

CFG = {'client_id': 'cid', 'client_secret': 'sec', 'redirect_uri': 'http://127.0.0.1:8765/callback'}
NOW = 1_000_000


def write_token(path, **kw):
    data = {'access_token': 'old_a', 'refresh_token': 'old_r', 'expires_at': NOW + 10_000, 'scope': 's'}
    data.update(kw)
    with open(path, 'w') as f:
        json.dump(data, f)


def read_token(path):
    with open(path) as f:
        return json.load(f)


class OuraAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'oura_token.json')

    def test_authorize_url(self):
        url = oura_auth.authorize_url(CFG, 'st8', 'chal')
        self.assertTrue(url.startswith('https://cloud.ouraring.com/oauth/authorize?'))
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q['response_type'], ['code'])
        self.assertEqual(q['scope'], ['personal daily heartrate workout'])
        self.assertIn('scope=personal+daily+heartrate+workout', url)
        self.assertEqual(q['code_challenge_method'], ['S256'])
        self.assertEqual(q['code_challenge'], ['chal'])
        self.assertEqual(q['state'], ['st8'])
        self.assertEqual(q['client_id'], ['cid'])
        self.assertEqual(q['redirect_uri'], [CFG['redirect_uri']])

    def test_pkce_s256(self):
        verifier, challenge = oura_auth.pkce_pair()
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        self.assertEqual(challenge, base64.urlsafe_b64encode(digest).decode().rstrip('='))
        self.assertNotIn('=', verifier)
        self.assertNotIn('=', challenge)

    def test_load_config_env_then_file(self):
        envf = os.path.join(self.tmp.name, 'oura.env')
        with open(envf, 'w') as f:
            f.write('OURA_CLIENT_ID=fileid\nOURA_CLIENT_SECRET=filesec\n# c\nOURA_REDIRECT_URI=http://127.0.0.1:1/cb\n')
        with mock.patch.dict(os.environ, {'OURA_CLIENT_ID': 'envid'}):
            cfg = oura_auth.load_config(envf)
        self.assertEqual(cfg, {'client_id': 'envid', 'client_secret': 'filesec',
                               'redirect_uri': 'http://127.0.0.1:1/cb'})

    def test_exchange_code_saves(self):
        resp = {'access_token': 'a1', 'refresh_token': 'r1', 'expires_in': 3600, 'scope': 'x'}
        with mock.patch.object(oura_auth, 'post_form', return_value=resp) as pf:
            out = oura_auth.exchange_code(CFG, 'code', 'ver', now=NOW, path=self.path)
        data = pf.call_args[0][1]
        self.assertEqual(data['grant_type'], 'authorization_code')
        self.assertEqual(data['code_verifier'], 'ver')
        self.assertEqual(data['client_secret'], 'sec')
        self.assertEqual(out['expires_at'], NOW + 3600)
        self.assertEqual(read_token(self.path)['refresh_token'], 'r1')

    def test_valid_token_no_refresh(self):
        write_token(self.path, expires_at=NOW + 301)
        with mock.patch.object(oura_auth, 'post_form') as pf:
            self.assertEqual(oura_auth.access_token(self.path, CFG, now=NOW), 'old_a')
        pf.assert_not_called()

    def test_refresh_persists_before_return(self):
        write_token(self.path, expires_at=NOW + 300)
        seen = {}

        def fake(url, data):
            seen['sent'] = data['refresh_token']
            return {'access_token': 'new_a', 'refresh_token': 'new_r', 'expires_in': 100}
        with mock.patch.object(oura_auth, 'post_form', side_effect=fake):
            tok = oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertEqual(tok, 'new_a')
        self.assertEqual(seen['sent'], 'old_r')
        saved = read_token(self.path)
        self.assertEqual((saved['access_token'], saved['refresh_token'], saved['expires_at']),
                         ('new_a', 'new_r', NOW + 100))

    def test_refresh_keeps_old_refresh_if_omitted(self):
        write_token(self.path, expires_at=NOW)
        with mock.patch.object(oura_auth, 'post_form', return_value={'access_token': 'n', 'expires_in': 5}):
            oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertEqual(read_token(self.path)['refresh_token'], 'old_r')

    def test_concurrent_refresh_once(self):
        write_token(self.path, expires_at=NOW - 1)
        calls = []

        def fake(url, data):
            calls.append(1)
            time.sleep(0.2)
            return {'access_token': 'new_a', 'refresh_token': 'new_r', 'expires_in': 3600}
        results = []
        with mock.patch.object(oura_auth, 'post_form', side_effect=fake):
            ts = [threading.Thread(target=lambda: results.append(
                oura_auth.access_token(self.path, CFG, now=NOW))) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, ['new_a', 'new_a'])

    def test_invalid_grant_raises(self):
        write_token(self.path, expires_at=NOW - 1)
        err = oura_auth.HttpError(400, {'error': 'invalid_grant'})
        with mock.patch.object(oura_auth, 'post_form', side_effect=err):
            with self.assertRaises(oura_auth.AuthRequired):
                oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertEqual(read_token(self.path)['refresh_token'], 'old_r')

    def test_other_http_error_is_runtime_not_auth(self):
        write_token(self.path, expires_at=NOW - 1)
        err = oura_auth.HttpError(500, {'error': 'boom'})
        with mock.patch.object(oura_auth, 'post_form', side_effect=err):
            with self.assertRaises(RuntimeError) as cm:
                oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertNotIsInstance(cm.exception, oura_auth.AuthRequired)
        self.assertIn('500', str(cm.exception))
        self.assertNotIn('old_r', str(cm.exception))

    def test_refresh_without_credentials_does_not_post(self):
        write_token(self.path, expires_at=NOW - 1)
        for cfg in ({'client_id': '', 'client_secret': 'sec', 'redirect_uri': 'x'},
                    {'client_id': 'cid', 'client_secret': '', 'redirect_uri': 'x'}):
            with mock.patch.object(oura_auth, 'post_form') as pf:
                with self.assertRaises(RuntimeError) as cm:
                    oura_auth.access_token(self.path, cfg, now=NOW)
            pf.assert_not_called()
            self.assertIn('oura.env', str(cm.exception))
            self.assertNotIsInstance(cm.exception, oura_auth.AuthRequired)

    def test_save_failure_does_not_return_new_token(self):
        write_token(self.path, expires_at=NOW - 1)
        resp = {'access_token': 'new_a', 'refresh_token': 'new_r', 'expires_in': 100}
        with mock.patch.object(oura_auth, 'post_form', return_value=resp), \
                mock.patch.object(oura_auth.os, 'replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertEqual(read_token(self.path)['refresh_token'], 'old_r')
        self.assertEqual([n for n in os.listdir(self.tmp.name) if n.startswith('.oura-token-')], [])

    def test_missing_or_corrupt_token(self):
        with self.assertRaises(oura_auth.AuthRequired):
            oura_auth.access_token(self.path, CFG, now=NOW)
        with open(self.path, 'w') as f:
            f.write('{bad')
        with self.assertRaises(oura_auth.AuthRequired):
            oura_auth.access_token(self.path, CFG, now=NOW)

    def test_token_file_mode_0600(self):
        write_token(self.path, expires_at=NOW - 1)
        os.chmod(self.path, 0o644)
        with mock.patch.object(oura_auth, 'post_form',
                               return_value={'access_token': 'n', 'refresh_token': 'r', 'expires_in': 9}):
            oura_auth.access_token(self.path, CFG, now=NOW)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_force_refresh(self):
        write_token(self.path, expires_at=NOW + 10_000)
        with mock.patch.object(oura_auth, 'post_form',
                               return_value={'access_token': 'f', 'refresh_token': 'fr', 'expires_in': 9}) as pf:
            self.assertEqual(oura_auth.access_token(self.path, CFG, now=NOW, force_refresh=True), 'f')
        pf.assert_called_once()


if __name__ == '__main__':
    unittest.main()
