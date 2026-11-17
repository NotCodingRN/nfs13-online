# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import build
import cloud
import sharing


class SharingTests(unittest.TestCase):
    def test_pack_contains_editable_default_and_no_private_host_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            template = root / "template.zip"
            with zipfile.ZipFile(template, "w") as archive:
                for name in ("NFS13Player.exe", "Start here.txt", "source/LICENSE", "host.json", "key.pem", "identities.json"):
                    archive.writestr(name, b"example")
            output = sharing.player_pack("192.168.1.50", root / "players.zip", template)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(json.loads(archive.read("server.json")), {"server_ip":"192.168.1.50"})
                self.assertEqual(set(archive.namelist()), {"NFS13Player.exe", "Start here.txt", "source/LICENSE", "server.json", "Connect.txt"})
                (root / "server.json").write_bytes(archive.read("server.json"))
            self.assertEqual(sharing.player_defaults(root / "server.json"), "192.168.1.50")

    def test_new_distribution_changes_default_but_preserves_players_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sharing, "DATA", Path(folder)), \
                patch.object(sharing, "player_defaults", return_value="192.168.1.50"):
            root = Path(folder)
            (root / "player.json").write_text(json.dumps(["game", "Racer", "192.168.1.20"]))
            self.assertEqual(sharing.load_preferences(), ("game", "Racer", "192.168.1.50"))
            sharing.preferences_path().write_text(json.dumps(["game", "Racer", "192.168.1.60"]))
            self.assertEqual(sharing.load_preferences(), ["game", "Racer", "192.168.1.60"])

    def test_source_bundle_excludes_runtime_secrets(self):
        names = [p.relative_to(build.ROOT).as_posix() for p in build.source_files()]
        self.assertIn("desktop/sharing.py", names)
        self.assertIn("AUTHORS", names)
        self.assertIn("server/admin_api.py", names)
        self.assertNotIn("HANDOFF.md", names)
        self.assertEqual([n for n in names if n.endswith(".json")], ["client/patches/nfs13_online.json", "server/friends.json"])


class HostingTests(unittest.TestCase):
    def test_create_saves_key_before_launch_and_checks_readiness(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cloud, "DATA", Path(folder)), patch.object(cloud, "run", return_value=b"testuser"):
            c = cloud.Cloud("chosen-profile", "eu-west-1", "race-server", "")
            c.preflight = Mock(return_value={"bundles":[{"bundleId":"small_3_0"}],"instances":[],"zones":["eu-west-1a"],"blueprint":"ubuntu_24_04"})
            c.instance = Mock(return_value={"state":{"name":"running"},"publicIpAddress":"192.168.1.50"})
            def aws(*args):
                if args[1] == "create-key-pair": return {"privateKeyBase64":"private-test-key"}
                if args[1] == "create-instances":
                    record = json.loads((Path(folder)/"race-server-deployment.json").read_bytes())
                    self.assertEqual(Path(record["key"]).read_text(), "private-test-key")
                return {}
            c.aws = Mock(side_effect=aws)
            c.provision = Mock(); c.verify_ready = Mock()
            record = c.create("small_3_0", Mock())
            self.assertEqual(record["ip"], "192.168.1.50")
            self.assertEqual(record["profile"], "chosen-profile")
            c.provision.assert_called_once(); c.verify_ready.assert_called_once()
            self.assertNotIn("restore_file", record)

    def test_resume_loads_saved_key_and_returns_complete_deployment(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(cloud, "DATA", Path(folder)):
            record={"profile":"chosen-profile","region":"eu-west-1","instance":"race-server","key":"saved-key.pem"}
            (Path(folder)/"race-server-deployment.json").write_text(json.dumps(record))
            c=cloud.Cloud("chosen-profile","eu-west-1","race-server","")
            c.instance=Mock(return_value={"publicIpAddress":"192.168.1.50","tags":[{"key":"ManagedBy","value":"NFS13Desktop"}]})
            c.aws=Mock(return_value={"staticIps":[{"name":"race-server-ip","attachedTo":"race-server","isAttached":True}]})
            c.provision=Mock();c.verify_ready=Mock()
            self.assertEqual(c.resume(Mock())["ip"],"192.168.1.50")
            self.assertEqual(c.key,"saved-key.pem")
            c.verify_ready.assert_called_once()

    def test_delete_waits_for_detach_and_releases_old_ip_names(self):
        c=cloud.Cloud("chosen-profile","eu-west-1","race-server","")
        c.save=Mock()
        address={"name":"legacy-ip","attachedTo":"race-server","isAttached":True}
        c.aws=Mock(side_effect=[{"staticIps":[address]}, {}, {"staticIps":[address]}, {"staticIps":[dict(address,isAttached=False)]}, {}])
        with patch.object(cloud.time,"sleep"):
            c.terminate("backup.tar.gz")
        self.assertEqual(c.aws.call_args.args,("lightsail","release-static-ip","--static-ip-name","legacy-ip"))

    def test_readiness_rejects_public_endpoint_with_wrong_identity_protocol(self):
        c=cloud.Cloud("chosen-profile","eu-west-1","race-server","")
        c.ssh=Mock();c.instance=Mock(return_value={"publicIpAddress":"192.168.1.50"})
        response=Mock();response.__enter__=Mock(return_value=io.BytesIO(b'{"serverActive":true}'));response.__exit__=Mock()
        with patch.object(cloud.urllib.request,"build_opener") as opener:
            opener.return_value.open.return_value=response
            with self.assertRaises(ValueError):c.verify_ready(Mock())


if __name__ == "__main__": unittest.main()
