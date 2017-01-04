import sys
import logging
import json
import subprocess

from nixpart.args import parse_args
from nixpart.storage import realize


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

    if args.is_json:
        json_fp = open(args.nixos_config, 'r')
    else:
        cmd = ['nix-build', '--no-out-link', '<nixpkgs/nixos>',
               '--arg', 'configuration', args.nixos_config,
               '-A', 'config.system.build.nixpart-spec']
        json_fp = open(subprocess.check_output(cmd).rstrip(), 'r')

    realize(json.load(json_fp))
