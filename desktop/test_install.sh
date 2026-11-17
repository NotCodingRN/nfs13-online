#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Exercise the real installer without systemd, Docker, sudo or cloud resources.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
export HOME="$scratch/home" NFS13_DIR="$scratch/server" USER=nfs13-test
mkdir -p "$HOME" "$scratch/bin" "$NFS13_DIR/frontend"
export PATH="$scratch/bin:$PATH"
export STUNNEL_SSL3="$NFS13_DIR/frontend/stunnel-ssl3"
printf '#!/bin/sh\nexit 0\n' > "$STUNNEL_SSL3"
chmod +x "$STUNNEL_SSL3"
printf '#!/bin/sh\nexit 0\n' > "$scratch/bin/systemctl"
printf '#!/bin/sh\nexit 0\n' > "$scratch/bin/loginctl"
cat > "$scratch/bin/openssl" <<'EOF'
#!/bin/sh
while [ "$#" -gt 0 ]; do
 case "$1" in
  -keyout|-out) shift; printf 'test certificate\n' > "$1" ;;
 esac
 shift
done
EOF
chmod +x "$scratch/bin/"*
bash "$REPO/install/install_server.sh" 192.168.1.50
test -s "$NFS13_DIR/server.py"
test -s "$NFS13_DIR/admin_api.py"
test -s "$NFS13_DIR/certs/cert.pem"
grep -q 'NFS13_HOST=192.168.1.50' "$HOME/.config/systemd/user/nfs13-server.service"
printf 'Installer passed with the prebuilt TLS binary already in its destination.\n'
