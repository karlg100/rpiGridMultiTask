# rpiGridMultiTask

Show control for the Halloween display: two video Pis playing "duelling"
clips, the WLED front lights and the graveyard lights, all kept in step over
MQTT.

This branch (`orchestrator-v2`) replaces the old `playlistManager-mqtt.py` +
`omxplayer-mqtt.py` pair with **haunt**. The old scripts are kept, untouched,
in [`legacy/`](legacy/).

The console, captured from `haunt demo` (pretend players, every clip 100 s long):

```
 HAUNT  Halloween                                                          demo (no broker) ●  14:03:42
 ▶ RUNNING   scene 1/14  Pumpkin Song                                                       master 100%
── PLAYERS ────────────────────────────────────────────────────────────────────────────────────────────
▸P1 Window     MASTER   ● playing  JOLJ_PumpkinSong_Trio_Win_BG_H.mp4
                ███████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0:18 / 1:40  level 100%
 P2 Wall       follower ● playing  BC_Numskulls_Wall_H.mp4
                █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  0:03 / 1:40 loop  level 60%
── LIGHTS ─────────────────────────────────────────────────────────────────────────────────────────────
 front_lights ■■ #722800    graveyard ■■ #007200
── PLAYLIST ───────────────────────────────────────────────────────────────────────────────────────────
   # scene                            len P1 Window                 P2 Wall                   lights
 ▶ 1 Pumpkin Song                    1:40 M JOLJ_P… 100%              BC_Num… 60%   loop +15s ■■ ■■
   2 Wicked Brew                     1:40   JOLJ_F… 60%   loop +8s  M WH_Spe… 100%            ■■ ■■
   3 Twas the Night                  1:40 M JOLJ_T… 100%              BC_Jit… 75%   +20s      ■■ ■■
   4 Dragula APT                     1:40 M DJ-Cum… 100%              EE_Omi… mute            ■■ ■■
   5 Cat Crow Canzonet               1:40   TnT_Ba… 60%   +20s      M WH_Son… 100%            ■■ ■■
   6 Frankenstein                    1:03 M Tricks… 100%  @0:37       Phanta… 100%  +40s      ■■ ■■
   7 Thriller                        0:00 M thrill… 100%  @4:04       thrill… mute  +420s →3… ■■ ■■
   8 In the Hall                     1:40 M JOLJ_I… 100%              EE_Omi… 60%   loop      ■■ ■■
   9 Ghostbusters                    1:40   EE_Omi… mute  loop      M Ghostb… 100%            ■■ ■■
── SCENE 1  Pumpkin Song ──────────────────────────────────────────────────────────────────────────────
 P1 master  Jack-O-Lantern - Songs - Window/Jack-O-Lantern - Songs - Window/JOLJ_PumpkinSong_Trio_Win_…
 P2  Bone Chillers - Numskulls/Wall/BC_Numskulls_Wall_H.mp4  level 60%  loop +15s  fade 1/1.5s
 scene ends at 1:40   front_lights #722800   graveyard #007200

── LOG ────────────────────────────────────────────────────────────────────────────────────────────────
 14:03:23 director up: Halloween, 14 scenes
 14:03:23 scene 1: Pumpkin Song
 14:03:23 Window (P1) is online
 14:03:23 Wall (P2) is online
 ? keys   space pause   n next   p prev   r restart   enter go to   s stop/start   +/- master   [ ] lev
```

## What it is

Three small programs that only talk to each other through the MQTT broker:

| Program | Runs on | Job |
|---|---|---|
| `haunt director` | home-pi | Runs the show: walks the playlist, cues the players, sets the lights. Headless. |
| `haunt player` | each video Pi | Drives one long-lived `mpv`: load, play, fade, volume. |
| `haunt console` | anywhere | The terminal UI above. Open and close it freely; the show does not notice. |

The playlist is [`show.yaml`](show.yaml) (settings explained in
[docs/SHOW-FILE.md](docs/SHOW-FILE.md)).

## Try it right now, without any Pis

On the Mac, from this folder:

```sh
pip3 install paho-mqtt pyyaml        # once
python3 -m haunt demo                # your real show.yaml, pretend players, no broker needed
```

Every clip is pretended to be 30 seconds long (`--clip-seconds N` to change).
All the keys work. `python3 -m haunt check` validates `show.yaml`.

## What changed for the three complaints

**Flicker at clip start and end.** omxplayer was started fresh for every clip,
so the video output was torn down and rebuilt at every boundary. Each player
now keeps a single `mpv` running all night. A clip is loaded paused and
blacked out, starts on cue with a fade up from black, fades back to black at
its end, and the screen simply stays black in between.

**Volume.** Each file's loudness is measured once (EBU R128, with ffmpeg, on
the player, cached) and evened out, so `level: 100` is the same loudness for
every clip. `level` in the show file is then just "how loud do I want this
one", 0 to 150. Sound fades in and out with the picture. Levels and a master
fader can be changed live from the console and are remembered.

**The clunky Python.** See [docs/REVIEW.md](docs/REVIEW.md) for what was wrong
and [docs/DESIGN.md](docs/DESIGN.md) for how the new one is put together.

## Console keys

| Key | Does |
|---|---|
| `space` | pause / resume both screens |
| `n` / `p` | next / previous scene |
| `r` | restart the current scene |
| `up` `down` then `enter` | pick a scene and go to it |
| `s` | stop the show (screens black) / start it again |
| `x` | mark the selected scene "skip" (or un-skip it) |
| `+` / `-` | master volume |
| `tab` | choose a player (the `▸` marker) |
| `[` / `]` | that player's level in the current scene, down / up |
| `m` | mute / unmute that player in the current scene |
| `u` | undo console level changes for the current scene (back to show.yaml) |
| `R` | reload show.yaml |
| `?` | show all keys |
| `Ctrl-L` | repaint |
| `q` | quit the console (the show keeps running) |

A `*` after a level means it was changed from the console and differs from
show.yaml. Those changes, the master level and skipped scenes are saved in
`show.state.json` next to the show file.

Anything that can publish MQTT can drive the show too:

```sh
python3 -m haunt send next
mosquitto_pub -h 192.168.1.243 -t haunt/director/cmd -m pause     # e.g. from Home Assistant
```

## Installing on the Pis

[docs/INSTALL.md](docs/INSTALL.md). Short version, on each machine after
cloning this repo:

```sh
sudo deploy/install.sh director      # on home-pi
sudo deploy/install.sh player 1      # on video Pi 1 (and "player 2" on the other)
```

## Tests

```sh
pip3 install pytest
python3 -m pytest tests
```

54 tests. Most run a whole simulated show on a fake clock in milliseconds.
`tests/test_real.py` starts a real mosquitto and real mpv processes if they
are installed, and is skipped if not.

## Also in this repo

`neoPixels/`, `Particle/` (the graveyard and old front-light firmware),
`candle2.py` and `gpio.sh` are unchanged.
