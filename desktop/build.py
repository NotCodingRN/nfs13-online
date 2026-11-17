"""Build portable Windows apps and the combined setup.exe installer."""
# SPDX-License-Identifier: AGPL-3.0-only
import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_files():
    result = [ROOT / name for name in ("LICENSE", "AUTHORS", "DISCLAIMER.md", "README.md")]
    for folder in ("desktop", "client", "server", "install"):
        result.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                      and (p.suffix in (".py", ".txt", ".md", ".sh", ".ps1", ".c", ".h", ".def", ".in", ".iss", ".hex")
                           or p.name in ("Dockerfile", "Makefile")
                           or p.relative_to(ROOT).as_posix() in ("client/patches/nfs13_online.json", "server/friends.json")))
    return sorted(set(result))


def icon(path):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (256, 256), "#101316")
    draw = ImageDraw.Draw(image)
    draw.polygon([(148,0),(256,0),(108,256),(0,256)], fill="#d81920")
    draw.polygon([(58,55),(87,55),(163,201),(134,201)], fill="white")
    draw.polygon([(58,55),(90,55),(55,201),(23,201)], fill="white")
    draw.polygon([(172,55),(204,55),(169,201),(137,201)], fill="white")
    image.save(path, format="ICO", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])


def build(role, payload, work):
    player = role == "Player"
    name = "NFS13Player" if player else "NFS13ServerControl"
    files = (["client/patches/nfs13_online.json", "client/hosts.txt", "install/add_hosts_windows.ps1"] if player else
             ["server/server.py", "server/admin_api.py", "server/friends.json", "server/frontend/Dockerfile",
              "server/frontend/stunnel.conf.in", "client/hosts.txt", "install/install_server.sh", "desktop/provision.sh"])
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--noupx", "--name", name,
            "--icon", str(payload / "Fairhaven.ico"), "--distpath", str(payload), "--workpath", str(work / "build"), "--specpath", str(work)]
    if player:
        args += ["--paths", str(ROOT / "client"), "--hidden-import", "patch_nfs13", "--hidden-import", "identity_patch"]
    for file in files:
        args += ["--add-data", str(ROOT / file) + ";" + str(Path(file).parent)]
    if not player:
        args += ["--add-data", str(payload / "PlayerTemplate.zip") + ";desktop"]
    subprocess.run(args + [str(ROOT / "desktop" / (role.lower() + ".py"))], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("roles", nargs="*", choices=["Host", "Player"], default=["Host", "Player"])
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--aws-msi", type=Path)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    payload = output.parent / "work" / "installer-payload"
    payload.mkdir(parents=True, exist_ok=True)
    icon(payload / "Fairhaven.ico")
    for source in source_files():
        target = payload / "source" / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (payload / "Start here.txt").write_bytes((ROOT / "desktop/Suite.txt").read_bytes())
    with tempfile.TemporaryDirectory() as temp:
        roles = ["Player", "Host"] if "Host" in args.roles else ["Player"]
        for role in roles:
            build(role, payload, Path(temp))
            name = "NFS13Player" if role == "Player" else "NFS13ServerControl"
            with zipfile.ZipFile(output / (name + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(payload / (name + ".exe"), name + ".exe")
                archive.write(ROOT / "desktop" / (role + ".txt"), "Start here.txt")
                for source in source_files(): archive.write(source, "source/" + source.relative_to(ROOT).as_posix())
            if role == "Player":
                (payload / "PlayerTemplate.zip").write_bytes((output / "NFS13Player.zip").read_bytes())
    if args.setup:
        if not args.compiler or not args.aws_msi or not args.compiler.is_file() or not args.aws_msi.is_file():
            raise ValueError("Setup requires --compiler ISCC.exe and --aws-msi AWSCLIV2.msi")
        subprocess.run([str(args.compiler.resolve()), "/DPayload=" + str(payload), "/DOutput=" + str(output),
                        "/DAwsMsi=" + str(args.aws_msi.resolve()), str(ROOT / "desktop/Fairhaven.iss")], check=True)


if __name__ == "__main__": main()
