# nfs13 online

Private self-hosted online server for **Need for Speed: Most Wanted (2012)** on PC,
with a Windows app that hosts it on AWS Lightsail and a player launcher you can
send to friends.

**Download:** [latest release](https://github.com/NotCodingRN/nfs13-online/releases/latest)

| File | Who it is for |
| --- | --- |
| `NFS13ServerControl.zip` | The host. Creates and manages the AWS server, then builds a player ZIP with your server IP filled in. |
| `NFS13Player.zip` | Players. Launcher that patches your own copy of the game and connects to a server IP. |

## Hosting a server (Windows)

You need your own AWS account with the AWS CLI configured. Your AWS
credentials stay on your PC.

1. Unzip `NFS13ServerControl.zip` and run `NFS13ServerControl.exe`.
2. Select your AWS CLI profile, region and a new server name.
3. Click **Test AWS & region**. Choose a plan from AWS's current prices.
4. Optionally choose a previous server backup, then click **Create server**.
5. It creates an Ubuntu Lightsail instance, static IP and firewall rules,
   installs the backend and legacy TLS frontend, and checks the public endpoints.
   Allow about 5–15 minutes. If interrupted, select **Resume installation**.
6. When ready, it creates a **player ZIP with the server IP prefilled** and opens
   its folder. Send that ZIP to friends. Friends do not need an AWS account.

The player ZIP includes the launcher and its source, with no AWS credentials,
SSH keys, host configuration or player identities. Regenerate it with
**Server → Export player ZIP**. Files are under `%LOCALAPPDATA%\Fairhaven\PlayerPacks`.

The control app also provides player inspection, online SP edits, login
disabling, per-player exports/restores, server backups, logs and
service/instance controls. Career saves remain on each PC.

**AWS charges accrue while the instance exists, including when stopped.** Use
**Backups → Back up and delete instance** to save server data and remove the
instance and its static IP. Restore that backup when creating a new server.

## Playing

1. Unzip the player ZIP from your host (or `NFS13Player.zip` and type the host's IP).
2. Run `NFS13Player.exe`, choose your game folder and display name, confirm you
   own the game, then click **Play**.

Names are 1–15 Latin letters, digits, `_` or `-`. They are display names, not
password-protected accounts. Keep `%LOCALAPPDATA%\Fairhaven\identities.json`
when moving to another PC.

Driving traffic is peer to peer: a cloud server does not bypass strict NAT.
Networks that block peer traffic may need a shared VPN. Twelve players is the
game's lobby limit; this build has not been load-tested with twelve clients.

> [!IMPORTANT]
> **Use this project ONLY with a legally acquired copy of Need for Speed: Most Wanted (2012).**
> No game files are provided. The patcher only works on your own installed copy.

> [!NOTE]
> **No public servers. Self-hosting only.** This repository is software you run
> yourself for you and people you know.

> [!WARNING]
> **Not affiliated with EA.** Not affiliated with, authorized, sponsored or endorsed
> by Electronic Arts Inc. or Criterion Games. Full terms: [DISCLAIMER.md](DISCLAIMER.md).
> *Need for Speed* and *Most Wanted* are trademarks of Electronic Arts Inc.

## What works

| Feature | State |
| --- | --- |
| Online login, EasyDrive, online menus | Works |
| Free roam with up to 12 players (tested with 3) | Works |
| Speedlists: five events picked at random each time | Works |
| License plates, player names, online XP | Saved on the server |
| Friends list and Autolog recommendations | Implemented, not fully verified in game |
| End-of-speedlist results | Not yet: the server does not send `ResultNotification` |
| Host migration | The new host does not restart the speedlist |

## How it fits together

Details: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

```
 game (patched NFS13.online.exe)
   │  DNS: *.ea.com names → your server (hosts file)
   ├── TCP 42127  Blaze (SSLv3) ─┐
   ├── TCP 44125  HTTPS (SSLv3) ─┤ stunnel-ssl3 → server.py
   ├── TCP 8080   Autolog HTTP  ─┘
   ├── TCP/UDP 17500  QoS
   └── UDP 3659  directly between players (peer to peer)
```

`server.py` is a single Python file with no dependencies. It answers the Blaze
RPCs the game uses and Autolog's HTTP API.

## Manual server setup (Linux)

Requirements: Python 3.10+, OpenSSL, and Docker to build an SSLv3-capable stunnel.

```bash
git clone https://github.com/NotCodingRN/nfs13-online.git
cd nfs13-online
./install/install_server.sh 192.168.1.50      # the IP players use to reach the server
```

Then open TCP 42127, 44125, 8080, 17500 and UDP 17500 and 3700-3899 (the peer relay). Watch it live with
`journalctl --user -u nfs13-server.service -f -o cat`.

## Manual client setup

```bash
python client/patch_nfs13.py --i-own-this-game "C:\path\to\NFS13.exe"
```

This writes `NFS13.online.exe` next to the original without changing it. Then add
each name in [client/hosts.txt](client/hosts.txt) to your hosts file pointing at
the server IP (`install/add_hosts_windows.ps1` does this on Windows).

## Building the release

```powershell
python -m unittest discover -s server
python -m unittest discover -s desktop
python desktop/build.py .\release
```

Needs Python, PyInstaller and Pillow. Add `--setup --compiler <ISCC.exe> --aws-msi <AWSCLIV2.msi>`
to also build the combined `setup.exe` (requires Inno Setup).

## Security warnings

- The game uses SSLv3, an obsolete and insecure protocol. Do not send sensitive data through it.
- The client patch skips the game's server certificate check. Only connect to servers you trust.
- The patcher modifies a copy of a game executable; it may trigger security software or violate the game's terms.
- Never enter EA account passwords into this or any community server.

## Legal

Unofficial, non-commercial, self-hosting only. You must use your own lawfully
acquired copy of the game. Reverse engineering and modifying executables may be
restricted where you live; you are responsible for checking applicable law.

Licensed under the [GNU Affero General Public License v3.0](LICENSE), without any
warranty. See [DISCLAIMER.md](DISCLAIMER.md), [SECURITY.md](SECURITY.md) and [AUTHORS](AUTHORS).
