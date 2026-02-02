from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from PositionalObjects.Map import Map
from PositionalObjects.Player import Player


@dataclass
class PlayerRoundState:
    player_key: str
    player_all: Player
    player_attack: Player
    player_defense: Player
    map_obj: Optional[Map]

    round_id: int = 0
    round_in_game: int = 0
    round_start: Optional[datetime] = None
    game_id: Optional[str] = None
    player_team_id: Optional[str] = None
    current_side: Optional[str] = None

    game_agents: Dict[str, str] = field(default_factory=dict)
    round_start_weapon: Dict[int, str] = field(default_factory=dict)
    round_in_game_by_round: Dict[int, int] = field(default_factory=dict)
    round_game_id_by_round: Dict[int, str] = field(default_factory=dict)


@dataclass
class MapState:
    map_name: str
    map_obj: Optional[Map]
    players: Dict[str, PlayerRoundState] = field(default_factory=dict)

    def get_player_state(self, player_key: str, display_name: str) -> PlayerRoundState:
        if player_key not in self.players:
            self.players[player_key] = PlayerRoundState(
                player_key=player_key,
                player_all=Player(player_id=player_key, name=display_name),
                player_attack=Player(player_id=player_key, name=display_name),
                player_defense=Player(player_id=player_key, name=display_name),
                map_obj=self.map_obj,
            )
        return self.players[player_key]
