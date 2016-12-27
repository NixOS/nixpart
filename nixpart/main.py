import sys
import logging

from nixpart.nix import xml2python, nix2python
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

    if args.is_xml:
        expr = xml2python(open(args.nixos_config, 'r').read())
    else:
        expr = nix2python(args.nixos_config)

    realize(expr)
