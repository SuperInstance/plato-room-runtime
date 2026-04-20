"""Room runtime — lifecycle management, middleware pipeline, hooks, and event processing."""
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from collections import defaultdict, deque
from enum import Enum

class RoomPhase(Enum):
    CREATED = "created"
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    DRAINING = "draining"
    SHUTTING_DOWN = "shutting_down"
    TERMINATED = "terminated"

class EventType(Enum):
    TILE_CREATED = "tile_created"
    TILE_UPDATED = "tile_updated"
    TILE_DELETED = "tile_deleted"
    AGENT_JOINED = "agent_joined"
    AGENT_LEFT = "agent_left"
    ROOM_PHASE_CHANGE = "room_phase_change"
    ROOM_ERROR = "room_error"
    HEARTBEAT = "heartbeat"

@dataclass
class RoomEvent:
    event_type: EventType
    room_id: str = ""
    agent_id: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str = ""
    metadata: dict = field(default_factory=dict)

@dataclass
class MiddlewareResult:
    pass_through: bool = True
    transformed_event: Optional[RoomEvent] = None
    response: Any = None
    error: str = ""

class Middleware:
    def __init__(self, name: str, handler: Callable, order: int = 0):
        self.name = name
        self.handler = handler
        self.order = order
        self.enabled = True
        self.processed_count = 0
        self.error_count = 0
        self.avg_latency_ms: float = 0.0

@dataclass
class RoomConfig:
    room_id: str
    max_tiles: int = 10000
    max_agents: int = 100
    heartbeat_interval: float = 30.0
    event_buffer_size: int = 1000
    auto_pause_on_error: bool = True
    error_threshold: int = 10
    metadata: dict = field(default_factory=dict)

class RoomRuntime:
    def __init__(self, config: RoomConfig):
        self.config = config
        self.phase = RoomPhase.CREATED
        self.agents: set[str] = set()
        self.tile_count: int = 0
        self._middleware: list[Middleware] = []
        self._hooks: dict[str, list[Callable]] = defaultdict(list)
        self._event_buffer: deque = deque(maxlen=config.event_buffer_size)
        self._error_count: int = 0
        self._event_count: int = 0
        self._start_time: float = 0.0
        self._uptime: float = 0.0
        self._metrics: dict = defaultdict(int)
        self._metrics["events_by_type"] = defaultdict(int)

    def add_middleware(self, name: str, handler: Callable, order: int = 0) -> Middleware:
        mw = Middleware(name=name, handler=handler, order=order)
        self._middleware.append(mw)
        self._middleware.sort(key=lambda m: m.order)
        return mw

    def remove_middleware(self, name: str) -> bool:
        for i, mw in enumerate(self._middleware):
            if mw.name == name:
                self._middleware.pop(i)
                return True
        return False

    def on(self, event_type: str, handler: Callable):
        self._hooks[event_type].append(handler)

    def off(self, event_type: str, handler: Callable = None):
        if handler:
            self._hooks[event_type] = [h for h in self._hooks[event_type] if h != handler]
        else:
            self._hooks[event_type].clear()

    def emit(self, event: RoomEvent) -> list[MiddlewareResult]:
        event.room_id = event.room_id or self.config.room_id
        self._event_buffer.append(event)
        self._event_count += 1
        self._metrics["events_by_type"][event.event_type.value] += 1

        results = []
        current_event = event
        for mw in self._middleware:
            if not mw.enabled:
                continue
            start = time.time()
            try:
                result = mw.handler(current_event, self)
                mw.processed_count += 1
                elapsed = (time.time() - start) * 1000
                mw.avg_latency_ms = (mw.avg_latency_ms * (mw.processed_count - 1) + elapsed) / mw.processed_count
                if isinstance(result, MiddlewareResult):
                    results.append(result)
                    if not result.pass_through:
                        return results
                    if result.transformed_event:
                        current_event = result.transformed_event
            except Exception as e:
                mw.error_count += 1
                self._error_count += 1
                results.append(MiddlewareResult(pass_through=True, error=str(e)))

        # Fire hooks
        for handler in self._hooks.get(event.event_type.value, []):
            try: handler(current_event)
            except: pass

        # Auto-pause check
        if self.config.auto_pause_on_error and self._error_count >= self.config.error_threshold:
            if self.phase == RoomPhase.ACTIVE:
                self.set_phase(RoomPhase.PAUSED)

        return results

    def set_phase(self, phase: RoomPhase):
        old = self.phase
        self.phase = phase
        if phase == RoomPhase.ACTIVE and old != RoomPhase.ACTIVE:
            self._start_time = time.time()
        if phase != RoomPhase.ACTIVE and old == RoomPhase.ACTIVE:
            self._uptime += time.time() - self._start_time
        self.emit(RoomEvent(event_type=EventType.ROOM_PHASE_CHANGE,
                           data={"old_phase": old.value, "new_phase": phase.value}))

    def join(self, agent_id: str) -> bool:
        if len(self.agents) >= self.config.max_agents:
            return False
        self.agents.add(agent_id)
        self.emit(RoomEvent(event_type=EventType.AGENT_JOINED, agent_id=agent_id))
        return True

    def leave(self, agent_id: str) -> bool:
        if agent_id not in self.agents:
            return False
        self.agents.discard(agent_id)
        self.emit(RoomEvent(event_type=EventType.AGENT_LEFT, agent_id=agent_id))
        return True

    def start(self):
        self.set_phase(RoomPhase.INITIALIZING)
        self.set_phase(RoomPhase.ACTIVE)

    def pause(self):
        self.set_phase(RoomPhase.PAUSED)

    def resume(self):
        if self.phase == RoomPhase.PAUSED:
            self.set_phase(RoomPhase.ACTIVE)

    def shutdown(self):
        self.set_phase(RoomPhase.DRAINING)
        self.set_phase(RoomPhase.SHUTTING_DOWN)
        self.agents.clear()
        self.set_phase(RoomPhase.TERMINATED)

    def heartbeat(self):
        self.emit(RoomEvent(event_type=EventType.HEARTBEAT))

    def recent_events(self, limit: int = 50) -> list[RoomEvent]:
        return list(self._event_buffer)[-limit:]

    def events_by_type(self, event_type: EventType, limit: int = 50) -> list[RoomEvent]:
        return [e for e in self._event_buffer if e.event_type == event_type][-limit:]

    @property
    def uptime_seconds(self) -> float:
        base = self._uptime
        if self.phase == RoomPhase.ACTIVE:
            base += time.time() - self._start_time
        return base

    @property
    def stats(self) -> dict:
        return {
            "room_id": self.config.room_id, "phase": self.phase.value,
            "agents": len(self.agents), "tiles": self.tile_count,
            "events": self._event_count, "errors": self._error_count,
            "middleware": len(self._middleware), "hooks": sum(len(h) for h in self._hooks.values()),
            "uptime_s": round(self.uptime_seconds, 1),
            "buffer_usage": len(self._event_buffer) / self.config.event_buffer_size,
            "events_by_type": dict(self._metrics["events_by_type"]),
        }
