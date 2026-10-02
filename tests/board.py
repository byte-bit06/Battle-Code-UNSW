"""Build a turn exactly as the judge sends it and parse it with the real helper.

Edges are keyed the way the map stores them:
    ("h", x, y) is the NORTH edge of tile (x, y)  (= south edge of (x, y-1))
    ("v", x, y) is the WEST edge of tile (x, y)   (= east edge of (x-1, y))
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mybot"))

import helper  # noqa: E402
from helper import Direction  # noqa: E402

R = helper.Constants.VISION_RADIUS
S = helper.Constants.VISION_SIZE


def edge_key(x: int, y: int, direction: Direction, width: int, height: int) -> tuple:
    """The canonical key of the edge on `direction` side of tile (x, y)."""
    if direction == Direction.NORTH:
        return ("h", x, y)
    if direction == Direction.SOUTH:
        return ("h", x, (y + 1) % height)
    if direction == Direction.WEST:
        return ("v", x, y)
    return ("v", (x + 1) % width, y)


class Board:
    def __init__(self, width: int, height: int, head: tuple[int, int],
                 my_id: int = 0, team: str = "A", facing: str = "N", length: int = 3):
        self.width, self.height = width, height
        self.head = head
        self.my_id, self.team, self.facing, self.length = my_id, team, facing, length
        self.edges: dict[tuple, str] = {}
        self.parts: list[tuple] = []
        self.pearls: set[tuple[int, int]] = set()
        # our own head is always on the board
        self.parts.append((team, my_id, head[0], head[1], facing, 1))

    # --- board setup -----------------------------------------------------
    def kelp(self, x, y, direction):
        self.edges[edge_key(x, y, direction, self.width, self.height)] = "w"
        return self

    def portal(self, portal_id, x, y, direction):
        self.edges[edge_key(x, y, direction, self.width, self.height)] = str(portal_id)
        return self

    def segment(self, x, y, dragon_id=None, team=None, facing="N", head=False):
        dragon_id = self.my_id if dragon_id is None else dragon_id
        team = self.team if team is None else team
        self.parts.append((team, dragon_id, x % self.width, y % self.height, facing, 1 if head else 0))
        return self

    def pearl(self, x, y):
        self.pearls.add((x % self.width, y % self.height))
        return self

    # --- protocol --------------------------------------------------------
    def _edge(self, key) -> str:
        return self.edges.get(key, ".")

    def text(self) -> str:
        w, h = self.width, self.height
        left, top = self.head[0] - R, self.head[1] - R
        lines = [f"ID {self.my_id}", f"TEAM {self.team}", f"MAP {w} {h}", "UNITS 64",
                 "ROUND 1", f"DIR {self.facing}", f"LENGTH {self.length}", "UNITS 1", "SONAR 0"]
        visible = set()
        for r in range(S):
            for c in range(S):
                x, y = (left + c) % w, (top + r) % h
                visible.add((x, y))
                lines.append(f"{x} {y} {1 if (x, y) in self.pearls else 0} 5")
        parts = [p for p in self.parts if (p[2], p[3]) in visible]
        lines.append(f"PARTS {len(parts)}")
        lines += [" ".join(str(v) for v in p) for p in parts]
        for r in range(S + 1):
            y = (top + r) % h
            lines.append(" ".join(self._edge(("h", (left + c) % w, y)) for c in range(S)))
        for r in range(S):
            y = (top + r) % h
            lines.append(" ".join(self._edge(("v", (left + c) % w, y)) for c in range(S + 1)))
        return "\n".join(lines) + "\n"

    def load(self):
        """Parse this board with the real helper; returns (ct, game)."""
        old = sys.stdin
        sys.stdin = io.StringIO(self.text())
        try:
            ct, game = helper.init()
            assert helper.update(ct, game)
        finally:
            sys.stdin = old
        return ct, game
