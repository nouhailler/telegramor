"""Historique de navigation (retour arrière après un saut vers un message)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    conversation_id: str
    seq: int


class NavigationHistory:
    def __init__(self, limit: int = 100) -> None:
        self._stack: list[Location] = []
        self.limit = limit

    def push(self, loc: Location | None) -> None:
        if loc is None:
            return
        if self._stack and self._stack[-1] == loc:
            return
        self._stack.append(loc)
        del self._stack[:-self.limit]

    def pop(self) -> Location | None:
        return self._stack.pop() if self._stack else None

    def can_go_back(self) -> bool:
        return bool(self._stack)

    def clear(self) -> None:
        self._stack.clear()
