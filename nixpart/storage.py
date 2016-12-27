import blivet

from blivet.size import Size
from blivet.partitioning import do_partitioning


def realize(expr):
    b = blivet.Blivet()
    b.reset()

    storagetree = {}

    for name, attrs in expr['storage']['disk'].items():
        disk = b.devicetree.get_device_by_name(name)
        storagetree['disk.' + name] = disk

    for name, attrs in expr['storage']['partition'].items():
        parents = [storagetree.get(attrs['targetDevice'])]

        for parent in parents:
            if parent.format.type is None:
                b.initialize_disk(parent)

        part_attrs = {
            'name': name,
            'parents': [storagetree.get(attrs['targetDevice'])],
            'grow': attrs['grow'],
        }

        if attrs['size'] is not None:
            part_attrs['size'] = Size(attrs['size'])

        part = b.new_partition(**part_attrs)
        b.create_device(part)
        storagetree['partition.' + name] = part

    for name, attrs in expr['storage']['btrfs'].items():
        parents = [storagetree.get(d) for d in attrs['devices']]

        for parent in parents:
            fmt = blivet.formats.get_format("btrfs", device=parent.path)
            b.format_device(parent, fmt)

        btrfs = b.new_btrfs(name=name, parents=parents,
                            data_level=attrs['data'],
                            metadata_level=attrs['metadata'])
        b.create_device(btrfs)
        storagetree['btrfs.' + name] = btrfs

    for mountpoint, attrs in expr['fileSystems'].items():
        if attrs['storage'].startswith('btrfs.'):
            continue
        target = storagetree.get(attrs['storage'])
        fmt = blivet.formats.get_format(attrs['fsType'], device=target.path)
        label = attrs.get('label')
        if label is not None:
            fmt.label = label
        b.format_device(target, fmt)

    do_partitioning(b)
    b.do_it()
    print(b.devicetree.devices)
