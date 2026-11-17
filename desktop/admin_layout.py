# SPDX-License-Identifier: AGPL-3.0-only
"""Responsive containers for the admin panel, including high-DPI displays."""
import ctypes
import os
from tkinter import ttk
from ui import tk


def fit_window(root, width=1100, height=800):
    available_width, available_height = root.winfo_screenwidth(), root.winfo_screenheight() - 60
    if os.name == "nt":
        from ctypes import wintypes
        area = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):
            available_width = area.right - area.left
            available_height = area.bottom - area.top
    width, height = min(width, available_width - 20), min(height, available_height - 30)
    root.minsize(min(760, width), min(480, height))
    root.geometry(f"{width}x{height}")


class ButtonRow(ttk.Frame):
    """Wrap complete buttons to another row instead of clipping their labels."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.items = []
        self.bind("<Configure>", lambda _: self.reflow())

    def add(self, widget):
        self.items.append(widget)
        widget.grid(row=0, column=len(self.items) - 1, padx=(0, 7), pady=5, sticky="w")
        self.after_idle(self.reflow)

    def reflow(self):
        width = self.winfo_width()
        if width < 10:
            return
        row = col = used = 0
        for widget in self.items:
            wanted = widget.winfo_reqwidth() + 7
            if used and used + wanted > width:
                row += 1; col = used = 0
            widget.grid_configure(row=row, column=col)
            used += wanted; col += 1


class Page(ttk.Frame):
    """Keep the tab's requested content height and scroll when space is short."""
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background="#101316", highlightthickness=0, width=100, height=220)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.body = ttk.Frame(self.canvas, padding=14)
        self.body.page = self
        self.window_id = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.pending = None
        self.laying_out = False
        self.body.bind("<Configure>", lambda _: self.queue_layout())
        self.canvas.bind("<Configure>", lambda _: self.queue_layout())
        self.bind("<Map>", lambda _: self.queue_layout())
        self.bind_all("<MouseWheel>", self.wheel, add="+")
        self.bind_all("<FocusIn>", self.reveal_focus, add="+")
        self.bind_all("<Configure>", self.content_changed, add="+")

    def content_changed(self, event):
        if self.winfo_ismapped() and self.owns(event.widget):
            self.queue_layout()

    def queue_layout(self):
        if self.pending is None and not self.laying_out:
            self.pending = self.after_idle(self.layout)

    def layout(self):
        self.pending = None
        if not self.winfo_ismapped():
            return
        self.laying_out = True
        width = max(1, self.canvas.winfo_width())
        self.canvas.itemconfigure(self.window_id, width=width)
        self.body.update_idletasks()
        wrap_labels(self.body)
        self.body.update_idletasks()
        height = max(self.body.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window_id, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.laying_out = False

    def owns(self, widget):
        while widget:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def wheel(self, event):
        if not self.winfo_ismapped():
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        if self.owns(widget) and widget.winfo_class() not in ("Text", "Listbox", "Treeview", "TCombobox"):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def reveal_focus(self, event):
        if not self.winfo_ismapped() or not self.owns(event.widget):
            return
        self.after_idle(lambda: self.reveal(event.widget))

    def reveal(self, widget):
        if not widget.winfo_exists():
            return
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        start = self.canvas.canvasy(0)
        end = start + self.canvas.winfo_height()
        total = max(1, self.body.winfo_height())
        if top < start:
            self.canvas.yview_moveto(max(0, top - 8) / total)
        elif top + widget.winfo_height() > end:
            self.canvas.yview_moveto((top + widget.winfo_height() - self.canvas.winfo_height() + 8) / total)


def wrap_labels(parent):
    for widget in parent.winfo_children():
        if isinstance(widget, ttk.Label):
            if int(float(widget.cget("wraplength") or 0)) > 0 or str(widget.cget("style")) in ("Title.TLabel", "Stat.TLabel"):
                width = max(160, widget.master.winfo_width() - 60)
                if int(float(widget.cget("wraplength") or 0)) != width:
                    widget.configure(wraplength=width, justify="left", anchor="w")
        elif isinstance(widget, ttk.Frame) and not isinstance(widget, Page):
            wrap_labels(widget)


def scroll_table(tree, parent):
    tree.grid(row=0, column=0, sticky="nsew")
    parent.rowconfigure(0, weight=1); parent.columnconfigure(0, weight=1)
    vertical = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
