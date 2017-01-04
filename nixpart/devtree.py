import blivet

from blivet.size import Size
from blivet.partitioning import do_partitioning


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

    def populate(self, expr):
        storagetree = {}

        for name, attrs in expr['storage']['disk'].items():
            disk = self._blivet.devicetree.get_device_by_name(name)
            storagetree['disk.' + name] = disk

        for name, attrs in expr['storage']['partition'].items():
            parents = [storagetree.get(attrs['targetDevice'])]

            for parent in parents:
                if parent.format.type is None:
                    self._blivet.initialize_disk(parent)

            part_attrs = {
                'name': name,
                'parents': [storagetree.get(attrs['targetDevice'])],
            }

            if attrs['size'] == "fill":
                part_attrs['grow'] = True
            else:
                part_attrs['size'] = expr2size(attrs['size'])

            part = self._blivet.new_partition(**part_attrs)
            self._blivet.create_device(part)
            storagetree['partition.' + name] = part

        for name, attrs in expr['storage']['btrfs'].items():
            parents = [storagetree.get(d) for d in attrs['devices']]

            for parent in parents:
                fmt = blivet.formats.get_format("btrfs", device=parent.path)
                self._blivet.format_device(parent, fmt)

            btrfs = self._blivet.new_btrfs(name=name, parents=parents,
                                           data_level=attrs['data'],
                                           metadata_level=attrs['metadata'])
            self._blivet.create_device(btrfs)
            storagetree['btrfs.' + name] = btrfs

        for mountpoint, attrs in expr['fileSystems'].items():
            if attrs['storage'].startswith('btrfs.'):
                continue
            target = storagetree.get(attrs['storage'])
            fmt = blivet.formats.get_format(attrs['fsType'],
                                            device=target.path)
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
