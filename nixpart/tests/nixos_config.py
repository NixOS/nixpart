import unittest
import os
import shutil
import tempfile

from nixpart.main import config2json

SIMPLE_CONFIG = '''
{ lib, ... }: {
  storage = {
    disk.sda = {};
    partition.root.size = "fill";
    partition.root.targetDevice = "disk.sda";
  };

  fileSystems."/".storage = "partition.root";
}
'''


def has_nix_build():
    """
    Check whether nix-build is available.
    """
    return shutil.which('nix-build') is not None


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


@unittest.skipUnless(has_nixpkgs(), "no <nixpkgs> available")
@unittest.skipUnless(has_nix_build(), "no nix-build available")
class NixosConfigTest(unittest.TestCase):
    def test_simple_storage_config(self):
        with tempfile.NamedTemporaryFile(mode='w+') as cfg:
            cfg.write(SIMPLE_CONFIG)
            cfg.flush()
            expr = config2json(cfg.name)
            self.assertIn('storage', expr)
            storage = expr['storage']

            self.assertIn('disk', storage)
            self.assertIn('sda', storage['disk'])
            self.assertIn('match', storage['disk']['sda'])
            self.assertIn('name', storage['disk']['sda']['match'])
            self.assertEqual('sda', storage['disk']['sda']['match']['name'])

            self.assertIn('partition', storage)
            self.assertIn('root', storage['partition'])
            self.assertIn('targetDevice', storage['partition']['root'])
            targetdev = storage['partition']['root']['targetDevice']
            self.assertEqual('disk.sda', targetdev)

            self.assertIn('fileSystems', expr)
            self.assertIn('/', expr['fileSystems'])
            self.assertIn('storage', expr['fileSystems']['/'])
            storageptr = expr['fileSystems']['/']['storage']
            self.assertEqual('partition.root', storageptr)
