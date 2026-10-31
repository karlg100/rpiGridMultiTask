"""On/off effects driven by the show: the pond mister, the fog machine, and
anything else that can be switched over MQTT.

Each output has a topic (default ``haunt/output/<name>``). The director
publishes ``ON`` or ``OFF`` to ``<topic>/set``, retained, and whatever does
the actual switching listens there: a Home Assistant automation for a smart
plug (see deploy/home-assistant/), an ESPHome or Tasmota relay, anything.

In show.yaml a scene (or a cue) sets each output to:

    on      on for the rest of the scene
    off     off
    N       a burst of N seconds

Outputs a scene does not mention are off during it. Safety rules:

  * everything is switched off when the show stops, pauses, gives up waiting
    for players, or the director shuts down
  * an output with ``max_on`` is never left on longer than that in one go,
    whatever the show file says (meant for the fog machine)
  * the switching side should also turn the output off when
    ``haunt/director/online`` goes to ``0`` (the director's last will), in case
    the director dies with something on

Overrides (console and phone): an output can be forced ``on`` or ``off``
instead of following the show (``auto``). Forced off stays off, across
scenes and restarts, until it is put back to auto (e.g. the pond is low).
Forced on is still bound by ``max_on`` (so for the fog machine it is a burst
of max_on seconds, then back to auto), and is dropped when the show stops,
pauses or the director shuts down; while the show is stopped it can be used
to try an output.
"""

from __future__ import annotations

from typing import Callable, Dict


class Outputs:
    def __init__(self, defs: Dict[str, dict], bus, clock: Callable[[], float],
                 note: Callable[..., None]):
        self.defs = defs
        self.bus = bus
        self.clock = clock
        self.note = note
        self.state: Dict[str, bool] = {}      # what the show wants
        self.sent: Dict[str, bool] = {}       # what we last published (after overrides)
        self.override: Dict[str, str] = {}    # name -> "on" / "off"; absent = auto
        self.held = set()                      # on for the rest of the scene
        self.until: Dict[str, float] = {}      # burst end times
        self.on_since: Dict[str, float] = {}
        self.suspended = False

    # -- low level -------------------------------------------------------

    def _publish(self, name: str, on: bool) -> None:
        self.bus.publish(self.defs[name]["topic"] + "/set", "ON" if on else "OFF", retain=True)

    def effective(self, name: str) -> bool:
        o = self.override.get(name)
        if o == "on":
            return True
        if o == "off":
            return False
        return bool(self.state.get(name))

    def _sync(self, name: str, force: bool = False) -> None:
        on = self.effective(name)
        if not force and self.sent.get(name) == on:
            return
        self.sent[name] = on
        if on:
            self.on_since[name] = self.clock()
        else:
            self.on_since.pop(name, None)
        self._publish(name, on)

    def _set(self, name: str, on: bool, force: bool = False) -> None:
        self.state[name] = on
        self._sync(name, force)

    def republish(self) -> None:
        """Send every output's state again (after a broker reconnect)."""
        for name in self.defs:
            self._publish(name, self.effective(name))

    def set_override(self, name: str, mode: str) -> None:
        """mode: "on", "off" or "auto"."""
        if name not in self.defs:
            raise ValueError("no output called %r (have: %s)" % (name, ", ".join(self.defs)))
        if mode not in ("on", "off", "auto"):
            raise ValueError("output mode must be on, off or auto")
        if mode == "auto":
            self.override.pop(name, None)
        else:
            self.override[name] = mode
        self._sync(name)

    def _drop_on_overrides(self) -> None:
        for name in [n for n, o in self.override.items() if o == "on"]:
            del self.override[name]

    # -- what the director calls ------------------------------------------

    def _apply_one(self, name: str, value) -> None:
        if value is True:
            self.held.add(name)
            self.until.pop(name, None)
            self._set(name, True)
        elif value is False or value is None:
            self.held.discard(name)
            self.until.pop(name, None)
            self._set(name, False)
        else:
            secs = float(value)
            max_on = float(self.defs[name].get("max_on") or 0)
            if max_on and secs > max_on:
                secs = max_on
            self.until[name] = max(self.until.get(name, 0.0), self.clock() + secs)
            self._set(name, True)

    def scene(self, settings: dict) -> None:
        """A scene starts: set every output from the scene's settings."""
        self.suspended = False
        self.held = set()
        for name in self.defs:
            value = settings.get(name)
            if value is None and name in self.until:
                continue                       # let a running burst finish
            self._apply_one(name, value)

    def apply(self, settings: dict) -> None:
        """A cue: change only the outputs it mentions."""
        if self.suspended:
            return
        for name, value in settings.items():
            if name in self.defs:
                self._apply_one(name, value)

    def all_off(self, force: bool = False) -> None:
        self.held = set()
        self.until = {}
        self.suspended = False
        self._drop_on_overrides()
        for name in self.defs:
            self._set(name, False, force=force)

    def suspend(self) -> None:
        """Pause: everything off, but remember what the scene wanted on."""
        self.suspended = True
        self.until = {}
        self._drop_on_overrides()
        for name in self.defs:
            self._set(name, False)

    def resume(self) -> None:
        if not self.suspended:
            return
        self.suspended = False
        for name in self.held:
            self._set(name, True)

    def tick(self) -> None:
        now = self.clock()
        for name, end in list(self.until.items()):
            if now >= end:
                del self.until[name]
                if name not in self.held:
                    self._set(name, False)
        for name, since in list(self.on_since.items()):
            max_on = float(self.defs.get(name, {}).get("max_on") or 0)
            if max_on and now - since >= max_on and self.sent.get(name):
                self.held.discard(name)
                self.until.pop(name, None)
                if self.override.get(name) == "on":
                    del self.override[name]
                self._set(name, False)
                self.note("%s switched off after its %gs limit" % (self.defs[name]["label"], max_on),
                          "warning")

    def snapshot(self) -> dict:
        now = self.clock()
        out = {}
        for name, d in self.defs.items():
            left = self.until.get(name)
            since = self.on_since.get(name)
            max_on = float(d.get("max_on") or 0)
            burst = round(left - now, 1) if left and name not in self.held else None
            if self.override.get(name) == "on" and max_on and since is not None:
                burst = round(max(0.0, since + max_on - now), 1)
            out[name] = {
                "label": d["label"],
                "on": self.effective(name),
                "burst": burst if self.effective(name) else None,
                "override": self.override.get(name),
                "show": bool(self.state.get(name)),
            }
        return out
