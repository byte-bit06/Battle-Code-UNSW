"""Toroidal maths, canonical edge keys and portal-aware stepping.

Conventions used everywhere in the bot:
  * A tile is an int index  idx = y * W + x.
  * A direction is an int   d in {0: N, 1: E, 2: S, 3: W}  (same order as
    helper.Direction.get_direction_list()).
  * An edge is keyed canonically by the tile on its west/north side plus
    E (1) or S (2):  key = idx * 4 + d.

Nothing else in the bot may use helper.Position.add_dir() for pathing,
because add_dir ignores portals.
"""

N, E, S, W = 0, 1, 2, 3
DX = (0, 1, 0, -1)
DY = (-1, 0, 1, 0)
OPPOSITE = (2, 3, 0, 1)

KELP = -1          # step() result: kelp edge (death)
UNKNOWN = -2       # step() result: portal whose partner we have not seen

EDGE_KELP = 1
EDGE_PORTAL = 2


class Geo:
    """Map geometry plus everything we know about special edges."""

    __slots__ = ("W", "H", "size", "special", "portal_pairs", "_nb", "version")

    def __init__(self, width: int, height: int):
        self.W = width
        self.H = height
        self.size = width * height
        self.special = {}        # edge key -> (EDGE_KELP, -1) | (EDGE_PORTAL, portal_id)
        self.portal_pairs = {}   # portal_id -> list of edge keys (1 or 2)
        self._nb = [None] * self.size   # lazy neighbour cache: tuple of 4 ints
        self.version = 0

    # ------------------------------------------------------------ basics --
    def idx(self, x: int, y: int) -> int:
        return (y % self.H) * self.W + (x % self.W)

    def xy(self, i: int):
        return i % self.W, i // self.W

    def plain(self, i: int, d: int) -> int:
        """Neighbour ignoring edges (wrap-around only)."""
        W = self.W
        x = i % W
        y = i // W
        return ((y + DY[d]) % self.H) * W + (x + DX[d]) % W

    def manhattan(self, a: int, b: int) -> int:
        W, H = self.W, self.H
        dx = abs(a % W - b % W)
        dy = abs(a // W - b // W)
        if dx * 2 > W:
            dx = W - dx
        if dy * 2 > H:
            dy = H - dy
        return dx + dy

    # ------------------------------------------------------------- edges --
    def edge_key(self, i: int, d: int) -> int:
        """Canonical key of the edge crossed leaving tile i in direction d."""
        if d == E or d == S:
            return i * 4 + d
        if d == W:
            return self.plain(i, W) * 4 + E
        return self.plain(i, N) * 4 + S

    def portal_exit(self, partner_key: int, d: int) -> int:
        """Tile where the head lands after crossing a portal whose partner edge
        is partner_key, travelling in direction d (direction is unchanged).

        partner vertical edge (key % 4 == E) sits between p and p+1 (east):
            travelling E -> land on the east tile, travelling W -> land on p.
        partner horizontal edge (key % 4 == S) sits between p and p+W (south):
            travelling S -> land on the south tile, travelling N -> land on p.
        """
        p = partner_key // 4
        if d == E or d == S:
            return self.plain(p, d)
        return p

    def learn_edge(self, i: int, d: int, kind: int, portal_id: int = -1) -> bool:
        """Record a kelp/portal edge. Returns True if it was new information."""
        key = self.edge_key(i, d)
        value = (kind, portal_id)
        if self.special.get(key) == value:
            return False
        self.special[key] = value
        touched = [key // 4, self.plain(key // 4, key % 4)]
        if kind == EDGE_PORTAL:
            keys = self.portal_pairs.setdefault(portal_id, [])
            if key not in keys:
                keys.append(key)
            for k in keys:   # both ends of the pair change once the partner is known
                touched.append(k // 4)
                touched.append(self.plain(k // 4, k % 4))
        nb = self._nb
        for t in touched:
            nb[t] = None
        self.version += 1
        return True

    def partner(self, key: int):
        kind, pid = self.special[key]
        for k in self.portal_pairs.get(pid, ()):
            if k != key:
                return k
        return None

    # -------------------------------------------------------- neighbours --
    def _compute(self, i: int):
        out = []
        special = self.special
        for d in (N, E, S, W):
            key = self.edge_key(i, d)
            sp = special.get(key)
            if sp is None:
                out.append(self.plain(i, d))
            elif sp[0] == EDGE_KELP:
                out.append(KELP)
            else:
                partner = self.partner(key)
                out.append(UNKNOWN if partner is None else self.portal_exit(partner, d))
        t = tuple(out)
        self._nb[i] = t
        return t

    def neighbours(self, i: int):
        """Tuple (n_N, n_E, n_S, n_W); negative entries mean KELP or UNKNOWN."""
        t = self._nb[i]
        return t if t is not None else self._compute(i)

    def step(self, i: int, d: int) -> int:
        t = self._nb[i]
        if t is None:
            t = self._compute(i)
        return t[d]

    # --------------------------------------------------------- symmetry --
    def mirror(self, i: int, hyp: str) -> int:
        """Mirror tile under hypothesis 'V' (x -> W-1-x), 'H' (y -> H-1-y) or
        'R' (180 degree rotation)."""
        W, H = self.W, self.H
        x = i % W
        y = i // W
        if hyp == "V":
            return y * W + (W - 1 - x)
        if hyp == "H":
            return (H - 1 - y) * W + x
        return (H - 1 - y) * W + (W - 1 - x)

    @staticmethod
    def mirror_dir(d: int, hyp: str) -> int:
        if hyp == "V":            # east <-> west
            return (N, W, S, E)[d]
        if hyp == "H":            # north <-> south
            return (S, E, N, W)[d]
        return OPPOSITE[d]        # rotation flips both
