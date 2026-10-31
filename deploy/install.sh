#!/bin/bash
# Set up this machine as the director or as a player.
#
#   sudo deploy/install.sh director
#   sudo deploy/install.sh player 1
#   sudo deploy/install.sh dmx            (the Pi with the USB-to-DMX dongle)
#   sudo deploy/install.sh hue            (Philips Hue rooms; usually home-pi)
#   sudo deploy/install.sh floods         (AiDot floods through Home Assistant; usually home-pi)
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
    dmx) pkgs="python3-paho-mqtt python3-yaml python3-serial" ;;
    hue) pkgs="python3-paho-mqtt python3-yaml avahi-utils" ;;
    floods) pkgs="python3-paho-mqtt python3-yaml" ;;
    *) echo "usage: $0 director | player <id> | dmx | hue | floods" >&2; exit 1 ;;
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

if [ "$role" = dmx ]; then
    if [ ! -e /etc/haunt/dmx.yaml ]; then
        cp "$dir/deploy/dmx.example.yaml" /etc/haunt/dmx.yaml
        echo "== created /etc/haunt/dmx.yaml  <-- check the channel and level"
    fi
    usermod -aG dialout "$user"
fi

if [ "$role" = hue ]; then
    if [ ! -e /etc/haunt/hue.yaml ]; then
        cp "$dir/deploy/hue.example.yaml" /etc/haunt/hue.yaml
        echo "== created /etc/haunt/hue.yaml  <-- check the bridge and room names"
    fi
    if [ ! -e /etc/haunt/hue.key ]; then
        install -m 600 -o "$user" /dev/null /etc/haunt/hue.key
        echo "== press the Hue bridge button, then:  python3 -m haunt hue -c /etc/haunt/hue.yaml --pair"
    fi
fi

if [ "$role" = floods ]; then
    if [ ! -e /etc/haunt/floods.yaml ]; then
        cp "$dir/deploy/floods.example.yaml" /etc/haunt/floods.yaml
        echo "== created /etc/haunt/floods.yaml  <-- check the Home Assistant address and the entity ids"
    fi
    if [ ! -e /etc/haunt/ha.token ]; then
        install -m 600 -o "$user" /dev/null /etc/haunt/ha.token
        echo "== put a Home Assistant long-lived access token in /etc/haunt/ha.token"
    else
        chown "$user" /etc/haunt/ha.token; chmod 600 /etc/haunt/ha.token
    fi
fi

unit="haunt-$role.service"
sed -e "s|@USER@|$user|" -e "s|@DIR@|$dir|" "$dir/deploy/$unit" > "/etc/systemd/system/$unit"
systemctl daemon-reload
systemctl enable "$unit"
echo "== installed and enabled $unit (running as $user from $dir)"
echo "   start it:   sudo systemctl start $unit"
echo "   watch it:   journalctl -fu $unit"
