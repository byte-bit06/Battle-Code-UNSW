"""Parser for unswbc .map files (format checked against the real engine).

Lines:
  MAP W H
  SYMMETRY y|x|xy      (optional: y = mirror x->W-1-x, x = mirror y->H-1-y, xy = 180 deg)
  TILE x y min_gap max_gap      (tiles not listed never spawn pearls)
  EDGE index type portal_id     (type 0 empty, 1 kelp, 2 portal)
  DRAGON team length x0 y0 x1 y1 ... (team 0 = A, 1 = B; head first; the dragon
                                      id is the line order: 0, 1, 2, ... as in the engine)

Edge index layout: rows y = 0..H, each row has (W+1) horizontal edges then
(W+1) vertical edges:
  index = y*2(W+1) + x            -> the edge on the NORTH side of tile (x, y)
  index = y*2(W+1) + (W+1) + x    -> the edge on the WEST side of tile (x, y)
Row H / column W are the wrapped copies of row 0 / column 0.
"""

KELP, PORTAL = 1, 2


class MapData:
    def __init__(self):
        self.W = self.H = 0
        self.name = ""
        self.symmetry = None
        self.gaps = {}          # (x, y) -> (min_gap, max_gap)
        self.north = {}         # (x, y) -> (type, portal_id) for the edge north of the tile
        self.west = {}          # (x, y) -> (type, portal_id) for the edge west of the tile
        self.dragons = []       # (id, team "A"/"B", [(x, y), ...] head first)


def load(path):
    m = MapData()
    edges = []
    for line in open(path):
        p = line.split()
        if not p:
            continue
        k = p[0]
        if k == "MAP":
            m.W, m.H = int(p[1]), int(p[2])
        elif k == "MAP_NAME":
            m.name = " ".join(p[1:])
        elif k == "SYMMETRY":
            m.symmetry = p[1]
        elif k == "TILE":
            m.gaps[(int(p[1]), int(p[2]))] = (int(p[3]), int(p[4]))
        elif k == "EDGE":
            edges.append((int(p[1]), int(p[2]), int(p[3])))
        elif k == "DRAGON":
            team, n = int(p[1]), int(p[2])
            cells = [(int(p[3 + 2 * i]), int(p[4 + 2 * i])) for i in range(n)]
            m.dragons.append((len(m.dragons), "A" if team == 0 else "B", cells))
    S = 2 * (m.W + 1)
    for idx, typ, pid in edges:
        if typ == 0:
            continue
        y, r = divmod(idx, S)
        if r <= m.W:
            key, table = (r % m.W, y % m.H), m.north
        else:
            key, table = ((r - m.W - 1) % m.W, y % m.H), m.west
        table[key] = (typ, pid)
    return m


def edge_of(m, x, y, d):
    """(type, portal_id) of the edge on side d (0 N, 1 E, 2 S, 3 W) of tile (x, y)."""
    W, H = m.W, m.H
    if d == 0:
        return m.north.get((x, y), (0, -1))
    if d == 2:
        return m.north.get((x, (y + 1) % H), (0, -1))
    if d == 3:
        return m.west.get((x, y), (0, -1))
    return m.west.get(((x + 1) % W, y), (0, -1))
