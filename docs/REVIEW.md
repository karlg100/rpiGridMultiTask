# Review of the old orchestration code

What was read: `playlistManager-mqtt.py` (the manager that ran on home-pi) and
`omxplayer-mqtt.py` (the player on each video Pi), as of commit `62e6e8e`.
Both now live in `legacy/`; line numbers refer to those files.

## The three reported problems, and why

### 1. Flicker and jarring starts/ends

- `omxplayer-mqtt.py:91` creates a **new omxplayer process for every clip**
  and `:63` kills it at the end. Each start opens the video layer and audio
  device from scratch; each stop tears them down. That is the flicker.
- Between clips nothing owns the screen, so the Linux text console shows.
  `player.sh` works around that by running `clear > /dev/tty1` once at
  start, which only helps until something prints.
- There is no fade anywhere. Clips cut in and cut out, and the follower is
  killed mid-frame when the master finishes (`resetAllPlayers`).
- omxplayer itself is the dead end: it was removed from Raspberry Pi OS in
  2021 (Bullseye) and needs the legacy graphics stack. The player script is
  also Python 2 (`print` statements, `has_key`). So the player Pis are pinned
  to an old OS image.

### 2. Volume

- `vol` has no defined scale. The playlist uses values from `-100` to `30`,
  and three different ways of saying "silent": `vol: -99`, `vol: -100`, and
  `--vol -4000` inside `args`.
- `omxplayer-mqtt.py:96-98` sets the volume **after** the player has been
  launched, so a clip can start at omxplayer's default volume before the
  value is applied.
- Nothing accounts for the clips being mastered at different loudness, so
  every number was found by trial and error and means something different
  for each file.
- No way to change a level while the show is running.

### 3. Structure

- **No state machine.** The states are written down in a comment
  (`playlistManager-mqtt.py:426-431`) and a `state` variable is set at `:424`,
  but it is never used. The behaviour comes from a chain of `elif`s over
  string comparisons re-evaluated every 200 ms.
- **The playlist is code.** Fourteen scenes of nested dicts at `:58-408`,
  with shell-escaped paths (`"Jack-O-Lantern\ -\ Songs..."`) and raw omxplayer
  argument strings. Four stale copies of the manager sit beside it
  (`-new`, `-rewrite`, `-dict`, `-single`).
- **The protocol races.** Each setting is published as its own topic
  (`player/1/file`, `player/1/args`, `player/1/vol`, ...) followed by a
  separate `queue` command (`:476-478`). The commit "fixed issue with omx
  getting called before all params set" is this race. State comes back as a
  dozen separate topics too, and nothing ties a state report to the command
  that caused it, hence the `waitForReset` flag and repeated resets.
- **The UI is the process.** `os.system('clear')` + `pprint` once a second
  (`:581-587`). No controls, and closing the terminal stops the show.

## Bugs found

| Where | Bug |
|---|---|
| `playlistManager-mqtt.py:492` | Front-light colour is built with `"#%x%x%x"`, which does not zero-pad. `(0, 0, 190)` is sent as `#00be`; `(255, 165, 0)` as `#ffa50`. Any channel below 16 corrupts the colour: **8 of the 14 scenes** send a malformed colour to WLED. |
| `:461` | `videoStats[player] = False` replaces the player's dict with a bool. The next pass does `videoStats[player]["player_status"]` and raises `TypeError`, killing the control thread while the display loop keeps running. Triggered by a player shutting down cleanly. |
| `:529-534` | `checkPlayers()` returns `False` on both branches. (Unused.) |
| `:536-547` | `resetAllPlayers()` sleeps 3 s and is called from the 5 Hz control loop for as long as any player is not in `reset`, so the manager blocks in 3-second steps. |
| `:66`, `:224` | `endtime` is only honoured on the master. Thriller's `endtime: 225` on player 2 has never done anything. |
| `:592-593` | Shutdown calls `mqttc.disconect()` (typo) and `mqttc.stop()` (does not exist), so Ctrl-C always ends in a traceback. `:439` has `global mqrttc`. |
| `:28-36`, `:560` | `on_message` runs on paho's thread and mutates `videoStats` while the control thread reads it, with no lock. |
| `:41` | Fixed client id `"mgr"`. A second manager (or a test run) silently kicks the first off the broker. |
| `:43` | `connect()` at import time, no reconnect handling: if the broker is not up yet the script dies. |
| `omxplayer-mqtt.py:36-55` | `commandLock` does not lock: when it is already held the function prints "locked" and carries on anyway. |
| `omxplayer-mqtt.py:151`, `:158` | Trailing commas turn `video` and `player_running` into 1-tuples. It only works because `"%s" % (False,)` happens to unpack a 1-tuple back to `False`. |
| `killomx.sh` | `killall -9` four times in a row. |

## Security note

`playlistManager-mqtt.py:42` and `omxplayer-mqtt.py:120` contain the MQTT
username and password, and this repository is public on GitHub. If that
password is real, change it on the broker. The new code reads it from
`/etc/haunt/env` instead and `show.yaml` deliberately has no password in it.
