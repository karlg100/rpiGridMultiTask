# Installing

## What the 2026 setup actually is

Done on 2026-10-29 and running:

| Machine | Hardware / OS | Role |
|---|---|---|
| home-pi (`pi@home-pi`, wired 192.168.1.45, wifi 192.168.1.18) | Pi 3B, Raspberry Pi OS 12 (bookworm) 32-bit | mosquitto broker + `haunt-director.service` |
| client1 (`karlg@client1.local`) | Pi 4, Raspberry Pi OS 13 (trixie) 64-bit | player 1 "Window", `rotate: 180` |
| client2 (`karlg@client2.local`) | Pi 4, Raspberry Pi OS 13 (trixie) 64-bit | player 2 "Wall" |

- Broker: mosquitto on home-pi, `/etc/mosquitto/conf.d/haunt.conf`, listening
  on every interface, login required, user `home-pi`. Everything in the show
  connects to the **wired** address, 192.168.1.45. The password is in
  `/etc/haunt/env` on each machine.
- The players were imaged with the **desktop** version of Raspberry Pi OS.
  They now boot to the console (`systemctl set-default multi-user.target`) so
  mpv can own the screen. `sudo systemctl set-default graphical.target`
  brings the desktop back.
- Videos are in `/home/karlg/videos` on both players (`media_root`).
- Sound goes to the headphone jack: `alsa/plughw:CARD=Headphones,DEV=0`.
- Learned on the real Pi 4s and now in `player.yaml`:
  - `--profile=fast`: with mpv's default scaler the Pi 4 dropped about 15
    frames a second on the 1080p clips; with it, none. Software decoding is
    fine (about one core); hardware decoding made no difference.
  - `--vo=gpu --gpu-context=drm`: with no display connected mpv otherwise
    falls back to a slow software window and stays there after the projector
    is plugged in. Pinned, it refuses to start, the player shows
    "mpv will not start - is the projector connected?" in the console, and
    it starts by itself within 5 s of a display appearing.

The rest of this page is the general procedure.

## 0. Rehearse on the Mac first

```sh
pip3 install paho-mqtt pyyaml
python3 -m haunt check show.yaml
python3 -m haunt demo show.yaml
```

## 1. The director (home-pi)

home-pi already runs Python 3 and reaches the broker, so nothing needs
reflashing.

```sh
cd ~ && git clone -b orchestrator-v2 https://github.com/karlg100/rpiGridMultiTask.git
cd rpiGridMultiTask
sudo deploy/install.sh director
sudoedit /etc/haunt/env          # HAUNT_MQTT_PASSWORD=...
sudo systemctl start haunt-director
journalctl -fu haunt-director
```

Then, from any SSH session on home-pi (or the Mac):

```sh
cd ~/rpiGridMultiTask && python3 -m haunt console
```

On home-pi the console finds the password in `/etc/haunt/env`. On the Mac,
`export HAUNT_MQTT_PASSWORD=...` first.

With no players up yet the director reports each scene's master as offline
and waits. That is the expected first sight.

Stop the old manager first if it is running; old and new use different
topics for the players, but both would drive the lights.

## 2. A player Pi

### Which Pi

A **Pi 4 is the safe choice**: it can decode 1080p H.264 in software if
hardware decoding does not engage, so the picture will be right either way.
A Pi 3 should work but depends on hardware decoding being set up correctly,
and has less headroom for the fade.

### OS

Flash current **Raspberry Pi OS Lite** (no desktop) with Raspberry Pi Imager;
set hostname, user, Wi-Fi and SSH in the imager. omxplayer does not exist on
any current image, which is the reason for the reflash.

Copy the videos to the Pi, keeping the same folder layout as before under one
directory (the old layout was `/home/pi/videos/...`).

### Install

```sh
cd ~ && git clone -b orchestrator-v2 https://github.com/karlg100/rpiGridMultiTask.git
cd rpiGridMultiTask
sudo deploy/install.sh player 1          # 2 on the other Pi
sudoedit /etc/haunt/env                  # HAUNT_MQTT_PASSWORD=...
sudoedit /etc/haunt/player.yaml          # media_root, rotate, audio_device
```

In `player.yaml`:

- `media_root`: where the videos are.
- `rotate: 180` on the Pi that used `--orientation 180` (player 1).
- `audio_device`: run `mpv --audio-device=help` and copy the name of the
  output you use. The old setup used the headphone jack (`-o local`).

### Check mpv by hand before starting the service

Over SSH, with the projector connected:

```sh
mpv --fullscreen /path/to/any/clip.mp4
```

You should get picture on the projector and sound. If that works, start the
agent in the foreground once to watch it:

```sh
python3 -m haunt player -c /etc/haunt/player.yaml -v
```

and then for real:

```sh
sudo systemctl start haunt-player
journalctl -fu haunt-player
```

The first time the show runs, each player measures the loudness of its files
in the background. Until
a file has been measured it plays without correction.

### Things to try if the picture is not right

| Symptom | Try |
|---|---|
| No picture from the service, fine by hand | The service user must be in the `video` and `render` groups (install.sh adds them; log out and in, or reboot). |
| Stutter, or `mpv` at 300% CPU in `top` | Hardware decoding is not engaged. Add to `mpv_args`: `["--hwdec=auto"]`, and if that does not help `["--hwdec=v4l2m2m-copy"]`. Run mpv by hand with `-v` and look for the line that says which hwdec is in use. |
| Still heavy on a Pi 3 | Set `video_fade: false` and add `["--vo=drm"]` to `mpv_args`. That is mpv's lightest output; clips then cut to and from black rather than fading (sound still fades). Or re-encode the clips to 720p. |
| Fade does nothing, clips just cut | The picture fade needs `--vo=gpu` (the default). |
| Login prompt or boot text visible before the first clip | `sudo systemctl disable getty@tty1`, and add `quiet logo.nologo vt.global_cursor_default=0` to `/boot/firmware/cmdline.txt`. |
| Screen blanks after a while | Add `consoleblank=0` to `/boot/firmware/cmdline.txt`. |
| Wrong audio output or silence | `audio_device` in player.yaml; list with `mpv --audio-device=help`. |

## 3. Night-of

```sh
python3 -m haunt console        # on home-pi over SSH, or on the Mac
```

- Tune levels by ear with `tab`, `[`, `]`; they stick.
- `x` on a scene skips it for the night.
- `s` stops the show (screens go black, lights stay); `s` again resumes.
- Edit `show.yaml`, press `R`.

## Going back

The old scripts are in `legacy/` on this branch and untouched on `master`.
