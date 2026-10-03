#!/bin/bash
# Set up this machine as the director or as a player.
#
#   sudo deploy/install.sh director
#   sudo deploy/install.sh player 1
#
# Safe to run again: it never overwrites an existing /etc/haunt/* file.
set -euo pipefail

role="${1:-}"
id="${2:-}"
dir="$(cd "$(dirname "$0")/.." && pwd)"
user="${SUDO_USER:-$(id -un)}"

if [ "$(id -u)" -ne 0 ]; then
    echo "run with sudo" >&2; exit 1
fi
case "$role" in
    director) pkgs="python3-paho-mqtt python3-yaml" ;;
    player)
        [ -n "$id" ] || { echo "usage: $0 player <id>" >&2; exit 1; }
        pkgs="python3-paho-mqtt python3-yaml mpv ffmpeg" ;;
    *) echo "usage: $0 director | player <id>" >&2; exit 1 ;;
esac

echo "== installing packages: $pkgs"
apt-get update -q
# shellcheck disable=SC2086
apt-get install -y -q $pkgs

mkdir -p /etc/haunt
if [ ! -e /etc/haunt/env ]; then
    cat > /etc/haunt/env <<ENV
# MQTT password for the broker user named in show.yaml / player.yaml
HAUNT_MQTT_PASSWORD=
ENV
    chown "$user" /etc/haunt/env     # so `haunt console` run by $user can read it too
    chmod 600 /etc/haunt/env
    echo "== created /etc/haunt/env  <-- put the MQTT password in it"
fi

if [ "$role" = player ]; then
    if [ ! -e /etc/haunt/player.yaml ]; then
        sed "s/^id: .*/id: $id/" "$dir/deploy/player.example.yaml" > /etc/haunt/player.yaml
        echo "== created /etc/haunt/player.yaml (id $id)  <-- check media_root, rotate, audio_device"
    fi
    usermod -aG video,render,audio "$user"
fi

unit="haunt-$role.service"
sed -e "s|@USER@|$user|" -e "s|@DIR@|$dir|" "$dir/deploy/$unit" > "/etc/systemd/system/$unit"
systemctl daemon-reload
systemctl enable "$unit"
echo "== installed and enabled $unit (running as $user from $dir)"
echo "   start it:   sudo systemctl start $unit"
echo "   watch it:   journalctl -fu $unit"
