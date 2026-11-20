# SPDX-License-Identifier: AGPL-3.0-only
import ipaddress
import json
import subprocess
import tarfile
import io
import time
import urllib.request
import re
import secrets
import base64
import shutil
import tempfile
import os
from pathlib import Path

from ui import DATA, ROOT

DATA_FILES = {"players.json", "license_plates.json", "friends.json", "accounts.json"}
# Blaze, HTTPS, Autolog, QoS, and the UDP relay range in server.RELAY_PORTS.
GAME_PORTS = [{"fromPort": first, "toPort": last, "protocol": protocol, "cidrs": ["0.0.0.0/0"]}
              for first, last, protocol in ((42127, 42127, "tcp"), (44125, 44125, "tcp"), (8080, 8080, "tcp"),
                                            (17500, 17500, "tcp"), (17500, 17500, "udp"), (3700, 3899, "udp"))]


def aws_executable():
    candidates = [shutil.which("aws"), str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs/Amazon/AWSCLIV2/aws.exe"),
                  str(Path(os.getenv("ProgramFiles", "C:/Program Files")) / "Amazon/AWSCLIV2/aws.exe")]
    found = next((p for p in candidates if p and Path(p).is_file()), None)
    if not found:
        raise ValueError("AWS CLI is missing. Install the Host tools component from Setup, then configure an AWS profile")
    return found


def run(args, data=None, timeout=60):
    args = list(args)
    if args[0] == "aws":
        args[0] = aws_executable()
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", AWS_CLI_OUTPUT_ENCODING="UTF-8", AWS_PAGER="")
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout, env=environment,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        message = (result.stderr or result.stdout).decode("utf-8", "replace")
        raise RuntimeError(message[-1800:] or f"{args[0]} failed")
    return result.stdout


class Cloud:
    def __init__(self, profile, region, instance, key):
        if not profile or profile.startswith("-"):
            raise ValueError("Choose an AWS CLI profile.")
        if not instance or instance.startswith("-"):
            raise ValueError("Enter the Lightsail instance name.")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d+", region):
            raise ValueError("Choose a valid AWS region")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,62}", instance):
            raise ValueError("Instance names start with a letter and use letters, digits, _ or -")
        self.cli = ["aws", "--profile", profile, "--region", region,
                    "--no-cli-pager", "--output", "json"]
        self.instance_name = instance
        self.profile, self.region = profile, region
        self.key = str(Path(key).resolve()) if key else ""
        self.known_hosts = str(DATA / "known_hosts").replace("\\", "/")

    def aws(self, *args):
        raw = run(self.cli + list(args))
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except UnicodeDecodeError:
            return json.loads(raw.decode("cp1252"))

    def instance(self):
        return self.aws("lightsail", "get-instance", "--instance-name", self.instance_name)["instance"]

    def ssh(self, command, data=None, timeout=60):
        if not self.key or not Path(self.key).is_file():
            raise ValueError("Choose the SSH private key for this Lightsail instance")
        DATA.mkdir(parents=True, exist_ok=True)
        host = str(ipaddress.IPv4Address(self.instance()["publicIpAddress"]))
        admin_ip = urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()
        cidr = str(ipaddress.IPv4Address(admin_ip)) + "/32"
        port = {"fromPort": 22, "toPort": 22, "protocol": "tcp", "cidrs": [cidr]}
        states = self.aws("lightsail", "get-instance-port-states", "--instance-name", self.instance_name).get("portStates", [])
        already_allowed = any(
            item.get("state") == "open" and item.get("protocol") == "tcp"
            and item.get("fromPort", 0) <= 22 <= item.get("toPort", -1)
            and (not item.get("cidrs") or any(
                ipaddress.IPv4Address(admin_ip) in ipaddress.ip_network(rule, strict=False)
                for rule in item["cidrs"] if ":" not in rule and ("/" in rule or rule.count(".") == 3)))
            for item in states
        )
        opened_here = not already_allowed
        if opened_here:
            self.aws("lightsail", "open-instance-public-ports", "--instance-name", self.instance_name,
                     "--port-info", json.dumps(port, separators=(",", ":")))
            time.sleep(3)
        try:
            args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                    "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "UserKnownHostsFile=" + self.known_hosts,
                    "-i", self.key, "ubuntu@" + host, command]
            last_error = None
            for attempt in range(3):
                try:
                    return run(args, data, timeout)
                except RuntimeError as exc:
                    last_error = exc
                    if not any(message in str(exc).lower() for message in
                               ("connection refused", "connection timed out", "connection reset by")):
                        raise
                    if attempt < 2:
                        time.sleep(2)
            raise last_error
        finally:
            if opened_here:
                self.aws("lightsail", "close-instance-public-ports", "--instance-name", self.instance_name,
                         "--port-info", json.dumps(port, separators=(",", ":")))

    def status(self):
        instance = self.instance()
        state = instance.get("state", {}).get("name", "unknown")
        report = {"state": state, "ip": instance.get("publicIpAddress", ""),
                  "plan": instance.get("bundleId", "unknown"), "players": [], "games": []}
        if state == "running":
            try:
                raw = self.ssh("curl -fsS --max-time 5 http://127.0.0.1:8080/admin/status").decode()
                report.update(json.loads(raw))
                report["service"] = "online"
            except Exception as exc:
                report["service"] = "unreachable"
                report["detail"] = str(exc)[-500:]
        else:
            report["service"] = "stopped"
        return report

    def control(self, action):
        instance = self.instance()
        state = instance.get("state", {}).get("name", "")
        if action in ("start", "stop", "reboot"):
            if action == "start" and state != "running":
                self.aws("lightsail", "start-instance", "--instance-name", self.instance_name)
            elif action == "stop" and state == "running":
                self.aws("lightsail", "stop-instance", "--instance-name", self.instance_name)
            elif action == "reboot" and state == "running":
                self.aws("lightsail", "reboot-instance", "--instance-name", self.instance_name)
            return action + " requested"
        if state != "running":
            raise ValueError("Start the Lightsail instance before managing its game service.")
        if action == "restart-service":
            self.ssh("systemctl --user restart nfs13-server.service")
            return "Game server restarted"
        if action == "service-stop":
            self.ssh("systemctl --user stop nfs13-server.service")
            return "Game server stopped"
        if action == "service-start":
            self.ssh("systemctl --user start nfs13-server.service")
            return "Game server started"
        raise ValueError("Unknown server action.")

    def logs(self):
        return self.ssh("journalctl --user -u nfs13-server.service -n 100 --no-pager -o cat").decode("utf-8", "replace")

    def save(self, destination):
        command = ("set -e; cd /home/ubuntu/nfs13-server; "
                   "files=''; for f in players.json license_plates.json friends.json accounts.json; "
                   "do [ ! -f \"$f\" ] || files=\"$files $f\"; done; "
                   "[ -n \"$files\" ] || exit 4; tar -czf - $files")
        raw = self.ssh(command, timeout=90)
        validate_archive(raw)
        atomic_write(destination, raw)
        return str(destination)

    def restore(self, source):
        files = validate_archive(Path(source).read_bytes())
        safety = DATA / "Backups" / f"before-restore-{time.time_ns()}.tar.gz"
        self.save(safety)
        values = {name: base64.b64encode(raw).decode() for name, raw in files.items()}
        script = ("import base64,subprocess\nfrom pathlib import Path\n"
                  "root=Path('/home/ubuntu/nfs13-server')\n" + f"files={values!r}\n" +
                  "subprocess.run(['systemctl','--user','stop','nfs13-server.service'],check=True)\n"
                  "original={name:(root/name).read_bytes() if (root/name).exists() else None for name in files}\n"
                  "try:\n for name,value in files.items():\n  p=root/(name+'.restore')\n  p.write_bytes(base64.b64decode(value))\n  p.replace(root/name)\n"
                  "except Exception:\n for name,value in original.items():\n  if value is not None: (root/name).write_bytes(value)\n  else: (root/name).unlink(missing_ok=True)\n raise\n"
                  "finally:\n subprocess.run(['systemctl','--user','start','nfs13-server.service'],check=True)\n")
        self.ssh("python3 -", script.encode(), timeout=90)
        return "Server data restored. Safety backup: " + str(safety)

    def admin(self, path, payload=None):
        if not path.startswith("/admin/") or "\n" in path:
            raise ValueError("Invalid admin path")
        script = ("import json,urllib.request\n"
                  f"body={json.dumps(payload).encode()!r} if {payload is not None!r} else None\n"
                  f"request=urllib.request.Request({'http://127.0.0.1:8080' + path!r},data=body,headers={{'Content-Type':'application/json'}})\n"
                  "print(urllib.request.urlopen(request,timeout=15).read().decode())\n")
        result = json.loads(self.ssh("python3 -", script.encode(), timeout=60))
        if result.get("status") == "error":
            raise ValueError(result.get("message", "Server rejected the action"))
        return result

    def players(self):
        result = self.admin("/admin/players")
        if "players" not in result:
            raise ValueError("This backend needs an update. Select Server > Update backend")
        return result["players"]

    def export_player(self, persona_id, destination):
        data = self.admin(f"/admin/player/export?id={int(persona_id)}")
        if data.get("format") != "nfs13-player-1":
            raise ValueError("This backend does not support player backups yet")
        atomic_write(destination, json.dumps(data, indent=2).encode())
        return str(destination)

    def import_player(self, source):
        data = json.loads(Path(source).read_bytes())
        if data.get("format") != "nfs13-player-1":
            raise ValueError("Choose an NFS13 player backup")
        return self.admin("/admin/player/import", data)["message"]

    def preflight(self):
        if not shutil.which("ssh"):
            raise ValueError("Windows OpenSSH is missing. Rerun Setup with the Host component selected")
        identity = self.aws("sts", "get-caller-identity")
        regions = self.aws("lightsail", "get-regions", "--include-availability-zones")["regions"]
        selected = next((r for r in regions if r["name"] == self.region), None)
        if not selected:
            raise ValueError(f"Lightsail is not offered in {self.region}")
        instances = self.aws("lightsail", "get-instances")["instances"]
        bundles = self.aws("lightsail", "get-bundles")["bundles"]
        bundles = [b for b in bundles if b.get("isActive") and "LINUX_UNIX" in b.get("supportedPlatforms", [])
                   and "ipv6" not in b["bundleId"] and 2 <= b.get("ramSizeInGb", 0) <= 8
                   and b.get("cpuCount", 0) >= 2 and b["bundleId"].endswith("_3_0")]
        blueprints = self.aws("lightsail", "get-blueprints")["blueprints"]
        blueprint = next((b["blueprintId"] for b in blueprints if b.get("isActive") and b["blueprintId"] == "ubuntu_24_04"), None)
        if not blueprint or not bundles:
            raise ValueError("No supported Ubuntu/x86 Linux plan was returned for this region")
        zones = [z["zoneName"] for z in selected.get("availabilityZones", []) if z.get("state") == "available"]
        if not zones:
            raise ValueError("This region returned no available Lightsail zones")
        return {"account": identity["Account"], "arn": identity["Arn"], "region": self.region,
                "regions": [r["name"] for r in regions], "zones": zones, "blueprint": blueprint,
                "bundles": sorted(bundles, key=lambda b: b["price"]),
                "instances": [{"name": i["name"], "state": i["state"]["name"], "ip": i.get("publicIpAddress", "")}
                              for i in instances],
                "permission_note": "Account and regional read access verified. AWS confirms create permissions and capacity only when you launch."}

    def create(self, bundle_id, report, restore_file=""):
        if restore_file:
            validate_archive(Path(restore_file).read_bytes())
        report("Checking the selected AWS account, region and plan…")
        checked = self.preflight()
        plan = next((b for b in checked["bundles"] if b["bundleId"] == bundle_id), None)
        if not plan:
            raise ValueError("The selected plan is not available in this region")
        if any(i["name"] == self.instance_name for i in checked["instances"]):
            raise ValueError("That instance already exists. Use Resume installation or connect to it from Server")
        DATA.mkdir(parents=True, exist_ok=True)
        key_name = "nfs13-" + secrets.token_hex(6)
        pair = self.aws("lightsail", "create-key-pair", "--key-pair-name", key_name)
        self.key = str(DATA / (key_name + ".pem"))
        atomic_write(self.key, pair["privateKeyBase64"].encode())
        if os.name == "nt":
            user = run(["whoami"]).decode().strip()
            run(["icacls", self.key, "/inheritance:r", "/grant:r", user + ":F"])
        record = {"profile": self.profile, "region": self.region, "instance": self.instance_name,
                  "key": self.key, "key_pair": key_name, "bundle": bundle_id, "restore_file": restore_file}
        record_path = DATA / (self.instance_name + "-deployment.json")
        atomic_write(record_path, json.dumps(record, indent=2).encode())
        report(f"Creating {self.instance_name} in {self.region}…")
        self.aws("lightsail", "create-instances", "--instance-names", self.instance_name,
                 "--availability-zone", checked["zones"][0], "--blueprint-id", checked["blueprint"],
                 "--bundle-id", bundle_id, "--key-pair-name", key_name,
                 "--ip-address-type", "ipv4", "--tags", "key=ManagedBy,value=NFS13Desktop")
        for _ in range(90):
            current = self.instance()
            if current["state"]["name"] == "running" and current.get("publicIpAddress"):
                break
            time.sleep(4)
        else:
            raise ValueError("AWS is still starting the instance. Its details are saved; use Resume installation")
        report("Assigning a static IP and opening game ports…")
        static_name = self.instance_name + "-ip"
        self.aws("lightsail", "allocate-static-ip", "--static-ip-name", static_name)
        self.aws("lightsail", "attach-static-ip", "--static-ip-name", static_name, "--instance-name", self.instance_name)
        self.aws("lightsail", "put-instance-public-ports", "--instance-name", self.instance_name,
                 "--port-infos", json.dumps(GAME_PORTS))
        self.provision(report)
        if restore_file:
            report("Restoring your server data…")
            self.restore(restore_file)
        record.pop("restore_file", None)
        atomic_write(record_path, json.dumps(record, indent=2).encode())
        self.verify_ready(report)
        record["ip"] = self.instance()["publicIpAddress"]
        record.pop("restore_file", None)
        atomic_write(record_path, json.dumps(record, indent=2).encode())
        return record

    def resume(self, report):
        record_path = DATA / (self.instance_name + "-deployment.json")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("profile") != self.profile or record.get("region") != self.region:
            raise ValueError("Choose the profile and region saved for this deployment")
        self.key = record["key"]
        current = self.instance()
        if not any(t.get("key") == "ManagedBy" and t.get("value") == "NFS13Desktop" for t in current.get("tags", [])):
            raise ValueError("Resume is for servers created by this setup wizard. For the existing server use Update backend")
        report("Repairing the static IP and game firewall configuration…")
        name = self.instance_name + "-ip"
        addresses = self.aws("lightsail", "get-static-ips").get("staticIps", [])
        address = next((a for a in addresses if a["name"] == name), None)
        if address and address.get("attachedTo") not in (None, self.instance_name):
            raise ValueError("The saved static IP belongs to another server")
        if not address:
            self.aws("lightsail", "allocate-static-ip", "--static-ip-name", name)
        if not address or not address.get("isAttached"):
            self.aws("lightsail", "attach-static-ip", "--static-ip-name", name, "--instance-name", self.instance_name)
        self.aws("lightsail", "put-instance-public-ports", "--instance-name", self.instance_name, "--port-infos", json.dumps(GAME_PORTS))
        self.provision(report)
        if record.get("restore_file"):
            self.restore(record["restore_file"])
            record.pop("restore_file", None)
            atomic_write(record_path, json.dumps(record, indent=2).encode())
        self.verify_ready(report)
        record["ip"] = self.instance()["publicIpAddress"]
        record.pop("restore_file", None)
        atomic_write(record_path, json.dumps(record, indent=2).encode())
        return record

    def verify_ready(self, report):
        report("Checking the public launcher endpoint and game listeners…")
        self.ssh("systemctl --user is-active --quiet nfs13-server.service nfs13-frontend.service")
        host = str(ipaddress.IPv4Address(self.instance()["publicIpAddress"]))
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with http.open(f"http://{host}:8080/server_manifest", timeout=20) as response:
            manifest = json.loads(response.read(65536))
        if manifest.get("serverActive") is not True or manifest.get("launcherIdentityVersion") != 2:
            raise ValueError("The public launcher endpoint is not ready. Use Resume installation")
        import socket
        for port in (42127, 44125, 17500):
            with socket.create_connection((host, port), timeout=15):
                pass

    def provision(self, report):
        payload = server_bundle()
        for _ in range(30):
            if self.instance().get("isStaticIp"):
                break
            time.sleep(2)
        else:
            raise ValueError("A static IP has not attached yet. Use Resume installation")
        report("Waiting for SSH and the Ubuntu first-start setup…")
        for attempt in range(30):
            try:
                self.ssh("true")
                break
            except RuntimeError:
                if attempt == 29:
                    raise
                time.sleep(5)
        self.ssh("mkdir -p /home/ubuntu/nfs13-source && tar -xzf - --no-same-owner -C /home/ubuntu/nfs13-source", payload)
        host = str(ipaddress.IPv4Address(self.instance()["publicIpAddress"]))
        report("Installing the backend and building legacy TLS. This can take 5–15 minutes…")
        self.ssh(f"bash /home/ubuntu/nfs13-source/desktop/provision.sh {host} > /home/ubuntu/nfs13-install.log 2>&1 || {{ tail -40 /home/ubuntu/nfs13-install.log; exit 1; }}", timeout=2400)
        return "Server installed and ready"

    def publish(self):
        folder = DATA / "Backups"
        folder.mkdir(parents=True, exist_ok=True)
        self.save(folder / f"before-update-{time.time_ns()}.tar.gz")
        # Servers made before the relay need its UDP range open; this call only adds rules.
        self.aws("lightsail", "open-instance-public-ports", "--instance-name", self.instance_name,
                 "--port-info", json.dumps(GAME_PORTS[-1], separators=(",", ":")))
        source = {name: base64.b64encode((ROOT / "server" / name).read_bytes()).decode()
                  for name in ("server.py", "admin_api.py")}
        script = ("import base64,subprocess\nfrom pathlib import Path\n"
                  "root=Path('/home/ubuntu/nfs13-server')\n" + f"files={source!r}\n" +
                  "for name,value in files.items():\n data=base64.b64decode(value)\n compile(data,name,'exec')\n"
                  "for name,value in files.items():\n p=root/(name+'.update')\n p.write_bytes(base64.b64decode(value))\n p.replace(root/name)\n"
                  "subprocess.run(['systemctl','--user','restart','nfs13-server.service'],check=True)\nprint('Backend updated; pre-update data backup saved on this PC')\n")
        return self.ssh("python3 -", script.encode()).decode().strip()

    def terminate(self, destination):
        self.save(destination)
        owned = [a["name"] for a in self.aws("lightsail", "get-static-ips").get("staticIps", [])
                 if a.get("attachedTo") == self.instance_name]
        # Deletion is offered only after a validated, completed local backup.
        self.aws("lightsail", "delete-instance", "--instance-name", self.instance_name)
        for _ in range(30):
            addresses = [a for a in self.aws("lightsail", "get-static-ips").get("staticIps", []) if a["name"] in owned]
            for address in addresses:
                if not address.get("isAttached"):
                    self.aws("lightsail", "release-static-ip", "--static-ip-name", address["name"])
                    owned.remove(address["name"])
            if not owned:
                break
            time.sleep(2)
        else:
            raise ValueError("Instance deletion requested and backup saved, but AWS has not detached these static IPs yet: " + ", ".join(owned) + ". Release them in Lightsail once detached to avoid idle IP charges.")
        return f"Backup saved to {destination}. Instance deletion requested. Existing snapshots remain in AWS."

    def snapshot(self):
        name = self.instance_name + "-" + time.strftime("%Y%m%d-%H%M%S")
        self.aws("lightsail", "create-instance-snapshot", "--instance-name", self.instance_name,
                 "--instance-snapshot-name", name)
        return "AWS snapshot requested: " + name


def atomic_write(destination, data):
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        file.write(data)
        temporary = Path(file.name)
    temporary.replace(path)


def validate_archive(raw):
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Server backup is too large")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > len(DATA_FILES):
            raise ValueError("Invalid server backup")
        result = {}
        for member in members:
            if not member.isfile() or member.name not in DATA_FILES or member.size > 16 * 1024 * 1024 or member.name in result:
                raise ValueError("Unexpected file in server backup")
            content = archive.extractfile(member).read()
            if not isinstance(json.loads(content), (dict, list)):
                raise ValueError("Invalid server JSON data")
            result[member.name] = content
        return result


def server_bundle():
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name in ("server/server.py", "server/admin_api.py", "server/friends.json",
                     "server/frontend/Dockerfile", "server/frontend/stunnel.conf.in",
                     "client/hosts.txt", "install/install_server.sh", "desktop/provision.sh"):
            raw = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(raw), 0o600
            archive.addfile(entry, io.BytesIO(raw))
    return data.getvalue()
