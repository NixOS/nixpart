import os
import shutil
import unittest
import tempfile

from xml.etree import ElementTree

from nixpart import nix


def has_nix_instantiate():
    """
    Check whether nix-instantiate is available.
    """
    return shutil.which('nix-instantiate') is not None


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

    def assert_simple_example(self, result, has_unrelated=False):
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

        if has_unrelated:
            self.assertIn('networking', result)
            self.assertIn('hostName', result['networking'])
            self.assertEqual('unrelatedOption',
                             result['networking']['hostName'])
        else:
            self.assertNotIn('networking', result)

    def test_simple_example(self):
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
            self.assert_simple_example(result)


class XmlConfigTest(unittest.TestCase):
    # We later delete NixConfigTest from the attributes of the current module,
    # so we need to make sure we keep a reference as an unbound method.
    assert_simple_example = NixConfigTest.assert_simple_example

    def test_simple_example(self):
        xml = b'''
        <?xml version='1.0' encoding='utf-8'?>
        <expr><attrs>
          <attr name="fileSystems"><attrs>
            <attr name="/"><attrs>
              <attr name="storage"><string value="partition.root" /></attr>
            </attrs></attr>
          </attrs></attr>
          <attr name="storage"><attrs>
            <attr name="disk"><attrs>
              <attr name="sda"><attrs>
                <attr name="clear"><bool value="true" /></attr>
              </attrs></attr>
            </attrs></attr>
            <attr name="partition"><attrs>
              <attr name="root"><attrs>
                <attr name="targetDevice"><string value="disk.sda" /></attr>
              </attrs></attr>
            </attrs></attr>
          </attrs></attr>
          <attr name="networking"><attrs>
            <attr name="hostName"><string value="unrelatedOption" /></attr>
          </attrs></attr>
        </attrs></expr>
        '''
        result = nix.xml2python(xml)
        self.assert_simple_example(result, has_unrelated=True)

    def test_nix_decode_error(self):
        xml = "<?xml version='1.0' encoding='utf-8'?><invalid></invalid>"
        self.assertRaises(nix.NixDecodeError, nix.xml2python, xml)

    def test_not_well_formed(self):
        onlytextdecl = "<?xml version='1.0' encoding='utf-8'?>"
        self.assertRaises(ElementTree.ParseError, nix.xml2python, onlytextdecl)
        self.assertRaises(ElementTree.ParseError, nix.xml2python, "")


@unittest.skipUnless(has_nixpkgs(), "no <nixpkgs> available")
@unittest.skipUnless(has_nix_instantiate(), "no nix-instantiate available")
class ParseFullNixConfigTest(NixConfigTest):
    pass


@unittest.skipUnless(has_nix_instantiate(), "no nix-instantiate available")
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
