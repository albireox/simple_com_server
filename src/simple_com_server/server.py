#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2021-04-30
# @Filename: server.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import pathlib

from typing import TypeVar

import serial_asyncio


T = TypeVar("T", bound="TCPServer")


class TCPServer:
    """Creates a bidirectional bytestream between a TCP socket and a serial port.

    The connection is multiplexed to allow multiple connections. When a client sends
    a package to the serial port, the server will block other clients until the serial
    port has replied to the client or a timeout occurs.

    Parameters
    ----------
    com_path
        The path to the TTY device for the serial port. Connection options for pyserial
        can be passed as comma-separated values, for example
        ``com_path=/dev/ttyS0,baudrate=9600,parity=N``.
    port
        The port on localhost on which to serve the TCP socket.
    timeout
        How long to wait, in seconds, for a reply from the serial device before allowing
        new messages from other clients.

    """

    def __init__(self, com_path: str | pathlib.Path, port: int, timeout: float = 1):

        if "," not in com_path:
            self.com_path = com_path
            self._extra_options = {}
        else:
            self.com_path, *other = com_path.split(",")
            self._extra_options = {}
            for o in other:
                key, value = o.split("=")
                if value in ["baudrate", "baudrate", "stopbits"]:
                    value = int(value)
                self._extra_options[key] = value

        self.port = port
        self.timeout = timeout

        self._lock = asyncio.Lock()

        self.server: asyncio.AbstractServer = None

        self.rserial: asyncio.StreamReader = None
        self.wserial: asyncio.StreamWriter = None

    async def start(self: T, **kwargs) -> T:
        """Starts the connection to the serial device and the TCP server.

        Parameters
        ----------
        kwargs
            Arguments to be passed to ``pyserial`` when opening the serial connection.

        """

        options = self._extra_options.copy()
        options.update(kwargs)

        self.rserial, self.wserial = await serial_asyncio.open_serial_connection(
            url=self.com_path,
            **options,
        )

        self.server = await asyncio.start_server(
            self._client_connected_cb,
            "0.0.0.0",
            self.port,
        )

        return self

    async def stop(self):
        """Closes the TCP server."""

        self.server.close()
        self.wserial.close()

    async def readall(self, reader, timeout=0.1):
        """Reads the buffer until it's empty."""

        reply = b""
        while True:
            try:
                reply += await asyncio.wait_for(reader.read(1), timeout)
            except asyncio.TimeoutError:
                return reply

    async def _client_connected_cb(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Handles a connected client."""

        while True:

            try:
                if self.wserial.is_closing():
                    return
                data = await reader.read(1024)
                if reader.at_eof() or writer.is_closing():
                    return
            except ConnectionResetError:
                return

            async with self._lock:
                try:
                    self.wserial.write(data)
                    await self.wserial.drain()

                    reply = await asyncio.wait_for(
                        self.readall(self.rserial),
                        self.timeout,
                    )

                    writer.write(reply)
                    await writer.drain()
                except BaseException:
                    self.wserial.close()
                    return
