#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
cd /home/ubuntu/nfs13-source
IP="$1"
sudo cloud-init status --wait >/dev/null 2>&1 || true
sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io python3 openssl curl
sudo systemctl enable --now docker
# The legacy TLS build needs more memory than the steady-state game service.
if [ ! -e /var/swap.nfs13 ]; then
  sudo fallocate -l 1G /var/swap.nfs13
  sudo chmod 600 /var/swap.nfs13
  sudo mkswap /var/swap.nfs13 >/dev/null
  sudo swapon /var/swap.nfs13
  echo '/var/swap.nfs13 none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
DEST=/home/ubuntu/nfs13-server
mkdir -p "$DEST/frontend"
if [ ! -x "$DEST/frontend/stunnel-ssl3" ]; then
  sudo docker build -t nfs13-stunnel-ssl3 server/frontend
  container=$(sudo docker create nfs13-stunnel-ssl3)
  sudo docker cp "$container:/out/stunnel-ssl3" "$DEST/frontend/stunnel-ssl3"
  sudo docker rm "$container" >/dev/null
  sudo chown ubuntu:ubuntu "$DEST/frontend/stunnel-ssl3"
fi
chmod +x "$DEST/frontend/stunnel-ssl3"
sudo loginctl enable-linger ubuntu
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
STUNNEL_SSL3="$DEST/frontend/stunnel-ssl3" bash install/install_server.sh "$IP"
curl --retry 10 --retry-connrefused --retry-delay 2 -fsS http://127.0.0.1:8080/server_manifest
touch "$DEST/.provisioned"
