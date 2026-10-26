"""Exercise the actual CLI in a temporary repo using a stateful fake Docker."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).with_name('prepare-frontend-assets.py')


class AssetCaptureCleanup(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='myink-asset-capture-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'scripts').mkdir()
        shutil.copyfile(SOURCE, self.root / 'scripts' / SOURCE.name)
        self.fake = self.root / 'docker'
        self.fake.write_text('#!' + sys.executable + '''
import json, os, sys
from pathlib import Path
root=Path(__file__).parent
state=root/'container'
a=sys.argv[1:]
with (root/'calls').open('a') as log: log.write(json.dumps(a)+'\\n')
mode=os.environ['MYINK_CAPTURE_TEST_MODE']
if a[0]=='image': print('sha256:immutable-fixture')
elif a[0]=='create':
    if mode=='before_failure': raise SystemExit(70)
    state.write_text('created')
    if mode=='partial_failure': raise SystemExit(70)
    print('container-fixture')
elif a[0]=='cp': (Path(a[-1])/'previous.js').write_text('public old asset')
elif a[0]=='rm':
    if not state.exists():
        print('Error response from daemon: No such container: test', file=sys.stderr)
        raise SystemExit(1)
    if mode=='cleanup_failure':
        print('Error response from daemon: unavailable', file=sys.stderr)
        raise SystemExit(1)
    state.unlink()
else: raise SystemExit(71)
''')
        self.fake.chmod(0o755)

    def run_capture(self, mode):
        return subprocess.run([sys.executable, str(self.root / 'scripts' / SOURCE.name),
                               '--docker', str(self.fake), '--image', 'fixture'],
                              env={**os.environ, 'MYINK_CAPTURE_TEST_MODE': mode},
                              capture_output=True, text=True, timeout=10)

    def test_partial_creation_failure_still_reclaims_container(self):
        result = self.run_capture('partial_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'container').exists(), 'partial create leaked its container')
        self.assertIn('exit status 70', result.stderr)

    def test_failed_create_with_confirmed_absence_keeps_original_error(self):
        result = self.run_capture('before_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exit status 70', result.stderr)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertTrue(any(call[:3] == ['rm', '-f', '-v'] for call in calls))

    def test_success_copies_public_bytes_records_identity_and_cleans(self):
        result = self.run_capture('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['images'][0]['id'], 'sha256:immutable-fixture')
        self.assertEqual(receipt['files']['previous.js'], hashlib.sha256(b'public old asset').hexdigest())
        self.assertFalse((self.root / 'container').exists())

    def test_cleanup_error_cannot_report_success(self):
        result = self.run_capture('cleanup_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'container').exists())
        self.assertNotIn('retained_public_frontend_assets', result.stdout)


if __name__ == '__main__':
    unittest.main()
