# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import server
import admin_api
import cloud
import local_data


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = server.PlayerRegistry(self.root / "players.json")
        self.plates = server.LicensePlateStore(self.root / "plates.json")
        self.player, self.ticket = self.registry.login("Alex", "a" * 64)

    def call(self, method, path, data=None):
        return admin_api.dispatch(method, path, json.dumps(data).encode(), self.registry, {}, self.plates)

    def test_export_restore_preserves_persona_credentials_and_stats(self):
        pid = self.player.persona_id
        self.registry.record_xp(pid, 76500)
        self.plates.set(pid, 123, "RACER")
        exported = self.call("GET", f"/admin/player/export?id={pid}")
        target = server.PlayerRegistry(self.root / "restored.json")
        admin_api.dispatch("POST", "/admin/player/import", json.dumps(exported).encode(), target, {}, self.plates)
        self.assertEqual(target.login("Alex", "a" * 64)[0].persona_id, pid)
        self.assertEqual(target.stats(pid)["xp"], 76500)
        listed = self.call("GET", "/admin/players")["players"][0]
        self.assertNotIn("credential_hash", listed)

    def test_edits_backup_and_disable_all_existing_tickets(self):
        pid = self.player.persona_id
        self.call("POST", "/admin/player", {"action": "update", "persona_id": pid, "xp": 71000, "disabled": True})
        self.assertEqual(self.registry.stats(pid)["xp"], 71000)
        self.assertTrue(list((self.root / "backups").glob("*.json")))
        self.assertIsNone(self.registry.from_ticket(self.ticket))
        with self.assertRaises(ValueError): self.registry.login("Alex", "a" * 64)

    def test_invalid_edit_changes_nothing(self):
        before = self.registry.path.read_bytes()
        for value in (-1, True, "100", 2**40):
            with self.assertRaises(ValueError):
                self.call("POST", "/admin/player", {"action": "update", "persona_id": self.player.persona_id, "xp": value})
        self.assertEqual(self.registry.path.read_bytes(), before)

    def test_name_change_keeps_credential_and_persona(self):
        renamed, _ = self.registry.login("Racer", "a" * 64)
        self.assertEqual(renamed.persona_id, self.player.persona_id)
        self.assertEqual(renamed.name, "Racer")

    def test_public_admin_calls_are_rejected(self):
        class Writer:
            def __init__(self): self.output = bytearray()
            def get_extra_info(self, name): return ("203.0.113.9", 1)
            def write(self, data): self.output.extend(data)
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): pass
        async def request():
            reader = asyncio.StreamReader(); reader.feed_data(b"GET /admin/players HTTP/1.1\r\nHost: t\r\n\r\n")
            writer = Writer()
            await server.handle_autolog_http(reader, writer)
            return writer.output
        self.assertIn(b"local access only", asyncio.run(request()))


class HostTests(unittest.TestCase):
    def test_archive_rejects_unsafe_and_duplicate_paths(self):
        for names in (("../players.json",), ("players.json", "players.json")):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                for name in names:
                    item = tarfile.TarInfo(name); item.size = 2
                    archive.addfile(item, io.BytesIO(b"{}"))
            with self.assertRaises(ValueError): cloud.validate_archive(raw.getvalue())

    def test_terminate_does_not_delete_after_failed_backup(self):
        c = cloud.Cloud("test", "us-east-1", "race-server", "")
        c.save = Mock(side_effect=ValueError("bad backup")); c.aws = Mock()
        with self.assertRaises(ValueError): c.terminate("data.tar.gz")
        c.aws.assert_not_called()

    def test_server_bundle_has_admin_and_installer_with_unix_newlines(self):
        with tarfile.open(fileobj=io.BytesIO(cloud.server_bundle()), mode="r:gz") as archive:
            self.assertIn("server/admin_api.py", archive.getnames())
            self.assertIn("desktop/provision.sh", archive.getnames())
            for entry in archive:
                self.assertNotIn(b"\r\n", archive.extractfile(entry).read())

    def test_career_restore_rejects_directory_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "career.zip"
            with zipfile.ZipFile(archive, "w") as output: output.writestr("../bad.NFS13Save", b"x")
            with patch.object(local_data, "game_closed"), self.assertRaises(ValueError):
                local_data.restore_saves(archive)


if __name__ == "__main__": unittest.main()
