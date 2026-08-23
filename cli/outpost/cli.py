"""
Outpost CLI Entry Point
"""

import click

from outpost.commands.auth import auth


@click.group()
@click.version_option(version="0.1.0", prog_name="outpost")
def cli():
    """Outpost — self-service environment provisioning from your terminal."""


cli.add_command(auth)


if __name__ == "__main__":
    cli()