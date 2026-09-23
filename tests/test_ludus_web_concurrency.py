import importlib.util
import pathlib
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).parents[1] / 'src'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load('backend', 'ludus-backend.py')
W = load('web', 'ludus-web.py')


class SharedExclusiveLockTest(unittest.TestCase):
    def test_reads_overlap_and_writes_run_alone(self):
        lock, active, peak, writes = B.SharedExclusiveLock(), [0], [0], []
        guard = threading.Lock()

        def read():
            with lock.shared():
                with guard:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(0.05)
                with guard: active[0] -= 1

        def write():
            with lock.exclusive():
                with guard: writes.append(active[0])
                time.sleep(0.02)

        threads = [threading.Thread(target=read) for _ in range(4)] + [threading.Thread(target=write)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertGreater(peak[0], 1)
        self.assertEqual(writes, [0])

    def test_only_listed_operations_are_shared(self):
        self.assertIn('games.list', B.SHARED)
        self.assertIn('doctor.json', B.SHARED)
        self.assertNotIn('launch_options.save', B.SHARED)
        self.assertNotIn('repair', B.SHARED)


class PamCheckTest(unittest.TestCase):
    def setUp(self):
        for table in (W.PAM_FAILURES, W.PAM_SUCCESSES, W.PAM_IN_FLIGHT): table.clear()

    def test_parallel_requests_share_one_pam_check(self):
        calls, started = [], threading.Event()

        def backend(operation, argument):
            calls.append(operation)
            started.set()
            time.sleep(0.1)
            return {'ok': True}

        results = []
        with mock.patch.object(W, 'call', side_effect=backend):
            threads = [threading.Thread(target=lambda: results.append(
                W.pam_check('10.0.0.2', 'Basic x', 'admin', 'secret'))) for _ in range(5)]
            threads[0].start(); started.wait(1)
            for thread in threads[1:]: thread.start()
            for thread in threads: thread.join(2)
        self.assertEqual(calls, ['webui.pam_auth'])
        self.assertEqual(results, [True] * 5)
        self.assertTrue(W.recent_pam_success('10.0.0.2', 'Basic x'))

    def test_remembered_sign_in_expires_after_idle_period(self):
        with mock.patch.object(W.time, 'monotonic', return_value=1000):
            W.remember_pam_success('10.0.0.2', 'Basic x')
        with mock.patch.object(W.time, 'monotonic', return_value=1000 + W.PAM_SUCCESS_TTL - 1):
            self.assertTrue(W.recent_pam_success('10.0.0.2', 'Basic x'))
        # The previous request renewed the idle window.
        with mock.patch.object(W.time, 'monotonic', return_value=1000 + 2 * W.PAM_SUCCESS_TTL - 2):
            self.assertTrue(W.recent_pam_success('10.0.0.2', 'Basic x'))
        with mock.patch.object(W.time, 'monotonic', return_value=1000 + 4 * W.PAM_SUCCESS_TTL):
            self.assertFalse(W.recent_pam_success('10.0.0.2', 'Basic x'))


if __name__ == '__main__': unittest.main()
