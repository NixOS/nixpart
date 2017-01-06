import unittest

from unittest.mock import patch, Mock, MagicMock

from blivet.size import Size
from blivet.devices import DiskDevice

from nixpart.devtree import DeviceTree


class DeviceTreeTest(unittest.TestCase):
    def setUp(self):
        def helper_class(self, info):
            def _run():
                device = DiskDevice(info.name, size=info.size,
                                    sysfs_path=info.sys_path)
                self._add_device(device)
                return device
            runner = Mock()
            runner.run = _run
            return runner
        self.devices = []
        patchers = [
            patch('blivet.formats.fs.FS.mountable', True),
            patch('blivet.formats.fs.FS.formattable', True),
            patch('blivet.formats.fs.FS.linux_native', True),
            patch('blivet.formats.fs.FS.supported', True),
            patch('blivet.formats.fs.FS.load_module', lambda s: None),
            patch('blivet.udev.get_devices', lambda: self.devices),
            patch('blivet.devices.storage.StorageDevice.update_sysfs_path'),
            patch('blivet.populator.PopulatorMixin._get_device_helper',
                  lambda s, i: lambda _d1, _d2: helper_class(s, i)),
            patch('blivet.platform.Platform.best_disklabel_type',
                  return_value='msdos'),
            patch('blivet.static_data.mpath_members.is_mpath_member',
                  return_value=False),
        ]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
            patcher.start()

    def add_device(self, devname, size):
        device = MagicMock()
        device.name = devname
        device.sys_name = devname
        device.size = size
        device.get = {
            'ID_FS_TYPE': "none",
            'ID_PART_TABLE_TYPE': "none"
        }.get
        self.devices.append(device)

    def test_sizes(self):
        self.add_device('test', Size("10 YB"))
        tree = DeviceTree()
        parts = {
            'test1': {'size': {'gib': 1}},
            'test2': {'size': {'mib': 1}},
            'test3': {'size': {'mb': 10, 'yb': 4}},
        }
        for part in parts.values():
            part['targetDevice'] = {'type': 'disk', 'name': 'test'}
        tree.populate({
            'storage': {
                'disk': {'test': {'match': {'allowIncomplete': False,
                                            'name': 'test'}}},
                'btrfs': {},
                'partition': parts
            },
            'fileSystems': {},
            'swapDevices': [],
        })
        result = {dev.path: dev for dev in tree.devices}
        self.assertEqual(Size("1 GiB"), result['/dev/test1'].size)
        self.assertEqual(Size("1 MiB"), result['/dev/test2'].size)
        self.assertEqual(Size("10 MB") + Size("4 YB"),
                         result['/dev/test3'].size)
