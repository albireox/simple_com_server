#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2021-04-30
# @Filename: server.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import html
import pathlib

from typing import TypeVar

import serial_asyncio
from sdsstools import get_logger


log = get_logger("simple-com")
log.start_file_logger("/home/lvm/simple-com.log")


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

    def __init__(
        self,
        com_path: str | pathlib.Path,
        port: int,
        timeout: float = 0.1,
        delimiter: str | None = None,
    ):

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
        self.delimiter = delimiter

        self._lock = asyncio.Lock()

        self.server: asyncio.AbstractServer = None

    async def start(self: T) -> T:
        """Starts the TCP server."""

        self.server = await asyncio.start_server(
            self._client_connected_cb,
            "0.0.0.0",
            self.port,
        )

        return self

    async def stop(self):
        """Closes the TCP server."""

        self.server.close()
        await self.server

    async def readall(self, reader, timeout=0.1) -> bytes:
        """Reads the buffer until it's empty."""

        if self.delimiter is not None and self.delimiter != "":
            try:
                return await reader.readuntil(html.escape(self.delimiter).encode())
            except asyncio.IncompleteReadError:
                log.error(
                    f"{self.port}: IncompleteReadError while "
                    "reading serial with delimiter."
                )
                return b""
            except BaseException as err:
                log.error(f"{self.port}: Unknown error while reading serial: {err}")
                return b""

        else:
            reply = b""
            while True:
                try:
                    reply += await asyncio.wait_for(reader.readexactly(1), timeout)
                except asyncio.TimeoutError:
                    return reply
                except asyncio.IncompleteReadError:
                    log.error(f"{self.port}: IncompleteReadError while reading serial.")
                    return b""
                except BaseException as err:
                    log.error(f"{self.port}: Unknown error while reading serial: {err}")
                    return b""

    async def send_to_serial(self, data: bytes, timeout=None) -> bytes:
        """Sends data to the serial device and waits for a reply."""

        options = self._extra_options.copy()
        wserial = None
        try:
            rserial, wserial = await serial_asyncio.open_serial_connection(
                url=self.com_path,
                **options,
            )
        except BaseException as err:
            log.error(f"{self.port}: Error while opening serial {self.com_path}: {err}")
            if wserial:
                self.close()
                await wserial.wait_closed()
                log.warning(f"{self.port}: Emergency close of {self.com_path}.")
            return b""

        log.info(f"{self.port}: Serial {self.com_path} open.")

        wserial.write(data)
        await wserial.drain()
        log.info(f"{self.port}: Serial {self.com_path}: sent {data}.")

        reply = b""
        try:
            reply = await self.readall(rserial, timeout or self.timeout)
            log.info(f"{self.port}: Serial {self.com_path}: received {reply}.")
        except BaseException as err:
            log.error(f"{self.port}: Unknown error in send_to_serial(): {err}")
        finally:
            wserial.close()
            await wserial.wait_closed()
            log.info(f"{self.port}: Serial {self.com_path} closed.")

        return reply

    async def _client_connected_cb(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Handles a connected client."""

        log.info(f"{self.port}: New connection.")
        while True:

            try:
                data = await reader.read(1024)
                if data == b"" or reader.at_eof():
                    log.info(f"{self.port}:At EOF. Closing.")
                    writer.close()
                    await writer.wait_closed()
                    return

                log.info(f"{self.port}: Received {data}.")

                async with self._lock:
                    try:
                        reply = await self.send_to_serial(data)
                        if reply != b"":
                            log.info(f"{self.port}: Sending {reply} to client.")
                            writer.write(reply)
                            await writer.drain()
                    except BaseException as err:
                        log.error(f"{self.port}: Error while sending to serial {err}.")
                        continue
            except BaseException as err:
                log.error(f"{self.port}: Error found: {err}")
                try:
                    writer.close()
                    await writer.wait_closed()
                except BaseException:
                    log.error(f"{self.port}: Failed closing writer during error.")
                    pass
                if self._lock.locked():
                    log.info(f"{self.port}: Releasing lock after error.")
                    self._lock.release()
                return
