# SPDX-License-Identifier: AGPL-3.0-only
"""Host-only player administration, called exclusively from loopback HTTP."""
import json
import re
import time
from urllib.parse import parse_qs, urlsplit
from dataclasses import replace


def snapshot(registry):
    folder = registry.path.parent / "backups"
    folder.mkdir(exist_ok=True)
    if registry.path.exists():
        (folder / f"players-{time.time_ns()}.json").write_bytes(registry.path.read_bytes())


def player_record(profile, registry, sessions, plates, include_secret=False):
    stats = dict(registry.stats(profile.persona_id))
    record = {"persona_id": profile.persona_id, "account_id": profile.account_id,
              "name": profile.name, "stats": stats,
              "xp_known": "updated_at" in stats, "online": profile.persona_id in sessions,
              "plate": plates.get(profile.persona_id)}
    if include_secret:
        record["credential_hash"] = registry._credentials.get(str(profile.persona_id))
    return record


def dispatch(method, target, raw, registry, sessions, plates):
    parsed = urlsplit(target)
    query = parse_qs(parsed.query)
    if method == "GET" and parsed.path == "/admin/players":
        return {"status": "ok", "players": [player_record(p, registry, sessions, plates)
                                               for p in registry.all_profiles()]}
    if method == "GET" and parsed.path == "/admin/player/export":
        profile = registry._profiles.get(int(query.get("id", ["0"])[0]))
        if profile is None:
            raise ValueError("Player not found")
        return {"format": "nfs13-player-1", "exported_at": int(time.time()),
                "player": player_record(profile, registry, sessions, plates, True)}
    if method != "POST" or parsed.path not in ("/admin/player", "/admin/player/import"):
        raise ValueError("Unknown admin action")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    if parsed.path.endswith("/import"):
        if data.get("format") != "nfs13-player-1":
            raise ValueError("Unsupported player backup")
        record = data["player"]
        persona_id = record["persona_id"]
        name = record["name"]
        if type(persona_id) is not int or not 1000001 <= persona_id <= 0x7fffffff:
            raise ValueError("Invalid persona ID")
        _validate_name(name)
        existing = registry._profiles.get(persona_id)
        if existing and existing.name.casefold() != name.casefold():
            raise ValueError("That persona ID already belongs to another player")
        if any(p.name.casefold() == name.casefold() and p.persona_id != persona_id
               for p in registry.all_profiles()):
            raise ValueError("That name already belongs to another persona")
        if persona_id in sessions:
            raise ValueError("Disconnect the player before restoring their data")
        stats = record.get("stats", {})
        _validate_stats(stats)
        secret = record.get("credential_hash")
        if secret is not None and (not isinstance(secret, str) or not re.fullmatch(r"[a-f0-9]{64}", secret)):
            raise ValueError("Invalid credential hash")
        plate = _validate_plate(record.get("plate"))
        snapshot(registry)
        # Preserve a portable persona ID without relying on its original network address.
        if existing is None:
            # The registry's existing profile type is supplied by its normal allocator.
            created = registry._new_profile("", name)
            registry._profiles.pop(created.persona_id)
            existing = replace(created, persona_id=persona_id, account_id=persona_id)
        registry._profiles[persona_id] = replace(existing, name=name)
        registry._stats[str(persona_id)] = dict(stats)
        if secret:
            registry._credentials[str(persona_id)] = secret
        registry._save()
        if plate:
            plates.set(persona_id, *plate)
        return {"status": "ok", "message": "Player data restored"}

    persona_id = data.get("persona_id")
    if type(persona_id) is not int or persona_id not in registry._profiles:
        raise ValueError("Player not found")
    profile = registry._profiles[persona_id]
    action = data.get("action")
    if action == "kick":
        if persona_id in sessions:
            sessions[persona_id].writer.close()
        return {"status": "ok", "message": "Player disconnected"}
    if action != "update":
        raise ValueError("Unknown player action")
    allowed = {"persona_id", "action", "name", "xp", "disabled", "dlc_compatibility"}
    if set(data) - allowed:
        raise ValueError("Unexpected player field")
    name = data.get("name", profile.name)
    _validate_name(name)
    if any(p.name.casefold() == name.casefold() and p.persona_id != persona_id for p in registry.all_profiles()):
        raise ValueError("Name is already in use")
    stats = dict(registry.stats(persona_id))
    for key in ("xp", "disabled", "dlc_compatibility"):
        if key in data:
            stats[key] = data[key]
    _validate_stats(stats)
    if "xp" in data:
        stats["updated_at"] = int(time.time())
    snapshot(registry)
    registry._profiles[persona_id] = replace(profile, name=name)
    registry._stats[str(persona_id)] = stats
    registry._save()
    if persona_id in sessions:
        sessions[persona_id].writer.close()
    return {"status": "ok", "message": "Player updated; changes apply on next login"}


def _validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", name):
        raise ValueError("Names use 1-15 letters, digits, _ or -")


def _validate_stats(stats):
    if not isinstance(stats, dict) or type(stats.get("xp", 0)) is not int or not 0 <= stats.get("xp", 0) <= 0x7fffffff:
        raise ValueError("Invalid XP total")
    for key in ("disabled", "dlc_compatibility"):
        if key in stats and type(stats[key]) is not bool:
            raise ValueError(f"Invalid {key} value")
    allowed = {"xp", "level", "updated_at", "vehicle_id", "disabled", "dlc_compatibility"}
    if set(stats) - allowed:
        raise ValueError("Unexpected saved player field")
    for key in ("level", "updated_at", "vehicle_id"):
        if key in stats and (type(stats[key]) is not int or stats[key] < 0 or stats[key] > 0x7fffffffffffffff):
            raise ValueError(f"Invalid {key}")


def _validate_plate(plate):
    if plate is None:
        return None
    if (not isinstance(plate, (list, tuple)) or len(plate) != 2 or type(plate[0]) is not int
            or not 0 <= plate[0] <= 0x7fffffff or not isinstance(plate[1], str)
            or not re.fullmatch(r"[A-Za-z0-9 _-]{1,16}", plate[1])):
        raise ValueError("Invalid saved license plate")
    return plate
