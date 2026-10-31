# Lights and effects per scene

## The controller

WLED 16.0.0 on an ESP32 at 192.168.1.186, 650 LEDs (segment 0 covers
LEDs 0-630), MQTT device topic `front_lights`. Its MQTT broker was still set
to 192.168.1.243, Home Assistant's old address, which is why it showed
offline; it now points at 192.168.1.244. The effect and palette tables in
`haunt/lights.py` were read from this controller. WLED 16 renumbered a few
effects (77 is now "Copy Segment"; Meteor Smooth became Meteor's "Smooth"
option, `o3: true` in show.yaml).

## What the eaves strip was doing

The WLED strip's last reported state (its retained `front_lights/v` message)
was effect 74, **Colortwinkles**, with palette 2, **Primary Color**: random
LEDs twinkling in one colour. The old manager only ever changed that one
colour per scene, which is why every scene looked like the same pattern.

Each scene now picks a WLED effect to match the video. The whole look goes
to WLED in one JSON-API message on `front_lights/api` (effect, speed,
intensity, palette, colours, a 1-second blend from the previous scene).
The graveyard (Particle firmware) can only take a colour, so it keeps its
per-scene colours.

## Scene by scene

| # | Scene | Front lights | Why | Mister | Fog |
|---|---|---|---|---|---|
| 1 | Pumpkin Song | **Candle Multi**, orange | Each LED flickers like its own candle: a row of lit jack-o-lanterns under the singing pumpkins. | | |
| 2 | Wicked Brew | **Popcorn**, green on purple | Pops of green rising and falling: the cauldron bubbling. | on | |
| 3 | Twas the Night | **Halloween Eyes**, red on black | Pairs of eyes open and blink at random along the eaves while the pumpkins tell the story. | | |
| 4 | Dragula APT | **Fire 2012**, Fire palette | "Burn through the witches": a real fire simulation along the house. | | |
| 5 | Cat Crow Canzonet | **Dancing Shadows**, purple and green | Spotlights sweeping past each other, like the cat and crow flitting around the witch. | on | |
| 6 | Frankenstein | **Lightning**, blue-white over dark green | Random lightning strikes for the lab scene; the Wraiths appear in the flashes. | | 6 s at start |
| 7 | Thriller | **Colorwaves**, Magred palette | Slow red/magenta waves, the Thriller palette, without strobing for 13 minutes. | | 8 s at start, 6 s at 7:00 when the zombie animation starts |
| 8 | Witching Hour | **Fairytwinkle**, purple and green | Witchy sparkle that starts from a lit strip. | on | |
| 9 | In the Hall (Mountain King) | **Running**, orange on black | Marching waves along the eaves. Speed is a slider, so it could be cued to accelerate with the music. | | |
| 10 | Ghostbusters | **Meteor** with "Smooth" on, green | Green streaks with fading tails: slimers zipping along the roof. | | |
| 11 | Spooky Scary Skeletons | **Bouncing Balls**, white on dark purple | Bone-white balls bouncing to a bouncy song. | | |
| 12 | Seance | **Aurora**, purple and teal | A slow, shifting spirit glow. | on | 5 s at start |
| 13 | Guardians Inferno | **Bpm**, Party palette | Pulses on the beat across a party palette: disco. | | |
| 14 | Ghosts n Stuff | **Juggle** | Eight coloured dots chasing with trails: EDM energy. | | |
| 15 | Stayin' Undead | **Glitter**, Party palette | Rainbow with white sparkles: a disco ball. | | |

## Hue rooms (living room, front bedroom)

The two front rooms' Philips Hue lights follow each scene too, through
`haunt hue` on home-pi (see `docs/SHOW-FILE.md` for the settings). They go
**off** whenever the show is not running, unless they have been handed to the
house with `h` in the console, which puts them back as they were. Colours match the eaves; the rooms
add movement Hue can do smoothly (no strobing: Hue limits how fast bulbs can
be changed, and it is a house, not a club).

| # | Scene | Living room | Front bedroom |
|---|---|---|---|
| 1 | Pumpkin Song | candle, orange | candle, dimmer |
| 2 | Wicked Brew | pulse green/purple (the cauldron) | drift purple/green |
| 3 | Twas the Night | low candle | slow red breathing |
| 4 | Dragula APT | fire | fire |
| 5 | Cat Crow Canzonet | drift purple/green, 3 s | the same, colours swapped |
| 6 | Frankenstein | lightning over dark blue, ~7 s | lightning over dark green, ~9 s (out of step) |
| 7 | Thriller | drift red/magenta; **at 7:00 sickly green flicker** as the zombies rise | magenta pulse; green flicker at 7:00 |
| 8 | Witching Hour | sparkle (drift on bulbs without it) | purple/green drift |
| 9 | In the Hall | orange/red pulse, 2.5 s (the march) | the same, alternate colours |
| 10 | Ghostbusters | slime-green drift | flickering slimer green |
| 11 | Spooky Scary Skeletons | bone white/purple drift, 1.5 s | white pulse |
| 12 | Seance | slow purple/teal drift | seance candle |
| 13 | Guardians Inferno | five-colour disco drift, 1 s | the same, reversed |
| 14 | Ghosts n Stuff | blue/pink pulse | cyan/magenta/blue drift, 1 s |
| 15 | Stayin' Undead | prism (drift on bulbs without it) | disco drift |

### Outdoor accents (porch, lamp post)

The two porch lights and the driveway lamp post are accents: the porch
carries each scene's second colour (joining in the march, the disco and the
lightning), and the lamp post is an old gas lamp that flickers in the
scene's colour, sputtering during the Frankenstein storm. Candy is handed
out at the end of the sidewalk, not at the door, so neither has to stay lit:
both can go dark in the lightning and pulse scenes, and off when the show
stops. (`floor:` in hue.yaml can hold a light up if that ever changes.) At 7:00 in Thriller everything outside goes
zombie green with the rooms. A white-only bulb just follows the brightness.

| # | Scene | Porch | Lamp post |
|---|---|---|---|
| 1 | Pumpkin Song | pumpkin orange | flickering gas lamp, orange |
| 2 | Wicked Brew | potion green | flicker, purple |
| 3 | Twas the Night | red | flicker, warm |
| 4 | Dragula APT | fire | fast flicker, red-orange |
| 5 | Cat Crow Canzonet | slow purple/green drift | green |
| 6 | Frankenstein | its own lightning | sputtering blue-white |
| 7 | Thriller | red (green at 7:00) | magenta pulse (green flicker at 7:00) |
| 8 | Witching Hour | purple | green flicker |
| 9 | In the Hall | orange pulse with the march | orange |
| 10 | Ghostbusters | slime green | green flicker |
| 11 | Spooky Scary Skeletons | white/purple drift | bone white |
| 12 | Seance | teal | candle |
| 13 | Guardians Inferno | disco drift | disco drift |
| 14 | Ghosts n Stuff | blue/pink pulse | cyan/magenta drift |
| 15 | Stayin' Undead | disco drift | prism |

Every setting is one line in `show.yaml` and can be changed and reloaded
(`R` in the console). The speed and intensity values are starting points;
WLED's sliders mean different things for each effect, so tune by eye.

Avoided on purpose: the strobe effects (Strobe, Strobe Mega, Blink Rainbow).
They are hard on neighbours and anyone sensitive to flashing light.

## Things worth trying later

- **Cues inside a scene.** Effects can change at a point in the master video
  (`cues: [{at: 95, lights: {front_lights: {...}}}]`), e.g. speed up the
  Mountain King march as the music accelerates, or switch Thriller to
  Lightning for the "darkness falls" section.
- **Audio-reactive effects.** WLED's sound-reactive effects (Gravcenter,
  Freqwave, ...) can follow the music if the controller has a microphone or
  receives WLED Audio Sync over UDP. Not set up; would need hardware or a
  sender.
- **WLED presets.** For looks easier to design in the WLED app, save them as
  presets and use `front_lights: {preset: N}` in a scene.

## Mister and fog

- The **pond mister** (under the wall screen) is on for the four witch
  scenes: Wicked Brew, Cat Crow Canzonet, Seance, Witching Hour. It's
  switched by a Tapo plug in Home Assistant; the automation is in
  `deploy/home-assistant/haunt-outputs.yaml`.
- The **fog machine** gets short bursts (it is limited to 10 s at a time in
  `show.yaml`): Frankenstein, Thriller, Seance. How to switch it is not
  decided; the show already publishes to `haunt/output/fog_machine/set`.
  Switch its fire button with a relay rather than its power through a smart
  plug (see the notes in that HA file).

## Sources

- WLED effect list and parameters: <https://kno.wled.ge/features/effects>
- WLED JSON API (state keys, palettes): <https://kno.wled.ge/interfaces/json-api/>
- WLED MQTT topics (`/api` accepts HTTP or JSON API syntax): <https://kno.wled.ge/interfaces/mqtt/>
