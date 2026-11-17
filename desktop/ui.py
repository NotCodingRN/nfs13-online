# SPDX-License-Identifier: AGPL-3.0-only
import os
import sys
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

DATA = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Fairhaven"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

class Window:
    def __init__(self, title, heading):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg="#101316")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.minsize(680, 460)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#101316", foreground="#eef1f4", font=("Segoe UI", 10))
        style.configure("TFrame", background="#101316")
        style.configure("TLabel", background="#101316", foreground="#eef1f4", padding=1)
        style.configure("Muted.TLabel", foreground="#a9b5c2")
        style.configure("Title.TLabel", font=("Bahnschrift SemiCondensed", 22, "bold"))
        style.configure("Stat.TLabel", foreground="#ffd227", font=("Bahnschrift", 20, "bold"))
        style.configure("TButton", background="#303944", foreground="#ffffff", padding=(13, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#465365"), ("disabled", "#232a32")], foreground=[("disabled", "#77828d")])
        style.configure("Play.TButton", background="#d81920", foreground="white", font=("Bahnschrift", 12, "bold"), padding=(16, 10))
        style.map("Play.TButton", background=[("active", "#f12d36"), ("disabled", "#5b252b")])
        style.configure("TEntry", fieldbackground="#232b34", foreground="white", insertcolor="white", padding=7)
        style.configure("TCombobox", fieldbackground="#232b34", background="#303944", foreground="white", padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#232b34")], foreground=[("readonly", "white")])
        style.configure("TCheckbutton", background="#101316", foreground="#eef1f4", padding=5)
        style.map("TCheckbutton", background=[("active", "#232b34")])
        style.configure("TNotebook", background="#101316", borderwidth=0)
        style.configure("TNotebook.Tab", background="#232b34", foreground="#b7c2cd", padding=(18, 10), font=("Bahnschrift", 11))
        style.map("TNotebook.Tab", background=[("selected", "#d81920")], foreground=[("selected", "white")])
        style.configure("Treeview", background="#1b2128", fieldbackground="#1b2128", foreground="#eef1f4", rowheight=31, borderwidth=0)
        style.configure("Treeview.Heading", background="#303944", foreground="white", padding=7)
        style.map("Treeview", background=[("selected", "#83252d")], foreground=[("selected", "white")])
        style.configure("TLabelframe", background="#101316", bordercolor="#35404c")
        style.configure("TLabelframe.Label", background="#101316", foreground="#a9b5c2")
        self.root.option_add("*TCombobox*Listbox.background", "#232b34")
        self.root.option_add("*TCombobox*Listbox.foreground", "white")
        banner = tk.Canvas(self.root, height=86, bg="#e9ecef", highlightthickness=0)
        banner.grid(row=0, column=0, sticky="ew")
        def draw(event):
            banner.delete("all")
            w = event.width
            banner.create_polygon(w-260,0,w,0,w,86,w-310,86,fill="#d81920",outline="")
            banner.create_text(24,28,text=heading,anchor="w",fill="#171b20",font=("Bahnschrift SemiCondensed",26,"bold"))
            banner.create_text(26,62,text="MOST WANTED  /  PRIVATE RACING",anchor="w",fill="#58626c",font=("Bahnschrift",10))
            banner.create_text(w-30,43,text="FAIRHAVEN",anchor="e",fill="white",font=("Bahnschrift",17,"bold"))
        banner.bind("<Configure>", draw)
        self.form = ttk.Frame(self.root, padding=20)
        self.form.grid(row=1, column=0, sticky="nsew")
        self.form.columnconfigure(1, weight=1)
        self.buttons = []
        self.inputs = []
        self.events = queue.Queue()
        self.busy = False
        self.status = tk.StringVar(value="Ready")
        self.note(self.status)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(80, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation in progress", "Wait for the current operation to finish.")
        else:
            self.root.destroy()

    def note(self, variable):
        ttk.Label(self.form, textvariable=variable, wraplength=920).grid(columnspan=3, sticky="w", pady=5)

    def field(self, label, default="", choices=None, secret=False):
        row = self.form.grid_size()[1]
        ttk.Label(self.form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
        var = tk.StringVar(value=default)
        widget = (ttk.Entry(self.form, textvariable=var, show="*" if secret else "")
                  if choices is None else ttk.Combobox(self.form, textvariable=var, values=choices))
        widget.grid(row=row, column=1, sticky="ew")
        self.inputs.append(widget)
        return var

    def button(self, label, action, inline=False, main=False):
        row = self.form.grid_size()[1] - int(inline)
        b = ttk.Button(self.form, text=label, command=action, style="Play.TButton" if main else "TButton")
        b.grid(row=row, column=2 if inline else 0, columnspan=1 if inline else 3, sticky="ew", pady=3)
        self.buttons.append(b)

    def job(self, title, action, done=None):
        if self.busy:
            return
        self.busy = True
        self.status.set(title)
        for b in self.buttons + self.inputs:
            b.state(["disabled"])
        def run():
            try:
                self.events.put(("done", (action(), done)))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def progress(self, line):
        self.events.put(("status", line))

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "status":
                self.status.set(value)
                continue
            self.busy = False
            for b in self.buttons + self.inputs:
                b.state(["!disabled"])
            if kind == "error":
                self.status.set("Action needs attention: " + value[:100])
                messagebox.showerror("NFS13", value[-1800:])
            else:
                result, done = value
                self.status.set("Ready")
                if done:
                    done(result)
        self.root.after(80, self.poll)
