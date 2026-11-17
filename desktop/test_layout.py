# SPDX-License-Identifier: AGPL-3.0-only
"""Check admin widget geometry at several window sizes, using this PC's DPI."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tkinter import ttk

import host
from ui import tk
from admin_layout import Page, ButtonRow


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class AdminLayoutTests(unittest.TestCase):
    def test_all_tabs_keep_controls_and_labels_whole(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(host, "DATA", Path(directory)), \
                patch.object(host, "run", return_value=b"ExampleProfile\n"), patch.object(tk.Tk, "mainloop"):
            win = host.main()
            try:
                win.root.minsize(0, 0)
                tabs = next(w for w in descendants(win.root) if isinstance(w, ttk.Notebook))
                for width, height in ((1100, 800), (920, 690), (760, 520)):
                    win.root.geometry(f"{width}x{height}+2000+2000")
                    for tab in tabs.tabs():
                        tabs.select(tab)
                        for _ in range(5):
                            win.root.update_idletasks(); win.root.update()
                        page = win.root.nametowidget(tab)
                        self.assertIsInstance(page, Page)
                        if tabs.tab(tab, "text") == "Host new server":
                            changed = False
                            for widget in descendants(page.body):
                                if isinstance(widget, ttk.Label) and str(widget.cget("textvariable")):
                                    win.root.setvar(str(widget.cget("textvariable")), "Account access verified. " * 30)
                                    changed = True
                            self.assertTrue(changed, "Exercise the changing region status message")
                            for _ in range(3): win.root.update()
                        for widget in descendants(page.body):
                            if not isinstance(widget, (ttk.Label, ttk.Button, ttk.Checkbutton)):
                                continue
                            with self.subTest(size=(width, height), tab=tabs.tab(tab, "text"), text=widget.cget("text")):
                                self.assertGreaterEqual(widget.winfo_height() + 1, widget.winfo_reqheight(), "Text/button is vertically clipped")
                                self.assertGreaterEqual(widget.winfo_width() + 1, widget.winfo_reqwidth(),
                                    f"Text/button is horizontally clipped: wrap={widget.cget('wraplength') if isinstance(widget,ttk.Label) else '-'} parent={widget.master.winfo_width()} body={page.body.winfo_width()} canvas={page.canvas.winfo_width()} pending={page.pending}")
                                self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), widget.master.winfo_width() + 1)
                                self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), widget.master.winfo_height() + 1)
                        # Last actions remain reachable, even when the page needs scrolling.
                        buttons = [w for w in descendants(page.body) if isinstance(w, ttk.Button)]
                        if buttons:
                            page.reveal(buttons[-1]); win.root.update_idletasks()
                            bottom = buttons[-1].winfo_rooty() + buttons[-1].winfo_height()
                            self.assertLessEqual(bottom, page.canvas.winfo_rooty() + page.canvas.winfo_height() + 1,
                                                 f"Last action unreachable: {width}x{height} {tabs.tab(tab, 'text')}")
            finally:
                win.root.destroy()


if __name__ == "__main__": unittest.main()
