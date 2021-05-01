#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2021-04-30
# @Filename: __main__.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

import asyncio

import click
from sdsstools.daemonizer import DaemonGroup, cli_coro

from simple_com_server.server import TCPServer


@click.group(cls=DaemonGroup, prog="com-server")
@click.option(
    "--device",
    multiple=True,
    type=str,
    help="Path to the serial device. Can be called multiple times for several devices.",
)
@click.option(
    "--port",
    multiple=True,
    type=int,
    help="Port on which to serve. Can be called multiple times for several devices.",
)
@click.option(
    "--timeout",
    type=float,
    default=1.0,
    help="Time to wait for a reply from the serial device.",
)
@cli_coro()
@click.pass_context
async def com_server(ctx, device, port, timeout):
    """Start a TCP-to-COM server."""

    # Do not require parameters to stop the daemon.
    if ctx.command.name in ["stop", "status"]:
        return

    if len(port) == 0 or len(device) == 0:
        raise click.UsageError("device and port are required options.", ctx)

    assert len(device) == len(port), "Number of devices must match number of ports."
    assert len(set(port)) == len(port), "Ports must be unique"

    servers = await asyncio.gather(
        *[
            TCPServer(
                str(device[ii]),
                port[ii],
                timeout=timeout,
            ).start()
            for ii in range(len(port))
        ]
    )

    await servers[0].server.serve_forever()
