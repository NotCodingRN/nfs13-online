# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class TicketIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "players.json"
        self.registry = server.PlayerRegistry(self.path)

    def test_names_keep_ids_across_restart_and_address_changes(self):
        alex, a = self.registry.login("Alex", "a" * 64)
        bob, b = self.registry.login("Bob", "b" * 64)
        self.assertNotEqual(alex.persona_id, bob.persona_id)
        self.assertEqual(self.registry.from_ticket(a), alex)
        self.assertEqual(self.registry.from_ticket(b), bob)
        fresh = server.PlayerRegistry(self.path)
        self.assertEqual(fresh.login("Alex", "a" * 64)[0].persona_id, alex.persona_id)
        with self.assertRaises(ValueError):
            fresh.login("Alex", "b" * 64)
        self.assertIsNone(fresh.from_ticket("invalid"))

    def test_two_simultaneous_logins_share_an_ip_without_sharing_a_persona(self):
        alex, a = self.registry.login("Alex", "a" * 64)
        bob, b = self.registry.login("Bob", "b" * 64)
        class Writer:
            def __init__(self): self.frames = []
            def write(self, data): self.frames.append(data)
            async def drain(self): pass
        async def login(ticket):
            writer = Writer()
            session = server.ClientSession(writer, ("127.0.0.1", 1), ("203.0.113.9", 1000),
                                           server.PlayerProfile(0, 0, "PendingLogin", ""))
            await server.handle_auth_request(session, 0x0032, 1,
                                            server.tdf_string_field("AUTH", ticket), session.client_peer)
            return session
        async def both(): return await asyncio.gather(login(a), login(b))
        with patch.object(server, "PLAYER_REGISTRY", self.registry), patch.dict(server.ACTIVE_SESSIONS, {}, clear=True):
            sessions = asyncio.run(both())
            self.assertEqual({s.profile.persona_id for s in sessions}, {alex.persona_id, bob.persona_id})
            self.assertEqual(len(server.ACTIVE_SESSIONS), 2)
            self.assertTrue(all(s.authenticated for s in sessions))

    def test_autolog_accepts_the_blaze_login_session_key(self):
        alex, ticket = self.registry.login("Alex", "a" * 64)
        class Writer:
            def __init__(self): self.frames = []
            def write(self, data): self.frames.append(bytes(data))
            async def drain(self): pass
            def get_extra_info(self, name): return ("203.0.113.9", 1)
            def close(self): pass
            async def wait_closed(self): pass
        async def login():
            writer = Writer()
            session = server.ClientSession(writer, ("127.0.0.1", 1), ("203.0.113.9", 1000),
                                           server.PlayerProfile(0, 0, "PendingLogin", ""))
            await server.handle_auth_request(session, 0x0032, 1,
                                            server.tdf_string_field("AUTH", ticket), session.client_peer)
            return b"".join(writer.frames)
        async def autolog(key):
            reader = asyncio.StreamReader()
            reader.feed_data(f"GET /view_model?session={key}&getComponent=MainMap&action=GetData HTTP/1.1\r\n\r\n".encode())
            writer = Writer()
            await server.handle_autolog_http(reader, writer)
            return b"".join(writer.frames)
        with patch.object(server, "PLAYER_REGISTRY", self.registry), patch.dict(server.ACTIVE_SESSIONS, {}, clear=True):
            frames = asyncio.run(login())
            key = next(k for k in self.registry._tickets if k != ticket)
            self.assertIn(key.encode(), frames)  # the key the game was given
            with self.assertLogs(server.log, "INFO") as logs:
                accepted = asyncio.run(autolog(key))
                refused = asyncio.run(autolog("0" * 32))
        self.assertIn(b"HasRecommendations", accepted)
        self.assertIn(b"Invalid or expired launcher ticket", refused)
        self.assertTrue(any("'session': 'known'" in line for line in logs.output))
        self.assertTrue(any("refused GET /view_model" in line for line in logs.output))
        self.assertFalse(any(key in line or ticket in line for line in logs.output))

    def test_xp_report_saves_only_the_authenticated_players_total(self):
        alex, _ = self.registry.login("Alex", "a" * 64)
        bob, _ = self.registry.login("Bob", "b" * 64)
        # Legacy clients can report entity 1; the authenticated connection owns the report.
        def report(value):
            return (server.encode_tag("STAT", 5) + b"\0\3" + server.tdf_varint(1) +
                    server.tdf_varint(1) + server.tdf_int_field("XP", value) + b"\0" +
                    server.tdf_string_field("GTYP", "OnlineEventFreedrive"))
        xp = server.parse_player_xp_report(report(91000))
        self.assertEqual(xp, 91000)
        self.assertIsNone(server.parse_player_xp_report(report(91000)[:-1]))
        self.registry.record_xp(alex.persona_id, xp)
        self.registry.record_xp(alex.persona_id, 1)
        fresh = server.PlayerRegistry(self.path)
        self.assertEqual(fresh.stats(alex.persona_id)["xp"], 91000)
        self.assertEqual(fresh.stats(bob.persona_id)["xp"], 0)
        with patch.object(server, "PLAYER_REGISTRY", fresh):
            self.assertEqual(json.loads(server.make_most_wanted_list_body(alex))["LocalUserPoints"], 91000)
