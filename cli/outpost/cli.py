"""
Outpost CLI Entry Point
"""

import click

from outpost.commands.audit import audit
from outpost.commands.auth import auth
from outpost.commands.env import env
from outpost.commands.teams import teams


@click.group()
@click.version_option(version="0.1.0", prog_name="outpost")
def cli():
    """Outpost - self-service environment provisioning from your terminal."""


cli.add_command(auth)
cli.add_command(env)
cli.add_command(audit)
cli.add_command(teams)


if __name__ == "__main__":
    cli()