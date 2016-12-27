import os
import shutil
import unittest
import tempfile

from nixpart import nix


def has_nixpkgs():
    """
    Check whether <nixpkgs> is available in NIX_PATH
    """
    nix_path = os.environ.get('NIX_PATH')
    if nix_path is None:
        return False
    for path in nix_path.split(':'):
        if path.startswith('nixpkgs='):
            return True
        if os.path.exists(path) and \
           os.path.exists(os.path.join(path, 'nixpkgs')):
            return True
    return False


class ParseNixConfigTest(unittest.TestCase):
    def setUp(self):
        self.statedir = tempfile.mkdtemp()
        self.old_env = os.environ.copy()
        os.environ['NIX_STATE_DIR'] = self.statedir

    def tearDown(self):
        shutil.rmtree(self.statedir, ignore_errors=True)
        os.environ = self.old_env

    @unittest.skipUnless(has_nixpkgs(), "no <nixpkgs> available")
    def test_full_nixpkgs(self):
        simple_cfg = b'''
        {
          storage.disk.sda.clear = true;
          storage.partition.root.targetDevice = "disk.sda";
          fileSystems."/".storage = "partition.root";
          networking.hostName = "unrelatedOption";
        }
        '''

        with tempfile.NamedTemporaryFile() as cfg:
            cfg.write(simple_cfg)
            cfg.flush()
            result = nix.nix2python(cfg.name)
            self.assertIn('storage', result)
            storage = result['storage']

            self.assertIn('disk', storage)
            self.assertIn('sda', storage['disk'])
            self.assertIn('clear', storage['disk']['sda'])
            self.assertEqual(True, storage['disk']['sda']['clear'])

            self.assertIn('partition', storage)
            self.assertIn('root', storage['partition'])
            self.assertIn('targetDevice', storage['partition']['root'])
            self.assertEqual('disk.sda',
                             storage['partition']['root']['targetDevice'])

            self.assertIn('fileSystems', result)
            self.assertIn('/', result['fileSystems'])
            self.assertIn('storage', result['fileSystems']['/'])
            self.assertEqual('partition.root',
                             result['fileSystems']['/']['storage'])

            self.assertNotIn('networking', result)
