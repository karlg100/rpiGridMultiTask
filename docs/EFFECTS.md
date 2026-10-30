# Lights and effects per scene

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
| 8 | In the Hall (Mountain King) | **Running**, orange on black | Marching waves along the eaves. Speed is a slider, so it could be cued to accelerate with the music. | | |
| 9 | Ghostbusters | **Meteor Smooth**, green | Green streaks with fading tails: slimers zipping along the roof. | | |
| 10 | Spooky Scary Skeletons | **Bouncing Balls**, white on dark purple | Bone-white balls bouncing to a bouncy song. | | |
| 11 | Seance | **Aurora**, purple and teal | A slow, shifting spirit glow. | on | 5 s at start |
| 12 | Witching Hour | **Fairytwinkle**, purple and green | Witchy sparkle that starts from a lit strip. | on | |
| 13 | Guardians Inferno | **Bpm**, Party palette | Pulses on the beat across a party palette: disco. | | |
| 14 | Ghosts n Stuff | **Juggle** | Eight coloured dots chasing with trails: EDM energy. | | |
| 15 | Stayin' Undead | **Glitter**, Party palette | Rainbow with white sparkles: a disco ball. | | |

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
