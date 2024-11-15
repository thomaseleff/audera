""" Command-line utility """

import sys
import errno
import argparse
from audera.cli import commands


# Define audera CLI tool function(s)
def main():
    """
    usage: audera [-h] {run} ...

    CLI application for running `audera` services.

    options:
    -h, --help  show this help message and exit

    commands:
    The `audera` command options.

    {run}
        run       Runs an `audera` service.

    Execute `audera {command} --help` for more help.
    """

    # Setup CLI argument option(s)
    _ARG_PARSER = argparse.ArgumentParser(
        prog='audera',
        description='CLI application for running `audera` services.',
        epilog="Execute `audera {command} --help` for more help."
    )

    # Setup command argument option(s)
    _ARG_SUBPARSER = _ARG_PARSER.add_subparsers(
        title='commands',
        prog='audera',
        description='The `audera` command options.'
    )

    # Setup `run` command CLI argument option(s)
    _RUN_ARG_PARSER = _ARG_SUBPARSER.add_parser(
        name='run',
        help='Runs an `audera` service.',
        epilog="Execute `audera run --help` for help."
    )
    _RUN_ARG_PARSER.add_argument(
        'type_',
        help="The type of `audera` service.",
        type=str,
        choices=['server', 'client']
    )
    _RUN_ARG_PARSER.set_defaults(func=commands.run)

    # Parse arguments
    _ARGS = _ARG_PARSER.parse_args()
    _KWARGS = {
        key: vars(_ARGS)[key]
        for key in vars(_ARGS).keys()
        if key != 'func'
    }

    # Execute sub-command
    if _ARG_PARSER.parse_args():
        _ARGS.func(**_KWARGS)
    else:
        return errno.EINVAL


if __name__ == '__main__':
    sys.exit(main())
