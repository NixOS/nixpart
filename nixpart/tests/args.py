import io
import unittest
import tempfile

from unittest.mock import patch

from nixpart.args import parse_args


class ArgsTest(unittest.TestCase):
    def setUp(self):
        self.cfgfile = tempfile.NamedTemporaryFile()
        self.cfgfile.write(b"dummy")
        self.cfgfile.flush()
        self.cfg = self.cfgfile.name

    def tearDown(self):
        self.cfgfile.close()

    def test_short_mount_with_sysroot(self):
        result = parse_args(['-m/foo', self.cfg])
        self.assertIn('mount', result)
        self.assertEqual('/foo', result.mount)

    def test_short_mount_without_sysroot(self):
        result = parse_args(['-m', self.cfg])
        self.assertIn('mount', result)
        self.assertEqual('/mnt', result.mount)

    def test_long_mount_with_sysroot(self):
        result = parse_args(['--mount=/foo', self.cfg])
        self.assertIn('mount', result)
        self.assertEqual('/foo', result.mount)

    def test_long_mount_without_sysroot(self):
        result = parse_args(['--mount', self.cfg])
        self.assertIn('mount', result)
        self.assertEqual('/mnt', result.mount)

    def test_mount_defaults_to_none(self):
        result = parse_args([self.cfg])
        self.assertIn('mount', result)
        self.assertIsNone(result.mount)

    def test_help_formatting(self):
        with patch('sys.stdout', io.StringIO()) as stdout_io, \
             patch('sys.stderr', io.StringIO()) as stderr_io, \
             patch('sys.exit'):
            parse_args(['--help'])
            stdout_io.seek(0)
            stdout = stdout_io.read()
            stderr_io.seek(0)
            stderr = stderr_io.read()

        for expect in [
            "[-m[SYSROOT]]",
            "-m[SYSROOT], --mount[=SYSROOT]",
        ]:
            self.assertIn(expect, stdout)

        for expect in [
            "the following arguments are required: nixos_config",
            "[-m[SYSROOT]]",
        ]:
            self.assertIn(expect, stderr)
