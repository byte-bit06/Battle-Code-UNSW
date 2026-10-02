"""The 7x7 vision as plain integers, built once per turn.

Flood fills over helper objects cost ~30M CPU points a turn in the judge's
sandbox: every step builds Positions and walks the helper's lookups. Here
each visible tile is an index 0..48 (row by row from the top left, the order
`ct.get_tiles()` uses), and each tile's four neighbours are precomputed:
KELP (-2), HIDDEN (-1) for a move that leaves vision, else the neighbour's index.
Only portal edges go through `resolve_destination`.
"""
from helper import Constants, Direction, EdgeType, Position
from core import resolve_destination

SIZE = Constants.VISION_SIZE
RADIUS = Constants.VISION_RADIUS
DIRS = Direction.get_direction_list()                    # N, E, S, W
DIR_INDEX = {d: k for k, d in enumerate(DIRS)}
_STEP = [(-1, 0), (0, 1), (1, 0), (0, -1)]                # (row, col) per DIRS
HIDDEN, KELP = -1, -2   # neighbour codes: outside vision / unknown portal, and kelp

_cache: tuple[object, "Grid"] | None = None


class Grid:
    __slots__ = ("ct", "tiles", "left", "top", "width", "height", "head",
                 "nbr", "parts", "own", "pearl", "length", "_order")

    def __init__(self, ct, game_width: int, game_height: int):
        self.ct = ct
        self.tiles = ct.get_tiles()
        here = ct.get_position()
        self.left, self.top = here.x - RADIUS, here.y - RADIUS
        self.width, self.height = game_width, game_height
        self.head = RADIUS * SIZE + RADIUS
        self.length = ct.get_length()
        my_id = ct.get_id()
        n = len(self.tiles)
        self.nbr = [None] * n
        self.parts = [t.get_dragon() for t in self.tiles]
        self.own = [p is not None and p.get_id() == my_id for p in self.parts]
        self.pearl = [t.has_pearl() for t in self.tiles]
        self._order = None
        for i, tile in enumerate(self.tiles):
            row, col = divmod(i, SIZE)
            out = [-1, -1, -1, -1]
            for k, direction in enumerate(DIRS):
                kind = tile.get_edge(direction).edge_type   # `is` checks: Enum.value is slow
                if kind is EdgeType.KELP:
                    out[k] = KELP
                    continue
                if kind is EdgeType.PORTAL:
                    out[k] = self.index(resolve_destination(ct, tile.get_position(), direction))
                    continue
                dr, dc = _STEP[k]
                r, c = row + dr, col + dc
                if 0 <= r < SIZE and 0 <= c < SIZE:
                    out[k] = r * SIZE + c
            self.nbr[i] = out

    def index(self, pos: Position | None) -> int:
        """Local index of a board position, or -1 if it is not in vision."""
        if pos is None:
            return -1
        c = (pos.x - self.left) % self.width
        r = (pos.y - self.top) % self.height
        return r * SIZE + c if c < SIZE and r < SIZE else -1

    def position(self, i: int) -> Position:
        return self.tiles[i].get_position()

    # ------------------------------------------------------------ own body
    def body_order(self) -> list[int]:
        """Index from the head (0) to the tail (L-1) of each own segment we
        can place, else -1. See queen_guard.own_body_order for the rules."""
        if self._order is not None:
            return self._order
        n = len(self.tiles)
        order = [-1] * n
        points_to = [-1] * n          # own body segment -> tile it faces
        pointed_by = [-1] * n         # tile -> own body segment facing it
        for i in range(n):
            part = self.parts[i]
            if self.own[i] and not part.is_head():
                j = self.nbr[i][DIR_INDEX[part.get_dir()]]
                points_to[i] = j
                if j >= 0:
                    pointed_by[j] = i
        i, k = self.head, 0
        while i >= 0 and order[i] < 0:
            order[i] = k
            i, k = pointed_by[i], k + 1
        for i in range(n):
            if not self.own[i] or self.parts[i].is_head() or order[i] >= 0 or pointed_by[i] >= 0:
                continue
            if HIDDEN in self.nbr[i]:
                continue  # a hidden neighbour could hold the segment before this one
            k = self.length - 1
            while i >= 0 and self.own[i] and order[i] < 0:
                order[i] = k
                i, k = points_to[i], k - 1
            break
        self._order = order
        return order

    # ------------------------------------------------------------ queries
    def exits(self, here: int, dest: int) -> int:
        """Safe moves from `dest` after stepping there from `here`; every
        dragon segment (tail included) blocks."""
        return sum(1 for j in self.nbr[dest]
                   if j >= 0 and j != here and j != dest and self.parts[j] is None)

    def area(self, dest: int, limit: int, order: list[int] | None) -> int:
        """Tiles reachable from `dest` (entered on move 1), up to `limit`.
        Own segment i is passable on move t when t > L - i (+1 if we eat the
        pearl on `dest`). With `order` None the whole body is a wall."""
        length = self.length
        stall = 1 if self.pearl[dest] else 0
        parts, own, nbr = self.parts, self.own, self.nbr
        seen = {dest}
        frontier = [dest]
        move, count = 1, 0
        while frontier and count < limit:
            count += len(frontier)
            move += 1
            nxt_frontier = []
            for i in frontier:
                for j in nbr[i]:
                    if j < 0 or j in seen:
                        continue
                    if parts[j] is not None:
                        if order is None or not own[j] or order[j] < 0:
                            continue
                        if move <= length - order[j] + stall:
                            continue  # still occupied; another route may reach it later
                    seen.add(j)
                    nxt_frontier.append(j)
            frontier = nxt_frontier
        return min(count, limit)


def grid_for(ct, game) -> Grid:
    """This turn's grid, built on first use and reused until the next turn."""
    global _cache
    vision = ct.get_vision()
    if _cache is None or _cache[0] is not vision:
        width, height = game.get_map_size()
        _cache = (vision, Grid(ct, width, height))
    return _cache[1]
