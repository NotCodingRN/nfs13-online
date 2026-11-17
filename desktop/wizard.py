# SPDX-License-Identifier: AGPL-3.0-only
"""Step-by-step server setup: AWS CLI, AWS account, region and plan, create."""
import configparser
import os
import queue
import shutil
import socket
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cloud import Cloud, run, aws_executable
from sharing import player_pack
from ui import DATA, tk

# Regions with Lightsail; the region check confirms the account can use one.
REGIONS = (
    ("us-east-1", "US East (N. Virginia)"), ("us-east-2", "US East (Ohio)"), ("us-west-2", "US West (Oregon)"),
    ("ca-central-1", "Canada (Central)"), ("eu-central-1", "Europe (Frankfurt)"), ("eu-west-1", "Europe (Ireland)"),
    ("eu-west-2", "Europe (London)"), ("eu-west-3", "Europe (Paris)"), ("eu-north-1", "Europe (Stockholm)"),
    ("eu-south-2", "Europe (Spain)"), ("ap-south-1", "Asia Pacific (Mumbai)"),
    ("ap-southeast-1", "Asia Pacific (Singapore)"), ("ap-southeast-2", "Asia Pacific (Sydney)"),
    ("ap-northeast-1", "Asia Pacific (Tokyo)"), ("ap-northeast-2", "Asia Pacific (Seoul)"),
)
LABELS = {code: f"{name}  ·  {code}" for code, name in REGIONS}
STEPS = ("AWS tools", "AWS account", "Region & plan", "Create", "Done")
NEW_PROFILE = "nfs13"


def list_profiles():
    try:
        return [p.strip() for p in run(["aws", "configure", "list-profiles"], timeout=30).decode().splitlines() if p.strip()]
    except (OSError, ValueError, RuntimeError):
        return []


def save_keys(profile, key_id, secret):
    """Store keys like `aws configure` does, without putting the secret on a command line."""
    if not (key_id.startswith(("AKIA", "ASIA")) and len(key_id) == 20):
        raise ValueError("The access key ID is 20 characters and starts with AKIA.")
    if len(secret) != 40:
        raise ValueError("The secret access key is 40 characters. Paste the whole key.")
    path = Path(os.getenv("AWS_SHARED_CREDENTIALS_FILE", Path.home() / ".aws" / "credentials"))
    path.parent.mkdir(parents=True, exist_ok=True)
    config = configparser.RawConfigParser()
    config.read(path, encoding="utf-8")
    if not config.has_section(profile):
        config.add_section(profile)
    config.set(profile, "aws_access_key_id", key_id)
    config.set(profile, "aws_secret_access_key", secret)
    with open(path, "w", encoding="utf-8") as handle:
        config.write(handle)


def latency(region):
    """Best of three TCP connects to the region's Lightsail endpoint, in ms, or None."""
    best = None
    for _ in range(3):
        try:
            start = time.perf_counter()
            with socket.create_connection((f"lightsail.{region}.amazonaws.com", 443), timeout=2.5):
                pass
            ms = int((time.perf_counter() - start) * 1000)
            best = ms if best is None else min(best, ms)
        except OSError:
            pass
    return best


def is_sso_error(message):
    text = message.lower()
    return "sso" in text or "token has expired" in text or "token is expired" in text


class Wizard:
    def __init__(self, master, saved, on_done):
        self.saved, self.on_done = saved, on_done
        self.top = tk.Toplevel(master, bg="#101316")
        self.top.title("Fairhaven • Set up a server")
        self.top.geometry("900x620")
        self.top.minsize(760, 540)
        self.top.transient(master)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(self.top)
        style.configure("TRadiobutton", background="#101316", foreground="#eef1f4", padding=4)
        style.map("TRadiobutton", background=[("active", "#232b34")])
        style.configure("Good.TLabel", foreground="#4cd07d")
        style.configure("Bad.TLabel", foreground="#ff6b6b")
        self.top.columnconfigure(1, weight=1)
        self.top.rowconfigure(0, weight=1)
        self.side = tk.Frame(self.top, bg="#171c22", width=220)
        self.side.grid(row=0, column=0, rowspan=2, sticky="ns")
        self.side.grid_propagate(False)
        self.page = ttk.Frame(self.top, padding=(26, 22, 26, 8))
        self.page.grid(row=0, column=1, sticky="nsew")
        self.page.columnconfigure(0, weight=1)
        footer = ttk.Frame(self.top, padding=(26, 8, 26, 18))
        footer.grid(row=1, column=1, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.back = ttk.Button(footer, text="Back", command=lambda: self.show(self.step - 1))
        self.back.grid(row=0, column=0, sticky="w")
        self.message = tk.StringVar()
        self.message_label = ttk.Label(footer, textvariable=self.message, style="Muted.TLabel", wraplength=420)
        self.message_label.grid(row=0, column=1, sticky="w", padx=14)
        self.next = ttk.Button(footer, text="Next", style="Play.TButton")
        self.next.grid(row=0, column=2, sticky="e")
        self.events = queue.Queue()
        self.busy = False
        self.step = 0
        self.profile = saved.get("profile", "")
        self.region = saved.get("region", "us-east-1")
        self.checked = None  # preflight result for (profile, region, name)
        self.record = None
        self.pack = None
        self.choice = None  # instance, plan and backup picked on the region page
        self.log = None
        self.timer = self.top.after(80, self.poll)
        self.top.bind("<Destroy>", lambda e: e.widget is self.top and self.top.after_cancel(self.timer))
        self.show(0)

    # ------------------------------------------------------------ plumbing
    def background(self, action, done, failed=None):
        self.busy = True
        self.next.state(["disabled"]); self.back.state(["disabled"])
        def work():
            try:
                self.events.put((done, action()))
            except Exception as exc:  # shown to the user, never swallowed
                self.events.put((failed or self.fail, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            callback, value = self.events.get()
            if callback == "log":
                self.log_line(value)
                continue
            self.busy = False
            self.next.state(["!disabled"])
            if self.step not in (0, 4):
                self.back.state(["!disabled"])
            callback(value)
        self.timer = self.top.after(80, self.poll)

    def fail(self, text):
        self.say(text, bad=True)

    def say(self, text, bad=False, good=False):
        self.message.set(text)
        self.message_label.configure(style="Bad.TLabel" if bad else "Good.TLabel" if good else "Muted.TLabel")

    def close(self):
        if self.busy and self.step == 3:
            return messagebox.showinfo("Setup in progress", "Wait for this step to finish. Closing now could leave a half-built server.", parent=self.top)
        self.top.destroy()

    def draw_sidebar(self):
        for child in self.side.winfo_children():
            child.destroy()
        tk.Label(self.side, text="SET UP", bg="#171c22", fg="#d81920", font=("Bahnschrift", 11, "bold")).pack(anchor="w", padx=18, pady=(22, 12))
        for index, name in enumerate(STEPS):
            done, current = index < self.step, index == self.step
            mark = "✓" if done else str(index + 1)
            tk.Label(self.side, text=f"  {mark}   {name}", anchor="w",
                     bg="#2a323c" if current else "#171c22",
                     fg="#4cd07d" if done else "#ffffff" if current else "#7d8894",
                     font=("Segoe UI", 10, "bold" if current else "normal")).pack(fill="x", padx=8, pady=2, ipady=7)

    def show(self, step):
        self.step = step
        for child in self.page.winfo_children():
            child.destroy()
        self.say("")
        self.draw_sidebar()
        self.back.grid() if 0 < step < 4 else self.back.grid_remove()
        self.next.state(["!disabled"])
        self.next.configure(text="Next")
        (self.page_tools, self.page_account, self.page_region, self.page_create, self.page_done)[step]()

    def title(self, text, sub=None):
        ttk.Label(self.page, text=text, style="Title.TLabel").grid(sticky="w")
        if sub:
            ttk.Label(self.page, text=sub, style="Muted.TLabel", wraplength=600, justify="left").grid(sticky="w", pady=(4, 12))

    def text(self, value, style="TLabel", **grid):
        label = ttk.Label(self.page, text=value, style=style, wraplength=600, justify="left")
        label.grid(sticky="w", **({"pady": 3} | grid))
        return label

    def row(self):
        frame = ttk.Frame(self.page)
        frame.grid(sticky="w", pady=6)
        return frame

    # ------------------------------------------------------------ 1. tools
    def page_tools(self):
        self.title("AWS tools", "The app creates and manages your server through Amazon's command-line tool. You install it once.")
        aws_status = self.text("Checking the AWS CLI…", "Muted.TLabel")
        ssh_status = self.text("Checking Windows OpenSSH…", "Muted.TLabel")
        buttons = self.row()
        ttk.Button(buttons, text="Download AWS CLI", command=lambda: webbrowser.open("https://awscli.amazonaws.com/AWSCLIV2.msi")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Turn on OpenSSH", command=lambda: os.startfile("ms-settings:optionalfeatures")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Check again", command=lambda: self.show(0)).pack(side="left")
        self.text("Install the AWS CLI with the default options. OpenSSH Client is under Settings → Apps → Optional features. Then click Check again.", "Muted.TLabel", pady=(10, 0))
        self.next.configure(command=lambda: self.show(1))
        def check():
            version = run(["aws", "--version"], timeout=30).decode().split(" ")[0] if self.has_aws() else ""
            return version, bool(shutil.which("ssh"))
        def done(result):
            version, ssh = result
            aws_status.configure(text=f"✓  AWS CLI found ({version})" if version else "✗  The AWS CLI isn't installed yet.",
                                 style="Good.TLabel" if version else "Bad.TLabel")
            ssh_status.configure(text="✓  Windows OpenSSH found" if ssh else "✗  Windows OpenSSH Client isn't turned on.",
                                 style="Good.TLabel" if ssh else "Bad.TLabel")
            if version and ssh:
                self.say("Everything needed is installed.", good=True)
            else:
                self.next.state(["disabled"])
        self.background(check, done)

    @staticmethod
    def has_aws():
        try:
            aws_executable()
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------ 2. account
    def page_account(self):
        self.title("Connect your AWS account", "Pick an AWS profile that's already on this PC, or paste a new access key.")
        mode = tk.StringVar(value="existing")
        chosen = tk.StringVar(value=self.profile)
        top = self.row()
        existing = ttk.Radiobutton(top, text="Use a profile on this PC", variable=mode, value="existing")
        existing.grid(row=0, column=0, sticky="w")
        combo = ttk.Combobox(top, textvariable=chosen, state="readonly", width=28)
        combo.grid(row=0, column=1, sticky="w", padx=12)
        ttk.Radiobutton(top, text="Add a new access key", variable=mode, value="new").grid(row=1, column=0, sticky="w", pady=(10, 0))
        keys = ttk.Frame(self.page)
        keys.grid(sticky="ew", pady=(4, 6))
        key_id, secret = tk.StringVar(), tk.StringVar()
        ttk.Label(keys, text="Access key ID", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(keys, text="Secret access key", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))
        id_entry = ttk.Entry(keys, textvariable=key_id, width=28)
        id_entry.grid(row=1, column=0, sticky="w")
        secret_entry = ttk.Entry(keys, textvariable=secret, width=34, show="•")
        secret_entry.grid(row=1, column=1, sticky="w", padx=(14, 0))
        steps = ("1.  In the AWS console open IAM → Users → Create user (e.g. nfs13-host).\n"
                 "2.  Choose “Attach policies directly” and tick AdministratorAccess.\n"
                 "3.  Open the user → Security credentials → Create access key → Command Line Interface.\n"
                 f"The key is saved as the AWS profile “{NEW_PROFILE}” on this PC.")
        help_text = ttk.Label(keys, text=steps, style="Muted.TLabel", wraplength=600, justify="left")
        help_text.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))
        open_iam = ttk.Button(keys, text="Open AWS IAM", command=lambda: webbrowser.open("https://console.aws.amazon.com/iam/home#/users"))
        open_iam.grid(row=3, column=0, sticky="w")
        sso_button = ttk.Button(self.page, text="Sign in with AWS SSO")
        def sync(*_):
            new = mode.get() == "new"
            combo.state(["disabled"] if new else ["!disabled", "readonly"])
            for widget in (id_entry, secret_entry, open_iam):
                widget.state(["!disabled"] if new else ["disabled"])
        mode.trace_add("write", sync)

        def loaded(profiles):
            combo.configure(values=profiles)
            if profiles:
                chosen.set(self.profile if self.profile in profiles else profiles[0])
                self.say(f"Found {len(profiles)} AWS profile{'s' if len(profiles) != 1 else ''} on this PC.")
            else:
                mode.set("new")
                existing.state(["disabled"])
                self.say("No AWS profiles on this PC yet. Add an access key below.")
            sync()
        self.background(list_profiles, loaded)

        def verified(result):
            profile, arn = result
            self.profile = profile
            self.checked = None
            self.say(f"✓  Connected as {arn}", good=True)
            self.top.after(700, lambda: self.show(2))
        def failed(text):
            profile = chosen.get() if mode.get() == "existing" else NEW_PROFILE
            if is_sso_error(text):
                self.say(f"“{profile}” signs in through AWS SSO and needs a fresh sign-in.", bad=True)
                sso_button.configure(command=lambda: self.background(
                    lambda: run(["aws", "sso", "login", "--profile", profile], timeout=300),
                    lambda _: self.say("Signed in. Click Check and continue.", good=True)))
                sso_button.grid(sticky="w", pady=6)
            else:
                self.say("AWS didn't accept this profile: " + text.strip().splitlines()[-1][:220], bad=True)
        def check():
            if mode.get() == "new":
                profile = NEW_PROFILE
                ident, key = key_id.get().strip(), secret.get().strip()
                action = lambda: (save_keys(profile, ident, key), identity(profile))[1]
            else:
                profile = chosen.get()
                if not profile:
                    return self.say("Pick a profile.", bad=True)
                action = lambda: identity(profile)
            self.say("Checking your AWS access…")
            self.background(action, verified, failed)
        def identity(profile):
            import json
            data = json.loads(run(["aws", "--profile", profile, "sts", "get-caller-identity", "--output", "json"], timeout=60))
            return profile, data["Arn"]
        self.next.configure(text="Check and continue", command=check)

    # ------------------------------------------------------------ 3. region & plan
    def page_region(self):
        self.title("Region and plan", "Pick where the server runs. Closer to your players means lower lag in lobbies.")
        region = tk.StringVar(value=LABELS.get(self.region, LABELS["us-east-1"]))
        name = tk.StringVar(value=self.saved.get("new_instance", "fairhaven-racing"))
        backup = tk.StringVar()
        plan = tk.StringVar()
        plans = {}
        grid = ttk.Frame(self.page)
        grid.grid(sticky="ew", pady=4)
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Region", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=5)
        region_box = ttk.Combobox(grid, textvariable=region, values=list(LABELS.values()), state="readonly", width=40)
        region_box.grid(row=0, column=1, sticky="w", padx=10)
        fastest = ttk.Button(grid, text="Find the fastest")
        fastest.grid(row=0, column=2, sticky="w")
        ttk.Label(grid, text="Server name", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(grid, textvariable=name, width=30).grid(row=1, column=1, sticky="w", padx=10)
        ttk.Label(grid, text="Plan", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        plan_box = ttk.Combobox(grid, textvariable=plan, state="disabled", width=56)
        plan_box.grid(row=2, column=1, columnspan=2, sticky="w", padx=10)
        ttk.Label(grid, text="Restore backup", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(grid, textvariable=backup, width=44).grid(row=3, column=1, sticky="w", padx=10)
        ttk.Button(grid, text="Browse", command=lambda: backup.set(
            filedialog.askopenfilename(parent=self.top, initialdir=DATA / "Backups", filetypes=[("Server backup", "*.tar.gz")]) or backup.get())
        ).grid(row=3, column=2, sticky="w")
        account = self.text("", "Muted.TLabel", pady=(10, 0))
        self.text("Optional: restore a backup to bring back players' names and online XP. 2 GB is plenty for one 12-player lobby.", "Muted.TLabel")

        def code():
            return next(c for c, label in LABELS.items() if label == region.get())
        def reset(*_):
            self.checked = None
            plan_box.configure(values=[]); plan.set(""); plan_box.state(["disabled"])
            self.next.configure(text="Check region")
        region.trace_add("write", reset); name.trace_add("write", reset)

        def measured(times):
            fastest.state(["!disabled"]); fastest.configure(text="Find the fastest")
            ok = {r: ms for r, ms in times.items() if ms is not None}
            if not ok:
                return self.say("Couldn't reach AWS to measure. Check your internet.", bad=True)
            best = min(ok, key=ok.get)
            region.set(LABELS[best])
            self.say(f"Fastest from here: {LABELS[best].split('  ·')[0]} ({ok[best]} ms).", good=True)
        def measure():
            fastest.state(["disabled"]); fastest.configure(text="Measuring…")
            def work():
                times = {}
                threads = [threading.Thread(target=lambda r=r: times.__setitem__(r, latency(r))) for r, _ in REGIONS]
                for t in threads: t.start()
                for t in threads: t.join()
                return times
            threading.Thread(target=lambda: self.events.put((measured, work())), daemon=True).start()
        fastest.configure(command=measure)

        def checked(data):
            self.checked = (self.profile, data["region"], name.get().strip(), data)
            plans.clear()
            for b in data["bundles"]:
                plans[f"{b['ramSizeInGb']:g} GB RAM · {b['cpuCount']} vCPU · ${b['price']:g}/month"] = b["bundleId"]
            plan_box.configure(values=list(plans)); plan_box.state(["!disabled", "readonly"])
            two = next((label for label, bid in plans.items() if label.startswith("2 GB")), next(iter(plans)))
            plan.set(two)
            existing = [i["name"] for i in data["instances"]]
            account.configure(text=f"AWS account {data['account']}. Servers already in this region: {', '.join(existing) or 'none'}.")
            if name.get().strip() in existing:
                self.checked = None
                return self.say(f"A server called “{name.get().strip()}” already exists here. Choose another name.", bad=True)
            self.say("✓  This region is ready. Pick a plan and continue.", good=True)
            self.next.configure(text="Next")
        def failed(text):
            if "not offered" in text or "OptInRequired" in text or "not subscribed" in text.lower():
                text = "Your account can't use this region yet (it may need turning on under Account → AWS Regions). Pick another."
            self.say(text.strip().splitlines()[-1][:260], bad=True)
        def go():
            if self.checked and self.checked[1] == code() and self.checked[2] == name.get().strip():
                if backup.get() and not Path(backup.get()).is_file():
                    return self.say("That backup file doesn't exist.", bad=True)
                self.region = code()
                self.choice = {"instance": name.get().strip(), "bundle": plans[plan.get()], "plan": plan.get(),
                               "backup": backup.get().strip(), "price_note": plan.get()}
                return self.show(3)
            try:
                cloud = Cloud(self.profile, code(), name.get().strip(), "")
            except ValueError as exc:
                return self.say(str(exc), bad=True)
            self.say("Checking this region with your AWS account…")
            self.background(cloud.preflight, checked, failed)
        self.next.configure(text="Check region", command=go)

    # ------------------------------------------------------------ 4. create
    def page_create(self):
        c = self.choice
        self.title("Create the server", None)
        self.text(f"{c['instance']} in {LABELS[self.region].split('  ·')[0]}, {c['plan']}." +
                  (" Your backup is restored after setup." if c["backup"] else ""))
        self.text("AWS bills this server every month until you delete it, even while it's stopped. "
                  "Setup takes about 5–15 minutes; you can watch it below.", "Muted.TLabel")
        self.log = tk.Text(self.page, bg="#1b2128", fg="#d9e1e9", relief="flat", height=12,
                           font=("Consolas", 10), wrap="word", padx=10, pady=8, state="disabled")
        self.log.grid(sticky="nsew", pady=(10, 0))
        self.page.rowconfigure(self.log.grid_info()["row"], weight=1)
        cloud = Cloud(self.profile, self.region, c["instance"], "")
        report = lambda line: self.events.put(("log", line))
        def finished(record):
            self.record = record
            self.log_line(f"Server is ready at {record['ip']}. Making the player ZIP…")
            self.background(lambda: player_pack(record["ip"], DATA / "PlayerPacks" / f"NFS13-Players-{record['ip']}.zip"),
                            lambda path: (setattr(self, "pack", path), self.show(4)))
        def failed(text):
            self.log_line("Stopped: " + text.strip())
            self.say("Setup stopped. Fix the problem, then click Resume to continue where it left off.", bad=True)
            self.next.configure(text="Resume", command=lambda: start(cloud.resume))
        def start(action):
            self.say("Working… keep this window open.")
            self.background(lambda: action(report) if action == cloud.resume else action(c["bundle"], report, c["backup"]),
                            finished, failed)
        self.next.configure(text="Create server", command=lambda: start(cloud.create))

    def log_line(self, line):
        if not getattr(self, "log", None) or not self.log.winfo_exists():
            return
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S  ") + str(line) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ 5. done
    def page_done(self):
        record = self.record
        self.title("Your server is live", "Send the player ZIP to your friends. They unzip it, pick their game folder and a name, then click Play.")
        ttk.Label(self.page, text=record["ip"], style="Stat.TLabel").grid(sticky="w", pady=(4, 8))
        self.text("Player ZIP: " + str(self.pack), "Muted.TLabel")
        buttons = self.row()
        ttk.Button(buttons, text="Open player ZIP folder", command=lambda: os.startfile(Path(self.pack).parent)).pack(side="left", padx=(0, 8))
        def copy():
            self.top.clipboard_clear()
            self.top.clipboard_append(f"NFS Most Wanted 2012 server: {record['ip']}\nUnzip the player ZIP, run NFS13Player.exe, pick your game folder and a name, then Play.")
            self.say("Invite copied.", good=True)
        ttk.Button(buttons, text="Copy invite text", command=copy).pack(side="left")
        self.text("When you're done playing for good, use Backups → Back up and delete instance so AWS stops billing.", "Muted.TLabel", pady=(12, 0))
        def finish():
            self.top.destroy()
            self.on_done(record, self.pack)
        self.next.configure(text="Finish", command=finish)
