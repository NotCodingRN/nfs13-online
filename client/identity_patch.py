"""Carry the launcher ticket through retail SilentLogin and Autolog."""
# SPDX-License-Identifier: AGPL-3.0-only
import re
import struct


def personalize(data: bytes, ticket: str) -> bytes:
    if not re.fullmatch(r"NF[0-9a-f]{24}", ticket):
        raise ValueError("Invalid server login ticket")
    out = bytearray(data)
    site, session = 0x8a35cb, 0xb81f60
    # Retail SilentLogin copies a C string from eax into request.AUTH at 0x00ca35d5.
    # Replace its old empty-string address with the existing mapped Autolog buffer.
    if out[site:site + 5] != bytes.fromhex("0590000000"):
        raise ValueError("Ticket login is unsupported on this game build; no changes were written")
    if out[session:session + 27] != b"LOCAL-ALEX-AUTOLOG-SESSION\0":
        raise ValueError("The upstream Autolog session patch is missing")
    out[site:site + 5] = b"\xb8" + struct.pack("<I", 0x00f81f60)
    out[session:session + 27] = ticket.encode("ascii") + b"\0"
    return bytes(out)
