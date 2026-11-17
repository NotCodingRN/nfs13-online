# SPDX-License-Identifier: AGPL-3.0-only
import contextlib
import io
import ipaddress
import json
import re
import secrets
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, BooleanVar, ttk

from ui import DATA, ROOT, Window, tk
from sharing import load_preferences, preferences_path

def server_ip(value):
    address = ipaddress.IPv4Address(value.strip())
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError("Enter the server’s public or private IPv4 address.")
    return str(address)

def play(folder, name, address, progress, high_performance=True):
    from local_data import game_closed
    game_closed()
    address = server_ip(address)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", name):
        raise ValueError("Use 1–15 letters, numbers, hyphens or underscores for your display name.")
    exe = Path(folder) / "NFS13.exe"
    if not exe.is_file():
        raise ValueError("Choose the folder containing NFS13.exe.")
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://{address}:8080"
    def get(path):
        with http.open(base + path, timeout=8) as response:
            return json.loads(response.read(65536))
    manifest = get("/server_manifest")
    if manifest.get("serverActive") is not True:
        raise ValueError("The game server is offline. Check the server IP and your network connection.")
    if manifest.get("launcherIdentityVersion") != 2:
        raise ValueError("The server needs the current launcher identity update")
    progress("Preparing your game copy…")
    sys.path.insert(0, str(ROOT / "client"))
    import patch_nfs13
    out = exe.with_name("NFS13.online.exe")
    original = sys.argv
    log = io.StringIO()
    try:
        sys.argv = ["patch_nfs13", "--i-own-this-game", str(exe), "--patch", str(ROOT / "client/patches/nfs13_online.json")]
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            if patch_nfs13.main() or not out.exists():
                raise RuntimeError(log.getvalue()[-900:])
    finally:
        sys.argv = original
    names = (ROOT / "client/hosts.txt").read_text().split()
    def mapped(host):
        try:
            return {x[4][0] for x in socket.getaddrinfo(host, None, socket.AF_INET)} == {address}
        except OSError:
            return False
    if not all(mapped(host) for host in names):
        progress("Approve the Windows hosts-file update for this server.")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "install/add_hosts_windows.ps1"), address], check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        if not all(mapped(host) for host in names):
            raise RuntimeError("Windows still resolves a game service to a different IP. Check UAC approval and conflicting hosts entries.")
    DATA.mkdir(parents=True, exist_ok=True)
    identity_path = DATA / "identities.json"
    try:
        identities = json.loads(identity_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        identities = {}
    # A player's secret survives server address changes and follows their chosen name.
    previous_name = ""
    try:
        previous_name = json.loads((DATA / "player.json").read_text())[1].casefold()
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    credential = identities.setdefault(name.casefold(), identities.get(previous_name, secrets.token_hex(32)))
    temporary = identity_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(identities), encoding="utf-8")
    temporary.replace(identity_path)
    request = urllib.request.Request(base + "/launcher/login",
        data=json.dumps({"name": name, "credential": credential}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with http.open(request, timeout=10) as response:
        reply = json.loads(response.read(65536))
    if reply.get("status") != "ok":
        raise ValueError(reply.get("message", "The server could not set your name."))
    from identity_patch import personalize
    patched = personalize(out.read_bytes(), reply["ticket"])
    out.write_bytes(patched)
    (DATA / "player.json").write_text(json.dumps([folder, name, address]), encoding="utf8")
    preferences_path().write_text(json.dumps([folder, name, address]), encoding="utf-8")
    if high_performance:
        from local_data import prefer_gpu
        prefer_gpu(out.resolve())
    subprocess.Popen([str(out.resolve())], cwd=exe.parent)

def main():
    win = Window("Fairhaven • Player", "Join the chase")
    win.root.geometry("780x740")
    folder, name, address = load_preferences()
    game = win.field("Game folder", folder)
    def browse():
        selected = filedialog.askdirectory(title="Choose the folder containing NFS13.exe")
        if selected:
            game.set(selected)
    win.button("Browse…", browse, inline=True)
    nick = win.field("Display name", name)
    ip = win.field("Server IPv4", address)
    instructions = tk.StringVar(value="Enter the server IP your host sent you. Each player gets a separate identity, including players on the same Wi-Fi.")
    win.note(instructions)
    owned = BooleanVar()
    ttk.Checkbutton(win.form, text="I own this copy of NFS Most Wanted (2012).", variable=owned).grid(columnspan=3, sticky="w", pady=8)
    gpu = BooleanVar(value=True)
    ttk.Checkbutton(win.form, text="Prefer the high-performance GPU", variable=gpu).grid(columnspan=3, sticky="w", pady=3)
    def launch():
        if not owned.get():
            return messagebox.showinfo("Game ownership", "Confirm ownership before preparing the online copy.")
        args = game.get(), nick.get().strip(), ip.get()
        use_gpu = gpu.get()
        win.job("Checking the server…", lambda: play(*args, win.progress, use_gpu), lambda _: win.status.set("Game launched"))
    win.button("Play", launch, main=True)
    tools = ttk.LabelFrame(win.form, text="Your data", padding=10)
    tools.grid(column=0, columnspan=3, sticky="ew", pady=(15, 0))
    tools.columnconfigure(0, weight=1); tools.columnconfigure(1, weight=1)
    from local_data import backup_saves, restore_saves, export_identity, import_identity
    def backup_local():
        path=filedialog.asksaveasfilename(defaultextension=".zip",initialfile="MostWanted-Career.zip",filetypes=[("Career backup","*.zip")])
        if path: win.job("Backing up your career…",lambda:backup_saves(path),lambda result:win.status.set("Saved "+result))
    def restore_local():
        path=filedialog.askopenfilename(filetypes=[("Career backup","*.zip")])
        if path and messagebox.askyesno("Restore local career", "Restore this career backup? Close the game first. A safety backup is made before replacing existing saves."):
            win.job("Restoring your career…",lambda:restore_saves(path),lambda result:win.status.set(result))
    def export_key():
        path=filedialog.asksaveasfilename(defaultextension=".json",initialfile="Fairhaven-Identity.json",filetypes=[("Personal identity","*.json")])
        if path: win.job("Exporting identity…",lambda:export_identity(path),lambda result:win.status.set("Identity saved. Keep this file private"))
    def import_key():
        path=filedialog.askopenfilename(filetypes=[("Personal identity","*.json")])
        if path: win.job("Importing identity…",lambda:import_identity(path),lambda result:win.status.set(result))
    for index,(label,action) in enumerate((("Back up local career",backup_local),("Restore local career",restore_local),("Export player identity",export_key),("Import player identity",import_key))):
        widget=ttk.Button(tools,text=label,command=action)
        widget.grid(row=index//2,column=index%2,sticky="ew",padx=4,pady=4);win.buttons.append(widget)
    ttk.Label(tools,text="Career saves stay on this PC. Export your identity before changing PCs.",style="Muted.TLabel",wraplength=650).grid(row=2,column=0,columnspan=2,sticky="w",pady=8)
    win.root.mainloop()

if __name__ == "__main__":
    main()
