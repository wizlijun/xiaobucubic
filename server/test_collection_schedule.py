import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import display_push
import display_server
import weather_shenzhen


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def wall(self):
        return 1800000000 + self.now


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.scheduler = display_server.Scheduler(clock=self.clock.monotonic, wall_clock=self.clock.wall)

    def test_idle_start_and_polling_do_not_activate_upstream(self):
        for _ in range(10):
            command = self.scheduler.poll('bandwagon')
            self.assertFalse(command['query_now'])
            self.assertTrue(command['paused'])
            self.assertEqual(command['poll_after_seconds'], 15)
            self.clock.now += 3600
        self.assertIsNone(self.scheduler.last_request)

    def test_upload_controls_next_query_despite_frequent_reads(self):
        self.scheduler.on_request()
        command = self.scheduler.poll('bandwagon')
        self.assertTrue(command['query_now'])
        save = Mock()
        reply = self.scheduler.submit('bandwagon', command['lease_id'], save)
        save.assert_called_once()
        self.assertEqual(reply['next_query_after_seconds'], 600)
        for second in (1, 15, 60, 300, 599):
            self.clock.now = second
            self.scheduler.on_request()
            self.assertFalse(self.scheduler.poll('bandwagon')['query_now'])
        self.clock.now = 600
        self.scheduler.on_request()
        self.assertTrue(self.scheduler.poll('bandwagon')['query_now'])

    def test_idle_pause_resume_and_fresh_cache(self):
        self.scheduler.on_request()
        lease = self.scheduler.poll('bandwagon')['lease_id']
        self.scheduler.submit('bandwagon', lease, lambda: None)
        self.clock.now = 180
        self.assertTrue(self.scheduler.poll('bandwagon')['paused'])
        self.scheduler.on_request()
        self.assertFalse(self.scheduler.poll('bandwagon')['query_now'])
        self.clock.now = 900
        self.assertFalse(self.scheduler.poll('bandwagon')['query_now'])
        self.scheduler.on_request()
        self.assertTrue(self.scheduler.poll('bandwagon')['query_now'])

    def test_failures_back_off_independently_and_keep_old_cache(self):
        for delay in (600, 1200, 2400, 3600, 3600):
            self.scheduler.on_request()
            lease = self.scheduler.poll('bandwagon')['lease_id']
            self.assertIsNotNone(lease)
            reply = self.scheduler.failure('bandwagon', lease)
            self.assertEqual(reply['next_query_after_seconds'], delay)
            self.assertFalse(self.scheduler.poll('bandwagon')['query_now'])
            self.clock.now += delay
        self.scheduler.on_request()
        self.assertTrue(self.scheduler.poll('weather')['query_now'])

    def test_duplicate_workers_get_only_one_lease(self):
        self.scheduler.on_request()
        with ThreadPoolExecutor(max_workers=8) as pool:
            commands = list(pool.map(lambda _: self.scheduler.poll('bandwagon'), range(20)))
        self.assertEqual(sum(command['query_now'] for command in commands), 1)

    def test_expired_lease_rejects_late_result_and_backs_off(self):
        self.scheduler.on_request()
        lease = self.scheduler.poll('bandwagon')['lease_id']
        self.clock.now = display_server.COLLECT_TIMEOUT
        save = Mock()
        with self.assertRaises(display_server.Conflict):
            self.scheduler.submit('bandwagon', lease, save)
        save.assert_not_called()
        command = self.scheduler.poll('bandwagon')
        self.assertEqual(command['reason'], 'retry_backoff')
        self.assertEqual(command['next_query_after_seconds'], 600)

    def test_recent_persisted_cache_not_downloaded_after_restart(self):
        scheduler = display_server.Scheduler(clock=self.clock.monotonic, wall_clock=self.clock.wall,
                                             initial={'bandwagon': self.clock.wall() - 200})
        scheduler.on_request()
        command = scheduler.poll('bandwagon')
        self.assertFalse(command['query_now'])
        self.assertEqual(command['next_query_after_seconds'], 400)


class QuietHandler(display_server.Handler):
    def log_message(self, *args):
        pass


class EndLoop(BaseException):
    pass


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.server = display_server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.server.daemon_threads = True
        self.server.store = display_server.Store(self.temp.name + '/state.json')
        self.server.config = {'read_token': 'reader', 'write_token': 'writer', 'message_token': 'bot', 'stale_after': 900}
        self.server.scheduler = display_server.Scheduler(clock=self.clock.monotonic, wall_clock=self.clock.wall)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        self.token = patch.object(display_push, 'write_token', return_value='writer')
        self.token.start()
        self.item = {'id': 'bandwagon', 'name': 'Bandwagon', 'updated_at': int(self.clock.wall()),
                     'windows': [{'label': '本期', 'used_percent': 20}]}

    def tearDown(self):
        self.token.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path, token='reader'):
        req = urllib.request.Request(self.url + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def poll(self, name='bandwagon'):
        return display_push.request_json(self.url, '/v1/collectors/' + name + '/poll', {})['collection']

    def test_http_poll_upload_and_read_permissions(self):
        self.get('/healthz')
        self.assertTrue(self.poll()['paused'])
        with self.assertRaises(urllib.error.HTTPError):
            self.get('/v1/display', 'wrong')
        self.assertTrue(self.poll()['paused'])
        for token in ('reader', 'bot', ''):
            with patch.object(display_push, 'write_token', return_value=token):
                with self.assertRaises(RuntimeError):
                    self.poll()
        self.get('/v1/display')
        lease = self.poll()['lease_id']
        self.assertIsNotNone(lease)
        self.assertFalse(self.poll()['query_now'])
        reply = display_push.push(self.url, self.item, lease=lease)
        self.assertEqual(reply['collection']['next_query_after_seconds'], 600)
        saved = self.get('/v1/display')['subscriptions'][0]
        self.assertNotIn('collection', saved)
        self.assertNotIn('lease_id', saved)
        with self.assertRaises(RuntimeError):
            display_push.push(self.url, dict(self.item, name='late'), lease=lease)
        self.assertEqual(self.get('/v1/display')['subscriptions'][0]['name'], 'Bandwagon')
        self.clock.now = 900
        self.assertTrue(self.poll()['paused'])
        self.get('/v1/display')
        self.assertTrue(self.poll()['query_now'])

    def test_weather_upload_also_returns_instructions(self):
        self.get('/v1/display')
        lease = self.poll('weather')['lease_id']
        reply = display_push.push(self.url, {'city': '深圳', 'updated_at': int(self.clock.wall())},
                                  '/v1/weather', lease=lease)
        self.assertEqual(reply['collection']['collector'], 'weather')
        self.assertEqual(reply['collection']['next_query_after_seconds'], 600)

    def test_worker_waits_for_server_and_resumes_after_client_returns(self):
        args = SimpleNamespace(push=self.url, follow=True, interval=0, collector='bandwagon')
        collect = Mock(return_value=self.item)
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            count = len(sleeps)
            if count == 1:
                collect.assert_not_called()  # 启动时无客户端：不查询上游。
                self.get('/v1/display')
            elif count == 2:
                self.assertEqual(collect.call_count, 1)
                self.clock.now = 900  # 客户端离开，缓存到期也不能查询。
            elif count == 3:
                self.assertEqual(collect.call_count, 1)
                self.get('/v1/display')
            elif count == 4:
                self.assertEqual(collect.call_count, 2)
                raise EndLoop

        with patch.object(display_push.time, 'sleep', side_effect=sleep), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EndLoop):
                display_push.run(args, collect)
        self.assertEqual(sleeps, [15, 15, 15, 15])

    def test_worker_failure_reports_backoff_and_preserves_data(self):
        display_push.push(self.url, self.item)
        self.clock.now = 600
        self.get('/v1/display')
        args = SimpleNamespace(push=self.url, follow=True, interval=0, collector='bandwagon')
        with patch.object(display_push.time, 'sleep', side_effect=EndLoop), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(EndLoop):
                display_push.run(args, Mock(side_effect=RuntimeError('upstream unavailable')))
        self.assertEqual(self.poll()['reason'], 'retry_backoff')
        self.assertEqual(self.get('/v1/display')['subscriptions'][0]['updated_at'], self.item['updated_at'])

    def test_worker_never_queries_when_control_is_unavailable_or_invalid(self):
        args = SimpleNamespace(push=self.url, follow=True, interval=0, collector='bandwagon')
        for outcome in (RuntimeError('offline'), {}, {'collection': {'query_now': True, 'poll_after_seconds': 15}}):
            collect = Mock()
            kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with patch.object(display_push, 'request_json', **kwargs), \
                    patch.object(display_push.time, 'sleep', side_effect=EndLoop), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(EndLoop):
                    display_push.run(args, collect)
            collect.assert_not_called()

    def test_worker_obeys_upload_response_poll_delay(self):
        args = SimpleNamespace(push=self.url, follow=True, interval=300, collector='bandwagon')
        grant = {'collection': {'query_now': True, 'lease_id': 'lease', 'poll_after_seconds': 15}}
        uploaded = {'collection': {'query_now': False, 'poll_after_seconds': 47}}
        with patch.object(display_push, 'request_json', return_value=grant), \
                patch.object(display_push, 'push', return_value=uploaded), \
                patch.object(display_push.time, 'sleep', side_effect=EndLoop) as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(EndLoop):
                display_push.run(args, lambda: self.item)
        sleep.assert_called_once_with(47)

    def test_supervise_collector_stops_on_clean_zero_exit(self):
        proc = Mock()
        proc.poll.return_value = 0
        proc.returncode = 0
        stop = threading.Event()
        with patch.object(display_server.subprocess, 'Popen', return_value=proc) as popen, \
                patch.object(stop, 'wait', return_value=False), \
                patch.object(display_server, 'log'):
            display_server.supervise_collector('bandwagon', 'http://127.0.0.1:8007', stop)
        popen.assert_called_once()

    def test_handler_route_tolerates_missing_path(self):
        handler = display_server.Handler.__new__(display_server.Handler)
        self.assertIsNone(handler._route())

    def test_weather_updated_at_uses_fetch_time_not_15min_slot(self):
        sample = {
            'current': {'time': 1795698000, 'temperature_2m': 17.0, 'weather_code': 0},
            'hourly': {'weather_code': [2], 'precipitation_probability': [10]},
            'daily': {'temperature_2m_min': [14.0], 'temperature_2m_max': [20.0]},
        }
        with patch.object(weather_shenzhen.time, 'time', return_value=1795698890.4):
            result = weather_shenzhen.to_display(sample)
        self.assertEqual(result['updated_at'], 1795698890)


if __name__ == '__main__':
    unittest.main()
