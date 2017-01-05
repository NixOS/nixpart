import os
import sys
import argparse


def handle_nixos_config(path):
    fullpath = os.path.abspath(path)
    if not os.path.exists(fullpath):
        msg = "{} does not exist.".format(fullpath)
        raise argparse.ArgumentTypeError(msg)
    return fullpath


class MountAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if option_string is None:
            # This is the case whenever no -m/--mount option was given.
            setattr(namespace, self.dest, None)
        elif values == '':
            # Due to our preprocessing in parse_args(), we end up having an
            # empty string if the -m/--mount option resides in a single program
            # argument.
            setattr(namespace, self.dest, '/mnt')
        else:
            setattr(namespace, self.dest, values)


# This one is highly implementation-specific but not easily avoidable because
# argparse doesn't allow GNU style optional arguments like we have in
# -m/--mount.
class NixpartFormatter(argparse.HelpFormatter):
    def _format_actions_usage(self, actions, groups):
        # We simply postprocess _format_actions_usage() by replacing only the
        # -m argument's formatting.
        result = super()._format_actions_usage(actions, groups)
        return result.replace('-m [', '-m[')

    def _format_action_invocation(self, action):
        if isinstance(action, MountAction):
            # More or less handled the same way as in the original method, but
            # we get only the metavar instead and concatenate it with the
            # short/long option.
            default = self._get_default_metavar_for_optional(action)
            metavar = self._metavar_formatter(action, default)(1)[0]
            parts = []
            for option_string in action.option_strings:
                maybe_eq = '=' if option_string.startswith('--') else ''
                parts.append(option_string + '[' + maybe_eq + metavar + ']')
            return ', '.join(parts)
        else:
            return super()._format_action_invocation(action)


def parse_args(args=None):
    desc = "Declaratively create partitions and filesystems"
    parser = argparse.ArgumentParser(description=desc,
                                     formatter_class=NixpartFormatter)

    parser.add_argument(
        '-v', '--verbose', dest='verbosity', action='count', default=0,
        help="Print what's going on, use multiple times to increase verbosity"
    )

    parser.add_argument(
        '-n', '--dry-run', dest='dry_run', action='store_true',
        help="Don't do anything but print what would be done"
    )

    parser.add_argument(
        '-m', '--mount', dest='mount', action=MountAction,
        nargs='?', metavar='MOUNTPOINT',
        help="Don't create partitions/filesystems but only mount them under "
             "the given path or /mnt if absent."
    )

    parser.add_argument(
        '-J', '--json', dest='is_json', action='store_true',
        help="The provided NixOS configuration file is already in JSON format"
    )

    parser.add_argument(
        'nixos_config', type=handle_nixos_config,
        help="A NixOS configuration file"
    )

    if args is None:
        args = sys.argv[1:]

    # Preprocess arguments so that we have GNU-style options for the -m/--mount
    # flag.
    #
    # Unfortunately This is currently not directly possible with argparse and
    # would need a lot of monkey patching, see this Stack Overflow question:
    #
    # http://stackoverflow.com/q/40989413
    #
    # For nixpart however, we do not have positional arguments other than that,
    # so we can circumvent this by transforming the arguments into something
    # that argparse could handle.
    newargs = []
    for n, arg in enumerate(args):
        # We can safely ignore one-character arguments, because they're
        # certainly no valid flags. If it's a file name, we still don't need to
        # preprocess it anyway.
        if len(arg) < 2:
            newargs.append(arg)
            continue

        # No options after this arg, so let's append all the remaining args and
        # stop the loop.
        if arg == '--':
            newargs += args[n:]
            break

        # Single-dash option: Just need to look for a 'm' character in it and
        # consume the rest of the arg's characters.
        if arg[0] == '-' and arg[1] != '-':
            mpos = arg[1:].find('m')
            if mpos != -1:
                # First +1 because 'mpos' starts at the second character of
                # 'arg' and another +1 because we need to break after the 'm'.
                break_at = mpos + 2
                newargs.append(arg[:break_at])
                newargs.append(arg[break_at:])
                continue
        # Multi-dash option: This is simpler, because we only need to look
        # whether 'arg' is only the option name and we just append an empty
        # value after that.
        elif arg == '--mount':
            newargs.append(arg)
            newargs.append('')
            continue

        newargs.append(arg)

    return parser.parse_args(args=newargs)
