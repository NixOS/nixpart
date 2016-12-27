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


class NixConfigTest(unittest.TestCase):
    def setUp(self):
        self.statedir = tempfile.mkdtemp()
        self.old_env = os.environ.copy()
        os.environ['NIX_STATE_DIR'] = self.statedir

    def tearDown(self):
        shutil.rmtree(self.statedir, ignore_errors=True)
        os.environ = self.old_env

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


@unittest.skipUnless(has_nixpkgs(), "no <nixpkgs> available")
class ParseFullNixConfigTest(NixConfigTest):
    pass


class ParseMockNixConfigTest(NixConfigTest):
    def setUp(self):
        super().setUp()
        self.dummy_nixpkgs_dir = tempfile.mkdtemp()
        eval_config_path = os.path.join(self.dummy_nixpkgs_dir,
                                        'nixos', 'lib', 'eval-config.nix')
        os.makedirs(os.path.dirname(eval_config_path))
        open(eval_config_path, 'wb').write(b'''
          { modules }: let
            module = builtins.head modules;
            isPlain = builtins.isAttrs module || builtins.isFunction module;
            attrs = { pkgs = {}; lib = {}; config = {}; options = {}; };
            callMod = mod: if builtins.isAttrs mod then mod else mod attrs;
            eval = callMod (if isPlain then module else import module);
            augmented = eval // {
              fileSystems = eval.fileSystems or {};
              swapDevices = eval.swapDevices or {};
              storage = eval.storage or {};
            };
          in { config = augmented; }
        ''')
        os.environ['NIX_PATH'] = "nixpkgs={}".format(self.dummy_nixpkgs_dir)

    def tearDown(self):
        shutil.rmtree(self.dummy_nixpkgs_dir)
        super().tearDown()

# Make sure the NixConfigTest class isn't directly run by the test runner.
del NixConfigTest
