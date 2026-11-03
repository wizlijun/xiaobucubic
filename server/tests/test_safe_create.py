"""Safe bot creation exercises the production HTTP handler with local fixtures."""
import concurrent.futures
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_server


class QuietHandler(display_server.Handler):
    def log_message(self, *args):
        pass


class SafeCreateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.server.daemon_threads = True
        self.server.store = display_server.Store(str(Path(self.temp.name) / 'state.json'))
        self.server.scheduler = None
        self.server.config = {'read_token': 'fixture-read', 'write_token': 'fixture-admin',
                              'message_token': 'fixture-bot', 'stale_after': 900}
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, body=None, token='fixture-bot'):
        request = urllib.request.Request(
            'http://127.0.0.1:%d/v1/messages' % self.server.server_port,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def seed_full(self):
        expiry = int(time.time()) + 3600
        self.server.store.data['messages'] = [
            {'id': 'human-%d' % i, 'text': 'human', 'expires_at': expiry} for i in range(11)
        ] + [{'id': 'old-bot', 'text': 'existing', 'sender': 'bot', 'expires_at': expiry}]

    def test_capability_advertised_without_exposing_human_messages(self):
        self.seed_full()
        status, value = self.request('GET')
        self.assertEqual(status, 200)
        self.assertEqual(value['capabilities'], {'safe_create': True})
        self.assertEqual([m['id'] for m in value['messages']], ['old-bot'])
        self.assertEqual(self.request('GET', token='unknown')[0], 401)

    def test_safe_new_id_at_capacity_cannot_evict_invisible_humans_or_old_bot(self):
        self.seed_full()
        before = json.dumps(self.server.store.data, sort_keys=True)
        status, _ = self.request('POST', {'id': 'new-bot', 'text': 'new', 'safe_create': True})
        self.assertEqual(status, 409)
        self.assertEqual(json.dumps(self.server.store.data, sort_keys=True), before)

    def test_safe_existing_id_updates_at_capacity(self):
        self.seed_full()
        status, value = self.request('POST', {'id': 'old-bot', 'text': 'updated', 'safe_create': True})
        self.assertEqual(status, 200)
        self.assertEqual(value['text'], 'updated')
        self.assertNotIn('safe_create', value)
        self.assertEqual(len(self.server.store.data['messages']), 12)

    def test_legacy_create_keeps_existing_eviction_behavior(self):
        self.seed_full()
        status, _ = self.request('POST', {'id': 'new-bot', 'text': 'new'})
        self.assertEqual(status, 200)
        identities = {m['id'] for m in self.server.store.data['messages']}
        self.assertNotIn('old-bot', identities)
        self.assertIn('new-bot', identities)
        self.assertEqual(len(identities), 12)

    def test_flag_validation_and_existing_human_authority_are_unchanged(self):
        self.seed_full()
        self.assertEqual(self.request('POST', {'id': 'new', 'text': 'new', 'safe_create': 'true'})[0], 400)
        self.assertEqual(self.request('POST', {'id': 'human-0', 'text': 'new', 'safe_create': True})[0], 409)

    def test_concurrent_safe_creates_cannot_both_consume_the_last_slot(self):
        self.seed_full()
        self.server.store.data['messages'].pop()
        barrier = threading.Barrier(2)
        def create(identity):
            barrier.wait(timeout=3)
            return self.request('POST', {'id': identity, 'text': 'new', 'safe_create': True})[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(create, ['new-1', 'new-2']))
        self.assertEqual(statuses, [200, 409])
        identities = {m['id'] for m in self.server.store.data['messages']}
        self.assertEqual(len(identities), 12)
        self.assertTrue(all('human-%d' % i in identities for i in range(11)))


if __name__ == '__main__':
    unittest.main()
