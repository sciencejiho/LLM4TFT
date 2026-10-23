"""Bounded deterministic grid routing compatible with the legacy search API."""

from __future__ import annotations

from collections import deque

Position = tuple[int, int]
MAX_GRID_CELLS = 56


def search(
    start: list[int], end: list[int], obstacles: list[list[int]], wall: tuple[int, int] = (7, 6)
) -> tuple[list[Position] | None, list[Position] | None]:
    """Return a shortest grid path and step directions with at most 56 expansions."""
    if not (0 <= wall[0] <= 7 and 0 <= wall[1] <= 6):
        raise ValueError("Routing board must fit inside the 8-by-7 arena")
    if len(start) != 2 or len(end) != 2 or len(obstacles) > MAX_GRID_CELLS:
        raise ValueError("Routing positions must describe the finite arena")
    origin, goal = (start[0], start[1]), (end[0], end[1])
    blocked = {tuple(position) for position in obstacles}
    parents: dict[Position, Position | None] = {origin: None}
    pending = deque([origin])
    for _ in range(MAX_GRID_CELLS):
        if not pending:
            return None, None
        current = pending.popleft()
        if current == goal:
            return _reconstruct(parents, current)
        for delta in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = (current[0] + delta[0], current[1] + delta[1])
            if neighbor in parents or (neighbor in blocked and neighbor != goal):
                continue
            if not (0 <= neighbor[0] <= wall[0] and 0 <= neighbor[1] <= wall[1]):
                continue
            parents[neighbor] = current
            pending.append(neighbor)
    return None, None


def _reconstruct(
    parents: dict[Position, Position | None], current: Position
) -> tuple[list[Position], list[Position]]:
    path = [current]
    for _ in range(MAX_GRID_CELLS):
        parent = parents[current]
        if parent is None:
            path.reverse()
            directions = [
                (right[0] - left[0], right[1] - left[1]) for left, right in zip(path, path[1:])
            ]
            return path, directions
        path.append(parent)
        current = parent
    raise RuntimeError("Grid path exceeded its finite cell bound")
