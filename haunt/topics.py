"""MQTT topic layout. Everything lives under one prefix (default ``haunt``).

    <p>/director/online        retained "1"/"0" (last will)
    <p>/director/state         retained JSON, the live show state
    <p>/director/playlist      retained JSON, the loaded show with all settings
    <p>/director/cmd           JSON commands to the director

    <p>/player/<id>/online     retained "1"/"0" (last will)
    <p>/player/<id>/state      retained JSON, what the player is doing
    <p>/player/<id>/probe      retained JSON, which show files exist + loudness
    <p>/player/<id>/cmd        JSON commands to the player

See docs/DESIGN.md for the payloads.
"""

from __future__ import annotations


class Topics:
    def __init__(self, prefix: str = "haunt"):
        self.prefix = prefix.strip("/")

    # director
    @property
    def director_online(self) -> str:
        return f"{self.prefix}/director/online"

    @property
    def director_state(self) -> str:
        return f"{self.prefix}/director/state"

    @property
    def director_playlist(self) -> str:
        return f"{self.prefix}/director/playlist"

    @property
    def director_cmd(self) -> str:
        return f"{self.prefix}/director/cmd"

    # players
    def player(self, pid, leaf: str) -> str:
        return f"{self.prefix}/player/{pid}/{leaf}"

    @property
    def all_players(self) -> str:
        return f"{self.prefix}/player/+/+"

    @property
    def everything(self) -> str:
        return f"{self.prefix}/#"

    def parse_player(self, topic: str):
        """Return (player_id, leaf) for a player topic, else None."""
        head = f"{self.prefix}/player/"
        if not topic.startswith(head):
            return None
        rest = topic[len(head):].split("/")
        if len(rest) != 2:
            return None
        return rest[0], rest[1]
