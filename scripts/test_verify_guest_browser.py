"""Failure cleanup checks with stubbed processes/fixtures; no database calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('guest_browser_verifier', Path(__file__).with_name('verify_guest_browser.py'))
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class GuestBrowserCleanupTests(unittest.TestCase):
    def test_timeout_terminates_kills_reaps_child_and_records_failure(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('browser', 180),
                                  subprocess.TimeoutExpired('browser', 10), 0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(verifier.subprocess, 'Popen', return_value=child):
                with self.assertRaises(subprocess.TimeoutExpired):
                    verifier.run_browser({}, output)
            self.assertFalse(json.loads((output / 'receipt.json').read_text())['passed'])
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in child.wait.call_args_list], [180, 10, 10])

    def test_preparation_failure_still_cleans_its_fixture(self):
        calls = []
        def fixture(_path, action):
            calls.append(action)
            if action == 'prepare':
                raise RuntimeError('simulated preparation failure')
        with tempfile.TemporaryDirectory() as directory, patch.object(verifier, 'fixture', side_effect=fixture):
            with self.assertRaisesRegex(RuntimeError, 'preparation'):
                verifier.verify(Path(directory))
            self.assertEqual(calls, ['prepare', 'cleanup'])
            self.assertTrue(json.loads((Path(directory) / 'cleanup.json').read_text())['apiStopped'])

    def test_socket_failure_after_invitation_preparation_still_cleans_fixture(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(verifier, 'fixture', side_effect=lambda _path, action: calls.append(action)), \
             patch.object(verifier.socket, 'socket', side_effect=OSError('simulated bind failure')):
            with self.assertRaisesRegex(OSError, 'bind failure'):
                verifier.verify(Path(directory))
        self.assertEqual(calls, ['prepare', 'cleanup'])


if __name__ == '__main__':
    unittest.main()
