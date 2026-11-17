# SPDX-License-Identifier: AGPL-3.0-only
import datetime
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cloud import Cloud, run, aws_executable
from ui import DATA, ROOT, Window, tk
from admin_layout import Page, ButtonRow, fit_window, scroll_table, wrap_labels
from sharing import player_pack


def main():
    win = Window("Fairhaven • Server control", "Server control")
    fit_window(win.root)
    ttk.Style(win.root).map("TButton", foreground=[("disabled", "#adb8c3")])
    win.form.bind("<Configure>", lambda _: wrap_labels(win.form))
    try:
        profiles = run(["aws", "configure", "list-profiles"]).decode().splitlines()
    except (OSError, ValueError, RuntimeError):
        profiles = []
    try:
        default = json.loads((DATA / "host.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        default = {}
    profile = tk.StringVar(value=default.get("profile", profiles[0] if profiles else ""))
    region = tk.StringVar(value=default.get("region", "us-east-1"))
    instance = tk.StringVar(value=default.get("instance", "fairhaven-racing"))
    key = tk.StringVar(value=default.get("key", ""))
    connection = ttk.Frame(win.form)
    connection.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 14))
    connection.columnconfigure(1, weight=1)
    connection.columnconfigure(3, weight=1)

    connection_fields = []
    def field(parent, label, var, row, col=0, values=None, width=24):
        caption = ttk.Label(parent, text=label, style="Muted.TLabel")
        caption.grid(row=row, column=col, sticky="w", padx=(0, 10), pady=4)
        widget = (ttk.Entry(parent, textvariable=var, width=width) if values is None else
                  ttk.Combobox(parent, textvariable=var, values=values, width=width))
        widget.grid(row=row, column=col+1, sticky="ew", padx=(0, 16), pady=4)
        win.inputs.append(widget)
        if parent is connection:
            connection_fields.append((row, col, caption, widget))
        return widget
    profile_box = field(connection, "AWS profile", profile, 0, values=profiles)
    region_box = field(connection, "Region", region, 0, 2, ["us-east-1", "eu-west-1", "eu-central-1", "eu-west-2", "ap-south-1", "ap-southeast-1"])
    instance_box = field(connection, "Server name", instance, 1)
    field(connection, "SSH key", key, 1, 2)

    def button(parent, text, action, primary=False):
        widget = ttk.Button(parent, text=text, command=action, style="Play.TButton" if primary else "TButton")
        parent.add(widget)
        win.buttons.append(widget)
        return widget
    def browse_key():
        value = filedialog.askopenfilename(title="Choose the server SSH key", filetypes=[("SSH key", "*.pem"), ("All files", "*.*")])
        if value: key.set(value)
    browse_button = ttk.Button(connection, text="Browse key", command=browse_key)
    browse_button.grid(row=2, column=3, sticky="e", padx=16)
    win.buttons.append(browse_button)
    connection_layout = {"narrow": None}
    def arrange_connection(event):
        narrow = event.width < 800
        if narrow == connection_layout["narrow"]:
            return
        connection_layout["narrow"] = narrow
        connection.columnconfigure(3, weight=0 if narrow else 1)
        for index, (row, col, caption, widget) in enumerate(connection_fields):
            caption.grid_configure(row=index if narrow else row, column=0 if narrow else col)
            widget.grid_configure(row=index if narrow else row, column=1 if narrow else col+1)
        browse_button.grid_configure(row=4 if narrow else 2, column=1 if narrow else 3)
    connection.bind("<Configure>", arrange_connection)

    tabs = ttk.Notebook(win.form)
    tabs.grid(row=2, column=0, columnspan=3, sticky="nsew")
    win.form.rowconfigure(2, weight=1)
    pages = {}
    for label in ("Server", "Players", "Backups", "Host new server", "Help"):
        frame = Page(tabs)
        tabs.add(frame, text=label)
        pages[label] = frame.body

    def client():
        settings = {"profile": profile.get().strip(), "region": region.get().strip(),
                    "instance": instance.get().strip(), "key": key.get().strip()}
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "host.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return Cloud(settings["profile"], settings["region"], settings["instance"], settings["key"])
    def operation(label, action, done=None):
        try: c = client()
        except Exception as exc: return messagebox.showerror("Server control", str(exc))
        win.job(label, lambda: action(c), done or (lambda value: win.status.set(str(value))))
    def confirm(label, text, action):
        if messagebox.askyesno(label, text): action()

    server_page = pages["Server"]
    state = tk.StringVar(value="Connect to your race server")
    address = tk.StringVar(value="Refresh to load the public IP, players and current lobbies.")
    ttk.Label(server_page, textvariable=state, style="Title.TLabel").pack(anchor="w")
    ttk.Label(server_page, textvariable=address, style="Stat.TLabel").pack(anchor="w", pady=(8, 10))
    detail = tk.Text(server_page, bg="#1b2128", fg="#d9e1e9", relief="flat", height=9,
                     font=("Consolas", 10), wrap="word", padx=12, pady=10, state="disabled")
    detail.pack(fill="both", expand=True, pady=(0, 8))
    server_ip = {"value": ""}
    def show_text(text):
        detail.configure(state="normal"); detail.delete("1.0", "end"); detail.insert("1.0", str(text)); detail.configure(state="disabled")
    def show_status(data):
        state.set(f"{instance.get()}   /   {data['state']}   /   service {data['service']}")
        server_ip["value"] = data.get("ip", "")
        address.set(server_ip["value"] or "No public IP")
        rows = [f"{len(data.get('players', []))} players online    •    {len(data.get('games', []))} active lobbies", ""]
        rows += [f"{p['name']}     {p.get('sp',0):,} SP     Persona {p['persona_id']}" for p in data.get("players", [])]
        rows += [f"Lobby {g['game_id']}: {', '.join(g['players'])} / {g['capacity']} slots" for g in data.get("games", [])]
        if data.get("detail"): rows += ["", "Management connection needs attention:", data["detail"]]
        rows += ["", "Updated " + datetime.datetime.now().strftime("%H:%M:%S")]
        show_text("\n".join(rows))
        win.status.set("Server status updated")
    bar = ButtonRow(server_page); bar.pack(fill="x")
    button(bar, "Refresh status", lambda: operation("Checking server…", lambda c: c.status(), show_status), True)
    button(bar, "Recent logs", lambda: operation("Reading log…", lambda c: c.logs(), show_text))
    def copy_connection():
        ip = server_ip["value"]
        if not ip: return messagebox.showinfo("Player instructions", "Refresh the server first")
        win.root.clipboard_clear(); win.root.clipboard_append(f"NFS Most Wanted 2012 private server: {ip}\nOpen Fairhaven Player, choose your game folder and a unique name, enter {ip}, then Play.")
        win.status.set("Player connection instructions copied")
    button(bar, "Copy player invite", copy_connection)
    pack_path = tk.StringVar(value="Player ZIP: host a server or refresh status, then export a launcher for friends.")
    def pack_destination(ip):
        return DATA / "PlayerPacks" / f"NFS13-Players-{ip}.zip"
    def pack_ready(path):
        pack_path.set("Player ZIP: " + str(path))
        win.status.set("Player ZIP ready to share. It includes the server IP, which players can change.")
    def export_pack():
        ip = server_ip["value"]
        if not ip: return messagebox.showinfo("Player ZIP", "Refresh server status first to load its IP")
        win.job("Creating the player ZIP…", lambda:player_pack(ip, pack_destination(ip)), pack_ready)
    button(bar, "Export player ZIP", export_pack)
    button(bar, "Open player ZIP folder", lambda:(DATA.joinpath("PlayerPacks").mkdir(parents=True,exist_ok=True),os.startfile(DATA/"PlayerPacks")))
    actions = ButtonRow(server_page); actions.pack(fill="x")
    power = tk.StringVar(value="Restart game service")
    choices = {"Start game service": "service-start", "Restart game service": "restart-service", "Stop game service": "service-stop",
               "Start AWS instance": "start", "Reboot AWS instance": "reboot", "Stop AWS instance": "stop"}
    box = ttk.Combobox(actions, textvariable=power, values=list(choices), state="readonly", width=25); actions.add(box); win.inputs.append(box)
    button(actions, "Apply", lambda: confirm("Server action", power.get() + "? Connected players may be disconnected.",
           lambda: operation("Applying server action…", lambda c: c.control(choices[power.get()]))))
    button(actions, "Update backend", lambda: confirm("Update backend", "Save a safety backup, install the packaged backend and restart the service?",
           lambda: operation("Backing up and updating…", lambda c: c.publish())))
    auto = tk.BooleanVar(value=False)
    ttk.Checkbutton(server_page, text="Refresh status every 30 seconds", variable=auto).pack(anchor="w", pady=5)
    ttk.Label(server_page,textvariable=pack_path,wraplength=850,style="Muted.TLabel").pack(anchor="w",pady=5)
    def tick():
        if auto.get() and not win.busy and tabs.select() == str(server_page.page):
            operation("Refreshing server…", lambda c: c.status(), show_status)
        win.root.after(30000, tick)
    win.root.after(30000, tick)

    players_page = pages["Players"]
    ttk.Label(players_page, text="Drivers & server progression", style="Title.TLabel").pack(anchor="w")
    ttk.Label(players_page, text="Online XP, identities and license plates are server data. Career saves and car ownership stay on each PC.", style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=8)
    table_frame = ttk.Frame(players_page)
    table_frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(table_frame, columns=("id", "name", "sp", "online", "car"), show="headings", height=4, selectmode="browse")
    for column, title, width in (("id","Persona",100),("name","Driver",170),("sp","Online SP",120),("online","Status",100),("car","Last vehicle ID",150)):
        tree.heading(column,text=title); tree.column(column,width=width,minwidth=width,stretch=False)
    scroll_table(tree, table_frame)
    records = {}
    def populate(rows):
        tree.delete(*tree.get_children()); records.clear()
        for record in rows:
            pid=record["persona_id"]; records[pid]=record; stats=record["stats"]
            tree.insert("", "end", iid=str(pid), values=(pid,record["name"],f"{stats.get('xp',0):,}" if record["xp_known"] else "Not reported",
                        "Disabled" if stats.get("disabled") else "Online" if record["online"] else "Offline", stats.get("vehicle_id","Not reported")))
        win.status.set(f"Loaded {len(rows)} registered players")
    def selected():
        items=tree.selection()
        if not items: raise ValueError("Select a player first")
        return records[int(items[0])]
    edit = ttk.Frame(players_page); edit.pack(fill="x", pady=8)
    edit.columnconfigure(1,weight=1); edit.columnconfigure(3,weight=1)
    name=tk.StringVar(); xp=tk.StringVar(); disabled=tk.BooleanVar(); dlc=tk.BooleanVar(value=True)
    field(edit,"Display name",name,0); field(edit,"Stored online SP",xp,0,2)
    ttk.Checkbutton(edit,text="Disable this player's login",variable=disabled).grid(row=1,column=0,columnspan=2,sticky="w")
    ttk.Checkbutton(edit,text="DLC vehicle compatibility grants",variable=dlc).grid(row=1,column=2,columnspan=2,sticky="w")
    edit_layout={"narrow":None}
    def arrange_edit(event):
        narrow=event.width<800
        if narrow==edit_layout["narrow"]: return
        edit_layout["narrow"]=narrow
        for child in edit.winfo_children():
            info=child.grid_info(); col=int(info["column"])
            if isinstance(child,ttk.Checkbutton):
                child.grid_configure(row=2 if child.cget("text").startswith("Disable") else (3 if narrow else 2), column=0 if narrow or child.cget("text").startswith("Disable") else 2)
            elif isinstance(child,ttk.Entry) and str(child.cget("textvariable"))==str(xp):
                child.grid_configure(row=1 if narrow else 0,column=1 if narrow else 3)
            elif isinstance(child,ttk.Label) and child.cget("text")=="Stored online SP":
                child.grid_configure(row=1 if narrow else 0,column=0 if narrow else 2)
        edit.columnconfigure(3,weight=0 if narrow else 1)
    edit.bind("<Configure>",arrange_edit)
    def on_select(_):
        try: record=selected()
        except ValueError: return
        name.set(record["name"]); xp.set(str(record["stats"].get("xp",0)))
        disabled.set(record["stats"].get("disabled",False)); dlc.set(record["stats"].get("dlc_compatibility",True))
    tree.bind("<<TreeviewSelect>>",on_select)
    def apply_player():
        try:
            record=selected(); value=int(xp.get())
            payload={"action":"update","persona_id":record["persona_id"],"name":name.get().strip(),"xp":value,
                     "disabled":disabled.get(),"dlc_compatibility":dlc.get()}
        except ValueError as exc: return messagebox.showerror("Player edit",str(exc))
        confirm("Apply player changes", "Save these changes? A safety snapshot is created and this player is disconnected. A later game report can increase their stored XP.",
                lambda: operation("Updating player…", lambda c:c.admin("/admin/player",payload)["message"]))
    def export_player():
        try: record=selected()
        except ValueError as exc: return messagebox.showinfo("Player backup",str(exc))
        path=filedialog.asksaveasfilename(defaultextension=".json",initialfile=f"{record['name']}-{record['persona_id']}.json",filetypes=[("Player backup","*.json")])
        if path: operation("Saving player…", lambda c:c.export_player(record["persona_id"],path))
    def import_player():
        path=filedialog.askopenfilename(filetypes=[("Player backup","*.json")])
        if path: confirm("Restore player", "Restore this player's server record? The player must be offline.",lambda:operation("Restoring player…",lambda c:c.import_player(path)))
    def kick():
        try: record=selected()
        except ValueError as exc: return messagebox.showinfo("Disconnect player",str(exc))
        confirm("Disconnect player", f"Disconnect {record['name']}?",lambda:operation("Disconnecting player…",lambda c:c.admin("/admin/player",{"action":"kick","persona_id":record["persona_id"]})["message"]))
    bar=ButtonRow(players_page);bar.pack(fill="x")
    button(bar,"Load players",lambda:operation("Loading registered players…",lambda c:c.players(),populate),True)
    button(bar,"Apply changes",apply_player);button(bar,"Back up player",export_player);button(bar,"Restore player",import_player);button(bar,"Disconnect",kick)
    ttk.Label(players_page,text="Compatibility grants cover the five DLC vehicle entries already supported by this backend; installed game content is required. This does not unlock the career garage.",style="Muted.TLabel",wraplength=900).pack(anchor="w",pady=7)

    backups_page=pages["Backups"]
    ttk.Label(backups_page,text="Keep your crew's progress",style="Title.TLabel").pack(anchor="w")
    ttk.Label(backups_page,text="Portable server backups include personas, identity hashes, online XP, compatibility flags, friend roster and license plates. Restore them under another AWS profile or region.",wraplength=850,style="Muted.TLabel").pack(anchor="w",pady=10)
    folder=DATA/"Backups";folder.mkdir(parents=True,exist_ok=True)
    history_frame=ttk.Frame(backups_page);history_frame.pack(fill="both",expand=True,pady=8)
    history=tk.Listbox(history_frame,bg="#1b2128",fg="white",selectbackground="#83252d",relief="flat",font=("Segoe UI",10),height=9)
    history.grid(row=0,column=0,sticky="nsew")
    history_frame.columnconfigure(0,weight=1);history_frame.rowconfigure(0,weight=1)
    hx=ttk.Scrollbar(history_frame,orient="horizontal",command=history.xview)
    hy=ttk.Scrollbar(history_frame,orient="vertical",command=history.yview)
    history.configure(xscrollcommand=hx.set,yscrollcommand=hy.set)
    hx.grid(row=1,column=0,sticky="ew");hy.grid(row=0,column=1,sticky="ns")
    def refresh_history():
        history.delete(0,"end")
        for path in sorted(folder.glob("*.tar.gz"),reverse=True): history.insert("end",path.name)
    refresh_history()
    def backup():
        path=filedialog.asksaveasfilename(initialdir=folder,initialfile=f"{instance.get()}-{datetime.datetime.now():%Y%m%d-%H%M%S}.tar.gz",defaultextension=".tar.gz",filetypes=[("Server backup","*.tar.gz")])
        if path: operation("Saving server data…",lambda c:c.save(path),lambda result:(win.status.set("Saved "+result),refresh_history()))
    def restore():
        path=filedialog.askopenfilename(initialdir=folder,filetypes=[("Server backup","*.tar.gz")])
        if path: confirm("Restore server", "Replace server progression with this backup and restart? A safety backup of the current data is saved first.",lambda:operation("Restoring server…",lambda c:c.restore(path)))
    def terminate():
        path=filedialog.asksaveasfilename(initialdir=folder,initialfile=f"{instance.get()}-final-{datetime.datetime.now():%Y%m%d-%H%M%S}.tar.gz",defaultextension=".tar.gz")
        if path: confirm("Back up and delete AWS instance",f"Save a validated backup to {path}, then permanently delete {instance.get()} in {profile.get()} / {region.get()}? This disconnects everyone. AWS snapshots remain billed separately.",lambda:operation("Backing up before deletion…",lambda c:c.terminate(path)))
    bar=ButtonRow(backups_page);bar.pack(fill="x")
    button(bar,"Back up server",backup,True);button(bar,"Restore server",restore)
    button(bar,"Open backup folder",lambda:os.startfile(folder));button(bar,"Refresh list",refresh_history)
    bar=ButtonRow(backups_page);bar.pack(fill="x")
    button(bar,"Create AWS snapshot",lambda:confirm("AWS snapshot", "Create an AWS disk snapshot? AWS charges for retained snapshot storage.",lambda:operation("Requesting AWS snapshot…",lambda c:c.snapshot())))
    button(bar,"Back up and delete instance",terminate)

    setup=pages["Host new server"]
    ttk.Label(setup,text="Build a fresh race server",style="Title.TLabel").pack(anchor="w")
    ttk.Label(setup,text="1. Choose or configure your AWS profile and region above.\n2. Test access, choose a plan and optionally select a server backup.\n3. Create the server. Setup installs the services, checks connectivity and creates a player ZIP with the new IP.\nIf setup is interrupted, use Resume installation; the saved key is loaded automatically.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=8)
    access=tk.StringVar(value="Region access has not been checked.")
    ttk.Label(setup,textvariable=access,wraplength=850).pack(anchor="w",pady=6)
    plans={};plan_value=tk.StringVar();restore_value=tk.StringVar()
    plan_box=ttk.Combobox(setup,textvariable=plan_value,state="readonly",width=90);plan_box.pack(fill="x",pady=6);win.inputs.append(plan_box)
    ttk.Label(setup,text="2 GB is the recommended starting plan for one lobby, up to the game's 12-player limit. More RAM adds headroom; 12 simultaneous players have not been load-tested.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=5)
    restore_row=ttk.Frame(setup);restore_row.pack(fill="x",pady=5);restore_row.columnconfigure(1,weight=1)
    field(restore_row,"Optional server backup",restore_value,0)
    def choose_restore():
        path=filedialog.askopenfilename(filetypes=[("Server backup","*.tar.gz")])
        if path: restore_value.set(path)
    ttk.Button(restore_row,text="Browse",command=choose_restore).grid(row=0,column=2)
    tested={"scope":None}
    def preflight_result(data):
        tested["scope"]=(profile.get(),region.get())
        plans.clear()
        for p in data["bundles"]:
            label=f"{p['ramSizeInGb']:g} GB RAM / {p['cpuCount']} vCPU   •   ${p['price']:g}/month   •   {p['bundleId']}"
            plans[label]=p["bundleId"]
        plan_box.configure(values=list(plans));plan_value.set(next(iter(plans),""))
        region_box.configure(values=data["regions"])
        access.set(f"Account {data['account']} • {data['region']}\n{data['permission_note']}\nExisting servers: "+(", ".join(i["name"] for i in data["instances"]) or "None"))
        win.status.set("Region read access verified; choose a plan")
    def created(record):
        key.set(record["key"]);server_ip["value"]=record["ip"];address.set(record["ip"])
        state.set("Server ready • "+record["instance"]);win.status.set("Ready. Copy the player invite from Server.")
        client();tabs.select(server_page.page)
        win.job("Server is live. Creating your player ZIP…",lambda:player_pack(record["ip"],pack_destination(record["ip"])),shared)
    def shared(path):
        pack_ready(path)
        messagebox.showinfo("Your server is live", f"Server IP: {server_ip['value']}\n\nPlayer launcher ZIP:\n{path}\n\nSend this ZIP to your friends. They extract it, choose their game folder and display name, then Play. The IP is already filled in and can be changed later.")
        os.startfile(Path(path).parent)
    def create():
        if tested["scope"]!=(profile.get(),region.get()) or plan_value.get() not in plans:
            return messagebox.showinfo("Test region first","Test this AWS profile and region before creating a server")
        plan=plans[plan_value.get()];backup=restore_value.get().strip()
        try:c=client()
        except Exception as exc:return messagebox.showerror("Create server",str(exc))
        confirm("Create paid AWS server",f"Create {instance.get()} in {profile.get()} / {region.get()}?\n{plan_value.get()}\nAWS bills the instance while stopped as well as running. Extra traffic and snapshots can add charges.",lambda:win.job("Starting fresh host setup…",lambda:c.create(plan,win.progress,backup),created))
    def resume():
        operation("Resuming server installation…",lambda c:c.resume(win.progress),created)
    bar=ButtonRow(setup);bar.pack(fill="x",pady=7)
    button(bar,"Test AWS & region",lambda:operation("Checking AWS account and regional access…",lambda c:c.preflight(),preflight_result),True)
    button(bar,"Create server",create);button(bar,"Resume installation",resume)
    def configure_profile():
        value=profile.get().strip()
        if not value or value.startswith("-"):return messagebox.showinfo("AWS profile","Enter the name of the AWS profile you want to configure")
        # This console belongs to the user because AWS setup requires their credentials.
        subprocess.Popen(["cmd.exe","/k",subprocess.list2cmdline([aws_executable(),"configure","--profile",value])])
    def sso(): operation("Opening AWS SSO sign-in…",lambda c:run(c.cli[:1]+["sso","login","--profile",profile.get()],timeout=300).decode())
    bar=ButtonRow(setup);bar.pack(fill="x")
    button(bar,"Configure AWS profile",configure_profile);button(bar,"Sign in with SSO",sso)
    button(bar,"Install AWS CLI",lambda:webbrowser.open("https://awscli.amazonaws.com/AWSCLIV2.msi"))
    def load_deployment():
        path=filedialog.askopenfilename(initialdir=DATA,filetypes=[("Saved deployment","*-deployment.json")])
        if not path:return
        data=json.loads(Path(path).read_text())
        for var,k in ((profile,"profile"),(region,"region"),(instance,"instance"),(key,"key")):var.set(data[k])
        win.status.set("Deployment settings loaded")
    button(bar,"Load saved deployment",load_deployment)

    help_page=pages["Help"]
    ttk.Label(help_page,text="One setup. Two roles.",style="Title.TLabel").pack(anchor="w")
    help_text=("Players: open Fairhaven Player, choose the original NFS13.exe folder, enter the host IP and your display name, then Play. Your personal identity is stored on your PC; use Export identity before moving PCs.\n\n"
               "Hosts: configure AWS CLI, test the selected profile and region, choose a plan and create a server. The app saves the SSH key and deployment settings locally. A static IP keeps player invites stable. To switch accounts later, back up server data and restore it during a fresh setup.\n\n"
               "Server data: persona IDs, credential hashes, reported online XP, compatibility flags and license plates. Full single-player career saves, car ownership and downloaded DLC files remain on each player's PC. The Player app can back up local saves.\n\n"
               "Networking: game traffic is peer to peer. Players must be reachable by each other; university networks or strict NAT can require a shared VPN. SSH management opens port 22 only to your current public IP while needed.\n\n"
               "Costs: the plan price comes from AWS for the selected region. Stopping an instance does not stop its plan charges. Back up and delete it when finished. Retained AWS snapshots have separate charges.\n\n"
               "Source and licenses are installed beside the apps. This is independent private-server software.")
    ttk.Label(help_page,text=help_text,wraplength=870,justify="left").pack(anchor="w",pady=14)
    bar=ButtonRow(help_page);bar.pack(fill="x")
    button(bar,"Open app data",lambda:os.startfile(DATA))
    button(bar,"Open AWS console",lambda:webbrowser.open("https://lightsail.aws.amazon.com/"))
    if "--setup" in sys.argv or not default:
        tabs.select(setup.page)
    win.root.report_callback_exception=lambda t,v,tb:messagebox.showerror("Fairhaven",str(v))
    win.root.mainloop()
    return win


if __name__ == "__main__":
    main()
