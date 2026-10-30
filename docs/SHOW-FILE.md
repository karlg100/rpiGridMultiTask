# show.yaml reference

Check a file with `python3 -m haunt check show.yaml`. Every problem is
reported with the scene it is in. Press `R` in the console to reload a running
show; a file with errors is rejected and the running show is kept.

## Top level

```yaml
name: Halloween

mqtt:
  host: 192.168.1.243
  port: 1883
  username: home-pi
  prefix: haunt            # all haunt topics start with this
  # password: taken from $HAUNT_MQTT_PASSWORD, or password_file: /path

players:                   # ids must match the id in each Pi's player.yaml
  1: {name: Window}
  2: {name: Wall}

lights:
  front_lights: {type: wled, topic: front_lights}
  graveyard: {type: particle, topic: graveyard}

defaults: { ... }          # see below
scenes: [ ... ]
```

## defaults

| Setting | Default | Meaning |
|---|---|---|
| `fade_in` | 1.0 | Seconds a clip takes to fade up (picture and sound). |
| `fade_out` | 1.5 | Seconds to fade down at a clip's natural end. |
| `skip_fade` | 0.6 | Fade used when you press next / prev / stop. |
| `gap` | 0.5 | Seconds of black between scenes. |
| `level` | 100 | Level for clips that do not set one. |
| `target_lufs` | -14 | Loudness every clip is normalised to. A limiter catches peaks, so quiet clips can be boosted safely. |
| `ready_timeout` | 10 | Seconds to wait for players to load a scene before going on without them. |
| `follower_preroll` | 5 | A late-starting follower is loaded this long before its cue. |
| `sync_lead` | 0 | If above 0, clips that start together are told to start at a shared wall-clock time this many seconds ahead. Needs the Pis' clocks in sync (NTP). 0 = start on receipt, which is within a few milliseconds on a LAN. |

## A scene

```yaml
  - name: Pumpkin Song       # must be unique
    master: 1                # this player's clip decides when the scene ends
    end_at: 100              # optional: end the scene when the master reaches 100 s
    enabled: true            # optional: false = skipped (also toggled with x in the console)
    players:
      1:
        file: "Jack-O-Lantern - Songs - Window/JOLJ_PumpkinSong_Trio_Win_BG_H.mp4"
        level: 100
      2:
        file: "Bone Chillers - Numskulls/Wall/BC_Numskulls_Wall_H.mp4"
        level: 60
        loop: true
        start_after: 15
    lights:
      front_lights: "#722800"
      graveyard: [0, 114, 0]
    cues:
      - at: 42
        lights: {graveyard: "#ff0000"}
        mqtt: {topic: ghosts/command, payload: startle}
```

A player left out of a scene stays black for that scene.

### Clip settings

| Setting | Meaning | Old equivalent |
|---|---|---|
| `file` | Path relative to the player's `media_root`. Plain text, no backslashes. | `file` |
| `level` | 0 to 150. 100 = the normalised loudness; 50 is 18 dB quieter. | `vol` |
| `mute: true` | Same as `level: 0`. | `--vol -4000`, `vol: -100` |
| `loop: true` | Loop until the scene ends. | `--loop` |
| `start` | Seek this many seconds into the file before playing. | `-l N` |
| `start_after` | Follower only: start when the **master's position** reaches this. | `wait` |
| `end_at` | Stop this clip when **its own position** reaches this. On the master it ends the scene. | `endtime` |
| `fade_in`, `fade_out` | Override the defaults for this clip. | |

`start_after`, the scene's `end_at` and cue times are positions in the
master's file, so with `start: 244` the master begins at 244, not 0. That is
how the old `wait` and `endtime` worked.

Picture rotation (`--orientation 180`) and the audio output (`-o local`) are
properties of the Pi, not of a clip, and now live in that Pi's `player.yaml`.

### Lights

Any of these forms:

```yaml
front_lights: "#ff8800"
front_lights: [255, 136, 0]
front_lights: off
front_lights: {color: "#ff8800", bri: 128}     # WLED brightness 0-255
front_lights: {preset: 3}                      # WLED preset
front_lights: {api: "FX=73&SX=120"}            # anything WLED's HTTP API takes
```

`type: wled` publishes `ON`/`OFF`/brightness to `<topic>`, the colour to
`<topic>/col` and presets/raw strings to `<topic>/api`.
`type: particle` publishes `<topic>/color/r|g|b` then `<topic>/command go`,
which is what the firmware in `Particle/` expects.

A light not mentioned in a scene keeps whatever it had.

### Cues

Fire once when the master's position passes `at`. A cue can change lights,
publish any MQTT message, or both. The Particle graveyard firmware already
listens for `ghosts/command` = `startle`.
