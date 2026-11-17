# SPDX-License-Identifier: AGPL-3.0-only
"""Player-owned identity and career-save backups; never sent to AWS."""
import csv
import ctypes
import io
import json
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath

from ui import DATA


def save_folder():
    documents = Path.home() / "Documents"
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
            documents = Path(buffer.value)
    return documents / "Criterion Games/Need For Speed(TM) Most Wanted/Save"


def game_closed():
    if os.name != "nt":
        return
    for name in ("NFS13.exe", "NFS13.online.exe"):
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + name, "/FO", "CSV", "/NH"],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        for row in csv.reader(io.StringIO(result.stdout.decode("utf-8", "replace"))):
            if row and row[0].lower() == name.lower():
                raise ValueError("Close the game first so its save files are consistent")


def backup_saves(destination):
    game_closed()
    root = save_folder()
    if not root.is_dir():
        raise ValueError("No local career save exists yet. Start the game and save once")
    files = [path for path in root.rglob("*") if path.is_file() and not path.is_symlink()]
    if not files:
        raise ValueError("The local save folder is empty")
    temporary = Path(destination).with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
    temporary.replace(destination)
    return str(destination)


def restore_saves(source):
    game_closed()
    with zipfile.ZipFile(source) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if not entries or len(entries) > 1000 or sum(i.file_size for i in entries) > 256 * 1024 * 1024:
            raise ValueError("Invalid or oversized career backup")
        names = set()
        data = {}
        for info in entries:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or ":" in info.filename or "\\" in info.filename
                    or len(path.parts) != 2 or not path.parts[0].isdigit()
                    or not path.name.endswith(".NFS13Save") or info.filename in names):
                raise ValueError("Backup contains an unexpected save path")
            names.add(info.filename)
            data[info.filename] = archive.read(info)
    root = save_folder()
    if root.exists() and any(root.rglob("*.NFS13Save")):
        folder = DATA / "Backups"; folder.mkdir(parents=True, exist_ok=True)
        backup_saves(folder / f"career-before-restore-{time.time_ns()}.zip")
    for name, content in data.items():
        target = root.joinpath(*PurePosixPath(name).parts)
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Save path leaves the save directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".restore")
        temporary.write_bytes(content)
        temporary.replace(target)
    return "Local career save restored; a previous save was backed up when present"


def export_identity(destination):
    content = json.loads((DATA / "identities.json").read_bytes())
    Path(destination).write_text(json.dumps({"format": "fairhaven-identity-1", "identities": content}, indent=2), encoding="utf-8")
    return str(destination)


def import_identity(source):
    data = json.loads(Path(source).read_bytes())
    values = data.get("identities")
    if data.get("format") != "fairhaven-identity-1" or not isinstance(values, dict) or not values:
        raise ValueError("Choose a Fairhaven identity backup")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", name) or not isinstance(secret, str)
           or not re.fullmatch(r"[a-f0-9]{64}", secret) for name, secret in values.items()):
        raise ValueError("Invalid identity backup")
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "identities.json"
    current = json.loads(path.read_bytes()) if path.exists() else {}
    if path.exists():
        (DATA / f"identities-before-import-{time.time_ns()}.json").write_bytes(path.read_bytes())
    current.update(values)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current), encoding="utf-8")
    temporary.replace(path)
    return "Player identity imported"


def prefer_gpu(executable):
    if os.name == "nt":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences") as key:
            try: current = winreg.QueryValueEx(key, str(executable))[0]
            except FileNotFoundError: current = ""
            tokens = [value for value in current.split(";") if value and not value.startswith("GpuPreference=")]
            winreg.SetValueEx(key, str(executable), 0, winreg.REG_SZ, ";".join(tokens + ["GpuPreference=2"]) + ";")
