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
front_lights: {preset: 3}                      # a preset saved in WLED
front_lights: {api: "FX=73&SX=120"}            # anything WLED's HTTP API takes

# a WLED effect:
front_lights: {effect: Fire 2012, palette: Fire, speed: 120, intensity: 160,
               colors: ["#ff6a00", "#300060"], bri: 200, transition: 1}
```

| Key | Meaning |
|---|---|
| `effect` | WLED effect by name ("Candle Multi") or number (102). List: <https://kno.wled.ge/features/effects> and `EFFECTS` in `haunt/lights.py`. |
| `palette` | WLED palette by name ("Fire", "Party", "Set Colors") or number. Left out = the effect's own default. |
| `colors` | Up to 3 colours: primary, secondary (usually the background), third. Slots not given are sent black. |
| `speed`, `intensity` | The effect's two sliders, 0-255. What they do differs per effect. |
| `bri` | Brightness 0-255. Left out = unchanged. |
| `transition` | Seconds to blend from the previous look. |
| `c1`, `c2`, `c3`, `o1`, `o2`, `o3` | WLED's extra effect sliders (c1/c2 0-255, c3 0-31) and checkboxes (true/false). Their meaning depends on the effect, e.g. for Meteor `o3` is "Smooth". |

A setting with an effect goes to WLED as one JSON-API message on
`<topic>/api`, so the strip changes in one step. It applies to segment 0,
which is the whole strip unless it has been split into segments in WLED.
`type: wled` otherwise publishes `ON`/`OFF`/brightness to `<topic>` and the
colour to `<topic>/col`.

`type: particle` publishes `<topic>/color/r|g|b` then `<topic>/command go`,
which is what the firmware in `Particle/` expects. It only does a colour; with
`colors`, it takes the first.

`type: hue` is a Philips Hue room (or zone). The director publishes the
scene's setting as JSON, retained, on `<prefix>/hue/<name>/set`, and
`python3 -m haunt hue` (the `haunt-hue` service) turns it into Hue bridge
calls and runs the animation. Which Hue room a light name means is set in
`/etc/haunt/hue.yaml`: a Hue room or zone, or a list of bulbs by name
(`porch: {lights: [Porch left, Porch right]}`), with an optional `floor`
(percent) below which the light never dims while the show runs, and an
optional `full: true` that runs it at full brightness whatever the scene's
`bri` and however dark its colours (the hue is kept; pulses, flicker and
lightning still dip by their `low`). The indoor rooms use `full: true` so
they can be seen from the street. The rooms switch **off** whenever the show is not
running: show stopped, director offline, or `haunt hue` stopped.

**Handing the rooms back to the house.** Press `h` in the console (or send
`hue` to the director) and `haunt hue` stops driving the Hue lights and puts
each bulb back the way it was before the show took it over (on/off,
brightness, colour or white temperature, effect). From then on the Hue app,
switches and automations work normally, while the show keeps running on the
screens, WLED and outputs. `h` again gives them back to the show, which first
remembers the house's settings afresh. The choice survives restarts of the
director and of `haunt hue` (it is in `show.state.json` and the retained
`<prefix>/hue/control`), and the console shows `Hue rooms ● SHOW` or
`● HOUSE`.

```yaml
lights:
  living_room: {type: hue}
  front_bedroom: {type: hue}

# in a scene:
      living_room: "#ff6a00"                                   # solid
      living_room: off
      living_room: {color: "#ff6a00", effect: candle, bri: 200} # Hue's own effect
      living_room: {colors: ["#7a00ff", "#00ff60"], animation: drift, period: 3}
```

| Setting | Meaning |
|---|---|
| `color` / `colors` | 1 to 8 colours, spread across the bulbs (bulb 1 gets colour 1, ...). A dark colour is a dim light. |
| `bri` | 0-255 (default 255) |
| `animation` | `solid` (default), `drift` (colours rotate round the bulbs, crossfading), `flicker` (each bulb on its own, flame-like), `pulse` (whole room breathes; colours advance each breath), `lightning` (held dim, random white double-flashes) |
| `effect` | Hue's built-in effects, on bulbs that have them: `candle fire sparkle prism opal glisten underwater cosmos sunbeam enchant`. Bulbs without it get `flicker` (candle, fire) or `drift` (others). `haunt hue --list` shows what each bulb has. |
| `period` | seconds per step: drift 4, flicker 0.6, pulse 3 (min 2), lightning 8 (min 1.5) by default |
| `low` | dimmest point as a fraction of `bri`: flicker 0.35, pulse 0.15, lightning 0.12 |
| `flash` | lightning flash colour (default `#d8e4ff`) |
| `transition` | fade into the setting, seconds (default 1) |

Hue takes about 10 bulb commands and 1 room command a second, so the
animations are slow-ish by design: no strobing.

### The flood lights (`type: floods`)

`type: floods` is a row of lights in Home Assistant: the 14 AiDot solar
floods across the front of the house, from the Window end to the Wall
end. The director publishes the scene's setting as JSON, retained, on
`<prefix>/floods/<name>/set`, and `python3 -m haunt floods` (the
`haunt-floods` service) works out every light's colour and brightness a few
times a second and sends the ones that changed to Home Assistant
(`light.turn_on` / `turn_off`). Which entities make up the row, in order, is
set in `/etc/haunt/floods.yaml` (`deploy/floods.example.yaml`). The row goes
**off** whenever the show is not running (or `idle:` says otherwise).

```yaml
lights:
  floods: {type: floods}

# in a scene:
      floods: "#ff6a00"                                            # solid
      floods: off
      floods: {colors: ["#ff6a00", "#5a00a0"], pattern: blocks}     # Window half / Wall half
      floods: {color: "#20ff20", animation: chase, width: 3, period: 2}
      floods: {color: "#003010", animation: lightning, period: 4, low: 0.3}
```

| Setting | Meaning |
|---|---|
| `color` / `colors` | 1 to 15 colours, laid along the row by `pattern`. A dark colour is a dim light. |
| `pattern` | `alternate` (default: 1, 2, 1, 2 ...), `blocks` (one block per colour; two colours = Window half and Wall half), `gradient` (blended along the row) |
| `bri` | 0-255 (default 255) |
| `animation` | `solid` (default), `drift` (pattern crawls along the row), `flicker` (each light on its own, flame-like), `pulse` (whole row breathes; colours swap each breath), `lightning` (held dim, white strikes across part or all of the row), `chase` (a group runs along the row with a tail), `wave` (brightness rolls along the row), `sparkle` (held dim, random lights flare) |
| `period` | seconds: drift = per step, flicker = how often, pulse = one breath, lightning = average gap, chase = one pass of the row, wave = one wave, sparkle = average gap per light |
| `low` | dimmest point as a fraction of `bri` |
| `direction` | `right` (Window to Wall, default), `left`, `bounce` (chase) |
| `width` | chase: how many lights in the moving group (default 3) |
| `flash` | lightning / sparkle colour |
| `transition` | fade into the setting, seconds, if the lights support it |

Each command goes to a light over Bluetooth through Home Assistant, so keep
animations gentle: a period of a second or more per step is safe.

A light not mentioned in a scene keeps whatever it had.

### Outputs (mister, fog machine, ...)

Defined once at the top of the file:

```yaml
outputs:
  pond_mister: {label: mister}
  fog_machine: {label: fog, max_on: 10}
```

| Key | Meaning |
|---|---|
| `topic` | Default `haunt/output/<name>`. The director publishes `ON`/`OFF` to `<topic>/set`, retained. |
| `label` | Name shown in the console; its first letter marks scenes in the playlist. |
| `max_on` | Never on for longer than this many seconds in one go, whatever a scene says. |

Then in a scene, or in a cue:

```yaml
    outputs: {pond_mister: on, fog_machine: 5}   # mister for the whole scene, a 5 s fog burst
    cues:
      - {at: 90, outputs: {fog_machine: 4}}      # another burst 90 s into the master clip
      - {at: 120, outputs: {pond_mister: off}}
```

`on` = on until the scene ends; a number = a burst of that many seconds;
`off`. Outputs a scene does not mention are off during it. Everything is
switched off when the show is paused, stopped or the director shuts down.

**Overriding from the console.** `f` (fog) and `w` (mister) in the console,
or the Fog & mister card on the phone page, set an output to **auto** (follow
the show), **forced on** or **forced off** (director command
`{"cmd":"output","name":"fog_machine","value":"on|off|auto"}`; without a
value it steps auto > on > off > auto). Forced off stays off through every
scene and across restarts until it is put back to auto. Forced on still obeys
`max_on`, so for the fog machine it is one 10 s burst and then back to auto;
it is dropped when the show stops or pauses, but works while the show is
stopped, to try an output.

Something else does the actual switching by listening on `<topic>/set`. For a
plug in Home Assistant, see `deploy/home-assistant/haunt-outputs.yaml`.

### Cues

Fire once when the master's position passes `at`. A cue can change lights,
switch outputs, publish any MQTT message, or all three. The Particle graveyard firmware already
listens for `ghosts/command` = `startle`.
