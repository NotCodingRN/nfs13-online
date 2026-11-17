# SPDX-License-Identifier: AGPL-3.0-only
"""Check admin widget geometry at several window sizes, using this PC's DPI."""
import tempfile
import time
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
            win = host.main(auto_setup=False)
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


class WizardTests(unittest.TestCase):
    def test_wizard_walks_every_step_without_clipping(self):
        import wizard
        preflight = {"account": "123456789012", "region": "eu-central-1", "instances": [],
                     "bundles": [{"ramSizeInGb": 1, "cpuCount": 2, "price": 7, "bundleId": "micro_3_0"},
                                 {"ramSizeInGb": 2, "cpuCount": 2, "price": 12, "bundleId": "small_3_0"}]}
        record = {"profile": "AWS-YVL", "region": "eu-central-1", "instance": "fairhaven-racing",
                  "key": "k.pem", "ip": "203.0.113.7"}
        def fake_run(args, data=None, timeout=60):
            if "--version" in args: return b"aws-cli/2.31.0 Python/3.13"
            if "list-profiles" in args: return b"AWS-YVL\r\nAWS-UNI\r\n"
            if "get-caller-identity" in args: return b'{"Arn": "arn:aws:iam::123456789012:user/host"}'
            raise AssertionError(args)
        done = []
        with tempfile.TemporaryDirectory() as directory, patch.object(wizard, "DATA", Path(directory)), \
                patch.object(wizard, "run", fake_run), patch.object(wizard, "aws_executable", return_value="aws"), \
                patch.object(wizard.shutil, "which", return_value="ssh"), \
                patch.object(wizard.Cloud, "preflight", return_value=preflight), \
                patch.object(wizard.Cloud, "create", return_value=record), \
                patch.object(wizard, "player_pack", side_effect=lambda ip, path: path):
            root = tk.Tk(); root.withdraw()
            try:
                w = wizard.Wizard(root, {"profile": "AWS-YVL", "region": "eu-central-1"},
                                  lambda r, p: done.append((r, p)))
                def settle():
                    for _ in range(40):
                        root.update(); time.sleep(0.01)
                        if not w.busy and w.events.empty(): break
                    for _ in range(3): root.update()
                def check_page():
                    for width, height in ((900, 620), (760, 540)):
                        w.top.geometry(f"{width}x{height}"); settle()
                        for widget in descendants(w.top):
                            if isinstance(widget, (ttk.Label, ttk.Button)) and widget.winfo_ismapped():
                                with self.subTest(step=w.step, size=width, text=str(widget.cget("text"))[:40]):
                                    self.assertGreaterEqual(widget.winfo_width() + 1, widget.winfo_reqwidth())
                                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                                         w.top.winfo_rootx() + w.top.winfo_width() + 1)
                                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                                         w.top.winfo_rooty() + w.top.winfo_height() + 1)
                settle(); self.assertEqual(w.step, 0); check_page()
                self.assertIn("installed", w.message.get())
                w.next.invoke(); settle(); self.assertEqual(w.step, 1)
                self.assertIn("2 AWS profiles", w.message.get()); check_page()
                w.next.invoke(); settle(); time.sleep(0.8); settle()
                self.assertEqual(w.step, 2); self.assertEqual(w.profile, "AWS-YVL"); check_page()
                w.next.invoke(); settle()  # check region
                self.assertIn("ready", w.message.get())
                w.next.invoke(); settle(); self.assertEqual(w.step, 3)
                self.assertEqual(w.choice["bundle"], "small_3_0"); check_page()
                w.next.invoke(); settle(); settle()  # create, then player ZIP
                self.assertEqual(w.step, 4); check_page()
                w.next.invoke(); root.update()
                self.assertEqual(done[0][0]["ip"], "203.0.113.7")
            finally:
                root.destroy()

    def test_new_keys_are_saved_without_touching_other_profiles(self):
        import wizard
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials"
            path.write_text("[AWS-YVL]\naws_access_key_id = AKIAOLDOLDOLDOLDOLD1\naws_secret_access_key = x\n")
            with patch.dict("os.environ", {"AWS_SHARED_CREDENTIALS_FILE": str(path)}):
                wizard.save_keys("nfs13", "AKIA" + "A" * 16, "s" * 40)
                with self.assertRaises(ValueError): wizard.save_keys("nfs13", "bad", "s" * 40)
            text = path.read_text()
            self.assertIn("[AWS-YVL]", text); self.assertIn("AKIAOLDOLDOLDOLDOLD1", text)
            self.assertIn("[nfs13]", text); self.assertIn("AKIA" + "A" * 16, text)


if __name__ == "__main__": unittest.main()
