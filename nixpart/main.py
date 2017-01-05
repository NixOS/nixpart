import sys
import logging
import json
import subprocess

from nixpart.args import parse_args
from nixpart.devtree import DeviceTree


def build_config(cfgfile, verbose):
    """
    Build a NixOS configuration file and return storage configuration as a JSON
    filename. If 'verbose' is False, the "-Q" argument is passed to nix-build
    and stderr is redirected to /dev/null.
    """
    cmd = ['nix-build']
    if not verbose:
        cmd.append('-Q')
    cmd += ['--no-out-link', '<nixpkgs/nixos>',
            '--arg', 'configuration', cfgfile,
            '-A', 'config.system.build.nixpart-spec']
    kwargs = {} if verbose else {'stderr': subprocess.DEVNULL}
    return subprocess.check_output(cmd, **kwargs).rstrip()


def config2json(cfgfile, is_json=False, verbose=False):
    """
    Convert a given config file to JSON by either building it if it's a Nix
    expression file or if 'is_json' is True, simply by opening the JSON file.
    """
    if is_json:
        fp = open(cfgfile, 'r')
    else:
        fp = open(build_config(cfgfile, verbose), 'r')
    return json.load(fp)


def main():
    args = parse_args()

    if args.verbosity > 0:
        levels = [logging.INFO, logging.DEBUG]
        if args.verbosity > len(levels):
            level = levels[-1]
        else:
            level = levels[args.verbosity - 1]

        handler = logging.StreamHandler(sys.stderr)

        for name in ['blivet', 'program']:
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.addHandler(handler)

    expr = config2json(args.nixos_config,
                       is_json=args.is_json,
                       verbose=args.verbosity > 0)

    devtree = DeviceTree()
    devtree.populate(expr, for_mounting=args.mount is not None)

    if args.dry_run:
        print(devtree.devices)
    elif args.mount is not None:
        devtree.mount(args.mount)
    else:
        devtree.realize()
