import os
import subprocess
import blivet

from blivet.size import Size
from blivet.partitioning import do_partitioning


class DeviceTreeError(Exception):
    pass


def expr2size(expr):
    """
    Convert a NixOS device size type to a blivet.size value.
    """
    sizes = {s.lower(): s for s in [
        "B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB",
        "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB",
    ]}

    size_acc = Size(0)
    for unit, sizeval in expr.items():
        size_acc += Size(str(sizeval) + " " + sizes[unit])
    return size_acc


class DeviceTree(object):
    def __init__(self):
        self._blivet = blivet.Blivet()
        self._blivet.reset()

    def get_device_by_script(self, devname):
        """
        Returns a fuction that executes a script with 'devname' as its first
        argument and returns the first line indicating a path as a blivet
        device.
        """
        def _find_dev(script, incomplete=False):
            matches = subprocess.check_output([script, devname]).splitlines()
            if len(matches) > 0:
                first = matches[0].decode('utf-8')
                return self._blivet.devicetree.get_device_by_path(
                    os.path.realpath(first),
                    incomplete=incomplete
                )
            else:
                return None
        return _find_dev

    def get_device_by_physical_pos(self, pos, incomplete=False):
        """
        Match physical disks based on a position in the order of enumeration
        from the kernel. Note that virtual devices such as /dev/loop* are
        excluded from this.
        """
        for device in self._blivet.devicetree._devices:
            is_incomplete = not getattr(device, 'complete', True)
            if not incomplete and is_incomplete:
                continue
            if device.type != "disk":
                continue
            pos -= 1
            if pos == 0:
                return device
        return None

    def get_device_by_id(self, devid, incomplete=False):
        """
        Get a device based on it's ID in /dev/disk/by-id.

        Note that this is different from blivet's get_device_by_id() because
        blivet's function searches based on a blivet-specific device id as an
        integer rather than in /dev/disk/by-id.
        """
        path = os.path.realpath(os.path.join("/dev/disk/by-id", devid))
        return self._blivet.devicetree.get_device_by_path(
            path, incomplete=incomplete
        )

    def match_device(self, devname, expr):
        """
        Match a device 'devname' based on the NixOS storage.disk.*.match
        configuration specified by 'expr'.

        The return value is a blivet device or None if no device has been
        found.
        """
        matchers = {
            'id': self.get_device_by_id,
            'label': self._blivet.devicetree.get_device_by_label,
            'name': self._blivet.devicetree.get_device_by_name,
            'path': self._blivet.devicetree.get_device_by_path,
            'sysfsPath': self._blivet.devicetree.get_device_by_sysfs_path,
            'uuid': self._blivet.devicetree.get_device_by_uuid,
            'script': self.get_device_by_script(devname),
            'physicalPos': self.get_device_by_physical_pos,
        }
        match_fun = matchers['name']
        match_on = devname
        for name, fun in matchers.items():
            if expr.get(name) is None:
                continue
            match_fun = fun
            match_on = expr[name]
            break
        return match_fun(match_on, incomplete=expr['allowIncomplete'])

    def devspec2tuple(self, devspec):
        """
        Take device specification from a Nix expression (which is a dict) and
        return it as a tuple so it's hashable.
        """
        return (devspec['type'], devspec['name'])

    def populate(self, expr, for_mounting=False):
        """
        Feed the blivet device tree with the various options from the Nix
        expression in 'expr'.
        """
        storagetree = {}

        if not for_mounting:
            for name, attrs in expr['storage']['disk'].items():
                disk = self.match_device(name, attrs['match'])
                if disk is None:
                    msg = "Could find a device for disk {}.".format(name)
                    raise DeviceTreeError(msg)
                storagetree[('disk', name)] = disk

            for name, attrs in expr['storage']['partition'].items():
                parent_spec = self.devspec2tuple(attrs['targetDevice'])
                parent = storagetree.get(parent_spec)
                if parent is None and not for_mounting:
                    msg = "Couldn't find a device specification for {}."
                    raise DeviceTreeError(msg.format('.'.join(parent_spec)))

                if parent.format.type is None:
                    self._blivet.initialize_disk(parent)

                part_attrs = {'name': name, 'parents': [parent]}

                if attrs['size'] == "fill":
                    part_attrs['grow'] = True
                else:
                    part_attrs['size'] = expr2size(attrs['size'])

                part = self._blivet.new_partition(**part_attrs)
                self._blivet.create_device(part)
                storagetree[('partition', name)] = part

            for name, attrs in expr['storage']['btrfs'].items():
                parents = [storagetree.get(self.devspec2tuple(devspec))
                           for devspec in attrs['devices']]

                for parent in parents:
                    fmt = blivet.formats.get_format(
                        "btrfs", device=parent.path
                    )
                    self._blivet.format_device(parent, fmt)

                btrfs = self._blivet.new_btrfs(
                    name=name, parents=parents, data_level=attrs['data'],
                    metadata_level=attrs['metadata']
                )
                self._blivet.create_device(btrfs)
                storagetree[('btrfs', name)] = btrfs

        for mountpoint, attrs in expr['fileSystems'].items():
            uuid = attrs['storage']['uuid']
            if for_mounting:
                device = self._blivet.devicetree.get_device_by_uuid(uuid)
                if device is not None:
                    device.format.mountpoint = mountpoint
                continue

            if attrs['storage']['type'] == 'btrfs':
                continue
            target = storagetree.get(self.devspec2tuple(attrs['storage']))
            fmt = blivet.formats.get_format(attrs['fsType'],
                                            device=target.path,
                                            uuid=uuid)
            label = attrs.get('label')
            if label is not None:
                fmt.label = label
            self._blivet.format_device(target, fmt)

    @property
    def devices(self):
        return self._blivet.devicetree.devices

    def realize(self):
        do_partitioning(self._blivet)
        self._blivet.do_it()

    def mount(self, sysroot):
        blivet.flags.installer_mode = True
        self._blivet.fsset.mount_filesystems(root_path=sysroot)
