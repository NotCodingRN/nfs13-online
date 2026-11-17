# SPDX-License-Identifier: AGPL-3.0-only
"""Create a player package without host settings or credentials."""
import ipaddress
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from ui import ROOT, DATA


def defaults_file():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / "server.json"


def player_defaults(path=None):
    try:
        data = json.loads((path or defaults_file()).read_text(encoding="utf-8"))
        return str(ipaddress.IPv4Address(data["server_ip"]))
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def preferences_path(address=None):
    address = player_defaults() if address is None else address
    return DATA / (f"player-{address}.json" if address else "player.json")


def load_preferences():
    try:
        folder, name, address = json.loads((DATA / "player.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        folder = name = address = ""
    default = player_defaults()
    if default:
        try:
            return json.loads(preferences_path(default).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            address = default
    return folder, name, address


def player_pack(address, destination, template=None):
    address = str(ipaddress.IPv4Address(address))
    template = Path(template) if template else ROOT / "desktop/PlayerTemplate.zip"
    if not template.is_file():
        raise ValueError("Player template is missing. Install the current Host and player release")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as file:
        temporary = Path(file.name)
    try:
        with zipfile.ZipFile(template) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as output:
            names = source.namelist()
            if "NFS13Player.exe" not in names or not any(n.startswith("source/") for n in names):
                raise ValueError("Player template is incomplete")
            for entry in source.infolist():
                if entry.filename in ("NFS13Player.exe", "Start here.txt") or entry.filename.startswith("source/"):
                    output.writestr(entry, source.read(entry))
            output.writestr("server.json", json.dumps({"server_ip": address}, indent=2))
            output.writestr("Connect.txt", f"Extract this ZIP, then open NFS13Player.exe.\nServer: {address}\nChoose your game folder and your own display name, then Play.\nThe server IP can be edited in the launcher. No AWS account is needed.\n")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)
