"""PLATO room management runtime."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Room:
    """A PLATO room."""

    name: str
    tiles: list[dict] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    temperature: str = "cold"
    created_at: float = field(default_factory=time.time)


class RoomRuntime:
    """Runtime for managing PLATO rooms."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    def create_room(self, name: str, temperature: str = "cold") -> Room:
        """Create a new room."""
        if name in self._rooms:
            raise ValueError(f"Room '{name}' already exists.")
        room = Room(name=name, temperature=temperature)
        self._rooms[name] = room
        return room

    def enter(self, room_name: str, agent_id: str) -> Room:
        """Add an agent to a room and warm the room."""
        room = self._get_room_or_raise(room_name)
        if agent_id not in room.agents:
            room.agents.append(agent_id)
        room.temperature = self._compute_temp(len(room.tiles))
        return room

    def leave(self, room_name: str, agent_id: str) -> Room:
        """Remove an agent from a room; cool to 'cold' if empty."""
        room = self._get_room_or_raise(room_name)
        if agent_id in room.agents:
            room.agents.remove(agent_id)
        if not room.agents:
            room.temperature = "cold"
        return room

    def add_tile(self, room_name: str, tile_dict: dict) -> Room:
        """Add a tile to a room and warm the room."""
        room = self._get_room_or_raise(room_name)
        room.tiles.append(tile_dict)
        room.temperature = self._compute_temp(len(room.tiles))
        return room

    def remove_tile(self, room_name: str, tile_index: int) -> Room:
        """Remove a tile from a room by index."""
        room = self._get_room_or_raise(room_name)
        if tile_index < 0 or tile_index >= len(room.tiles):
            raise IndexError(f"Tile index {tile_index} out of range.")
        room.tiles.pop(tile_index)
        room.temperature = self._compute_temp(len(room.tiles))
        return room

    def get_room(self, name: str) -> Optional[Room]:
        """Get a room by name, or None if it does not exist."""
        return self._rooms.get(name)

    def list_rooms(self) -> list[Room]:
        """List all rooms."""
        return list(self._rooms.values())

    def search_rooms(self, query: str, top_n: int = 5) -> list[Room]:
        """Search rooms by keyword overlap across room tiles."""
        query_words = set(query.lower().split())
        if not query_words:
            return []

        scored: list[tuple[int, Room]] = []
        for room in self._rooms.values():
            score = 0
            for tile in room.tiles:
                for value in tile.values():
                    if isinstance(value, str):
                        tile_words = set(value.lower().split())
                        score += len(query_words & tile_words)
            if score > 0:
                scored.append((score, room))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [room for _, room in scored[:top_n]]

    def navigate(self, room_name: str, agent_id: str) -> dict:
        """Return navigation info for a room."""
        room = self._get_room_or_raise(room_name)
        return {
            "room": room,
            "tiles_count": len(room.tiles),
            "agents": room.agents,
            "temperature": room.temperature,
        }

    def room_temp(self, room_name: str) -> str:
        """Compute temperature classification based on tile count."""
        room = self._get_room_or_raise(room_name)
        return self._compute_temp(len(room.tiles))

    def stats(self) -> dict:
        """Return aggregate statistics across all rooms."""
        total_rooms = len(self._rooms)
        total_tiles = sum(len(r.tiles) for r in self._rooms.values())
        total_agents = sum(len(r.agents) for r in self._rooms.values())
        distribution: dict[str, int] = {
            "cold": 0,
            "warm": 0,
            "hot": 0,
            "crystallized": 0,
        }
        for room in self._rooms.values():
            temp = self._compute_temp(len(room.tiles))
            distribution[temp] = distribution.get(temp, 0) + 1
        return {
            "total_rooms": total_rooms,
            "total_tiles": total_tiles,
            "total_agents": total_agents,
            "temp_distribution": distribution,
        }

    def _get_room_or_raise(self, room_name: str) -> Room:
        """Internal helper to fetch a room or raise an error."""
        room = self._rooms.get(room_name)
        if room is None:
            raise KeyError(f"Room '{room_name}' does not exist.")
        return room

    @staticmethod
    def _compute_temp(tile_count: int) -> str:
        """Compute temperature based on tile count."""
        if tile_count < 50:
            return "cold"
        if tile_count < 500:
            return "warm"
        if tile_count < 1000:
            return "hot"
        return "crystallized"
