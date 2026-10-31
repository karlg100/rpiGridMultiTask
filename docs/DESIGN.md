# Design

## Shape

```
                         MQTT broker (192.168.1.243)
                                   │
        ┌──────────────┬───────────┴───────────┬──────────────────┐
        │              │                       │                  │
  haunt director   haunt player 1        haunt player 2      haunt console
     (home-pi)      (video Pi)            (video Pi)       (any terminal, 0..n)
        │              │                       │
        │           one mpv                 one mpv
        │         (kept running)          (kept running)
        │
        └── plain MQTT publishes ──► WLED front lights, Particle graveyard
```

Three programs, one Python package (`haunt/`), no shared state except what is
on the broker.

- The **director** is the only thing that knows the playlist. It is headless
  and runs under systemd.
- A **player** knows nothing about scenes. It is told "load this file, at
  this level, with these fades", "play", "stop", and reports what it is doing.
- The **console** only reads retained state and publishes commands. Closing
  it changes nothing. Home Assistant or `mosquitto_pub` can do the same.

Dependencies are deliberately the ones `apt` already has on Raspberry Pi OS:
`python3-paho-mqtt`, `python3-yaml`, `mpv`, `ffmpeg`. The console uses
`curses` from the standard library. No pip, no virtualenv on the Pis.
Works on Python 3.9+ and paho-mqtt 1.x or 2.x (both tested).

## Why mpv, kept running

The flicker came from starting and killing omxplayer per clip. Each player
now starts **one** mpv at boot and holds it:

```
mpv --idle=yes --force-window=immediate --keep-open=yes --fullscreen ...
    --input-ipc-server=/tmp/haunt-mpv-<pid>.sock
```

- `--idle` + `--force-window`: mpv owns the screen from the start and shows
  black whenever nothing is loaded. The video output is opened once.
- Clips are loaded into that instance over its JSON IPC socket, **paused**,
  with the picture faded to black first, so the first frame is decoded and
  waiting but nothing is visible.
- On cue: unpause and fade up. Near the end: fade down. `--keep-open` holds
  the output at end of file rather than closing it; the agent then unloads the
  file and the screen is black until the next one.
- Looping uses mpv's own `loop-file`, which is seamless.

The picture fade is mpv's `brightness` property ramped between -100 and 0.
With the default `--vo=gpu` that is applied in the GPU shader, so it costs
nothing. The sound fade is the `volume` property on the same ramp.

If mpv dies the agent restarts it. If the agent dies, the kernel kills its
mpv (`PR_SET_PDEATHSIG`) so an orphan can never keep hold of the display.

## Volume

```
file ──► gain stage ──► peak limiter (-1 dBFS) ──► mpv volume ──► ALSA PCM (0 dB) ──► line out
          │                                          │
          loudness correction                        fades only (0-100%)
          + clip level (show.yaml / console)
          + master fader (console)
          + trim (player.yaml)
```

- **Loudness correction.** The first time a player is asked about a file it
  measures the integrated loudness with `ffmpeg -af ebur128` (audio only,
  niced, in a background thread) and caches it in
  `~/.cache/haunt/loudness.json`. At load time it adds
  `target_lufs - measured` dB (target -14 LUFS; boosts capped at +18 dB).
  The clips range from -24 to -7.5 LUFS, see docs/LOUDNESS.md.
- **Levels** are percentages on mpv's cubic scale, turned into dB
  (`60*log10(level/100)`: 50% is -18 dB) and added to the same gain.
- **The limiter** (`alimiter`, limit -1 dBFS) comes after all of that, so a
  quiet clip can be pushed up to the target without its peaks clipping, and a
  master above 100% cannot clip either.
- **mpv's own volume** only does the fades, and never goes above 100%.
- **The Pi's analog output** has its own hardware level (ALSA `PCM` on the
  `Headphones` card). It defaulted to -19.9 dB, which made everything quiet;
  it is now set to 0 dB and saved with `alsactl store`.

Gain changes while a clip plays are sent with mpv's `af-command`, so there is
no dropout.

## The protocol

Everything is under one prefix (default `haunt`), separate from the old
`player/...` topics, so old and new can coexist while migrating. The light
topics are unchanged.

| Topic | Retained | Payload |
|---|---|---|
| `haunt/director/online` | yes | `1` / `0` (last will) |
| `haunt/director/state` | yes | JSON: phase, scene, position, master level, lights, log tail |
| `haunt/director/playlist` | yes | JSON: the loaded show with every setting |
| `haunt/director/cmd` | no | JSON command, or a bare word |
| `haunt/player/<id>/online` | yes | `1` / `0` (last will) |
| `haunt/player/<id>/state` | yes | JSON: state, cue, file, pos, dur, level, volume, gain_db, error |
| `haunt/player/<id>/probe` | yes | JSON: which show files exist, their loudness and length |
| `haunt/player/<id>/cmd` | no | JSON command |
| `haunt/hue/control` | yes | `show` / `released`, set by the director (console `h`) |
| `haunt/hue/<name>/set` | yes | JSON: the scene's Hue setting for that room |
| `haunt/hue/<name>/status` | yes | `ok: ...`, `released to the house`, or the error |
| `haunt/hue/online` | yes | `1` / `0` (last will of `haunt hue`) |

Two rules fix the old races:

1. **One message per command.** `load` carries the file and every setting.
   There is no window in which a player has half its parameters.
2. **Every command has a cue id and every state report echoes it.** The
   director only believes a report that carries the current scene's cue, so
   stale or retained state can never be mistaken for progress.

Director commands (`haunt/director/cmd`):

```
next  prev  restart  pause  resume  toggle  stop  start  reload
{"cmd":"goto","index":3}
{"cmd":"master","value":80}            or  {"cmd":"master","delta":-5}
{"cmd":"level","player":"2","delta":5}     (current scene; add "scene":N for another)
{"cmd":"mute","player":"1"}
{"cmd":"enable","index":5,"value":false}
{"cmd":"reset_levels"}
hue   or  {"cmd":"hue","value":false}  (Hue rooms to the house; true gives them back)
{"cmd":"output","name":"fog_machine","value":"on|off|auto"}
{"cmd":"mono","player":"2","value":false}       (no value toggles; the player keeps it)
{"cmd":"test","value":true}                      test mode on/off (stops the show first)
{"cmd":"test_scene","delta":1}  or "index":N     test mode: every light shows that scene's look
{"cmd":"test_light","name":"front_lights","pattern":"red"}   name or "all";
                                  pattern: scene white red green blue off
```

Player commands (`haunt/player/<id>/cmd`), sent by the director:

```
{"cmd":"load","cue":"a3f1-7","file":"...","start":0,"loop":false,"level":100,
 "fade_in":1.0,"fade_out":1.5,"target_lufs":-18}
{"cmd":"play","cue":"a3f1-7"}          optional "at": wall-clock time to start
{"cmd":"pause"}  {"cmd":"resume"}
{"cmd":"stop","fade":1.5}
{"cmd":"level","value":70,"ramp":0.3}
{"cmd":"probe","files":[...]}
```

Player states: `idle`, `loading`, `ready`, `playing`, `paused`, `stopping`,
`ended`, `error`.

## The director's state machine

```
            ┌──────────────────────────────────────────────┐
            ▼                                              │
       preparing ──all ready──► running ──master done──► ending ──► gap
            │                      │                                 │
   master offline/error      next/prev/goto                    stop pressed
            │                      └────────► ending               ▼
            ▼                                                   stopped
      skip to next scene
   (all scenes fail ► waiting, retry every 5 s)
```

- **preparing**: send `load` to each player in the scene (and `stop` to any
  that is not). Wait until they report `ready` for this cue. A follower that
  is offline or slow does not hold the show up; a master that is offline or
  errors gets the scene skipped.
- **running**: `play` the master; apply the lights; start followers when the
  master's position reaches their `start_after`; fire cues; stop followers at
  their own `end_at`. As the master nears its end, followers are faded so
  both screens reach black together. The scene ends when the master reports
  `ended`, hits `end_at`, goes offline or stops reporting.
- **ending**: everything fades out; wait for `idle`.
- **gap**: a moment of black, then the next enabled scene.

Lost messages are handled by repetition rather than hope: a `load` or `play`
that a player has not acted on within 2.5 s is sent again, which also brings
back a player that rebooted mid-scene. If the broker itself goes away the
director holds still and carries on when it returns.

The director's position for the master is extrapolated between reports, so
follower starts and cues are accurate to about a tenth of a second, not to
the report interval.

## Code map

| File | What |
|---|---|
| `haunt/director.py` | Scene state machine, commands, light cues, persistence of console changes |
| `haunt/player.py` | Player agent: commands, fades, volume maths, state reports |
| `haunt/backends.py` | `MpvBackend` (process + IPC) and `FakeBackend` (clock-driven pretend player) |
| `haunt/console.py` | `render()` (pure: model in, text lines out), key handling, curses painting |
| `haunt/config.py` | show.yaml / player.yaml parsing and validation |
| `haunt/bus.py` | `MqttBus` (paho, reconnecting, last-will) and `MemoryBus` (in-process, for tests and demo) |
| `haunt/lights.py` | WLED and Particle message formats |
| `haunt/loudness.py` | ffmpeg measurement, cache, dB maths |
| `haunt/cli.py` | `director`, `player`, `console`, `demo`, `check`, `send` |

Each component is single-threaded: messages arrive on a queue and are handled
between `tick()` calls, so there are no locks in the show logic. The clock is
injected, which is what lets the tests run a whole show in milliseconds.

## What has and has not been tested

Tested here, on x86 Linux:

- The director, player agent and console logic: 52 tests on a simulated clock
  (scene flow, offsets, cues, pause, skip, offline/restarting players, level
  changes, persistence, config validation, rendering at several sizes).
- The real stack end to end: mosquitto 2.0 (with password auth), two real
  mpv 0.37 processes with null video/audio output, generated clips, including
  a broker restart mid-scene and a missing file.
- The picture fade, measured from the actual screen contents under a
  software-GL X server: black while loaded and paused, linear ramp to full.
- Python 3.9 + paho-mqtt 1.6 and Python 3.13 + paho-mqtt 2.1.

Since then it has been installed on the real machines (two Pi 4s on
Raspberry Pi OS trixie, a Pi 3 on bookworm for the director): DRM/KMS output,
the systemd units, `deploy/install.sh`, loudness measurement and reboot
autostart all work. See docs/INSTALL.md for what had to be tuned.

## Not done (ideas)

- Start/stop the show on a schedule or at dusk (`neoPixels/calc_nighttime.py`
  already computes it).
- The house-eyes Pi as a third "player", or at least lights-style cues to it.
- Triggering the fog machine from a cue (it only needs an MQTT-switchable
  relay; the `cues: mqtt:` hook is already there).
