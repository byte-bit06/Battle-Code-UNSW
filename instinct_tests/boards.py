"""ASCII board fixtures for Instinct_Engine tests.

    . . K . .        K  kelp (all four edges of that tile)
    . H h . .        H  our head          h  our neck (the segment behind H)
                     b  our body
    . b b K .        E  enemy head        e  enemy body
    . . . e E        T  teammate head     t  teammate body
                     P  pearl             O  "the open board" for corridor tests
                     .  empty

Cells may be separated by spaces (as above) or written solid ("..K..").
Body order is walked from the head. Where the walk is ambiguous (two body
tiles touch the head) say which one is the neck with `h`, or number every
segment (1 = next to the head, 2 = behind it, ...). F/G are extra enemies,
with bodies f/g.

Kelp sits on EDGES in this game, so a K cell is shorthand for "all four edges
of this tile are kelp" - it is a solid block. The board does not wrap by
default (`border_kelp=True` walls the outside in), because a wrapping 5x4
fixture rarely means what the person writing it intended.

Every builder takes explicit ids so a scenario can be run in both turn orders:
    build(BOARD, my_id=5, enemy_ids=[3])   enemies move BEFORE us
    build(BOARD, my_id=5, enemy_ids=[9])   enemies move AFTER us
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mybot"))

from geometry import Geo, N, E, S, W, EDGE_KELP        # noqa: E402
from instinct.state import Dragon, State               # noqa: E402

OUR_HEAD, OUR_NECK, OUR_BODY = "H", "h", "b"
ENEMY_HEADS = "EFG"
ENEMY_BODIES = "efg"
MATE_HEAD, MATE_BODY = "T", "t"
KELP, PEARL, OPEN, EMPTY = "K", "P", "O", "."


def parse_grid(text):
    """-> (rows of cells, W, H). Accepts spaced or solid rows."""
    rows = [r for r in (line.rstrip() for line in text.strip("\n").splitlines()) if r.strip()]
    cells = []
    for r in rows:
        cells.append(r.split() if " " in r.strip() else list(r.strip()))
    W = max(len(r) for r in cells)
    for r in cells:
        r.extend([EMPTY] * (W - len(r)))
    return cells, W, len(cells)


def _chain(geo, head, tiles, label):
    """Order a set of body tiles into a chain starting next to the head."""
    remaining = set(tiles)
    body = [head]
    cur = head
    while remaining:
        nxt = [n for n in geo.neighbours(cur) if n >= 0 and n in remaining]
        if not nxt:
            raise ValueError(f"{label}: body is not connected at {geo.xy(cur)}")
        if len(nxt) > 1:
            raise ValueError(f"{label}: ambiguous body order at {geo.xy(cur)}; "
                             f"number the segments instead")
        cur = nxt[0]
        remaining.discard(cur)
        body.append(cur)
    return body


def build(text, my_id=5, enemy_ids=None, mate_ids=None, lengths=None,
          my_length=None, border_kelp=True, longest_ally=False, round_num=10):
    """ASCII board -> instinct.state.State.

    enemy_ids  ids for E, F, G in that order (default 9, 10, 11: they move AFTER us)
    lengths    {'E': 12} to give a dragon a length beyond what is drawn
    my_length  our true length, if longer than the segments drawn
    """
    cells, bw, bh = parse_grid(text)          # bw/bh, not W/H: W is the WEST direction
    geo = Geo(bw, bh)
    enemy_ids = list(enemy_ids or [9, 10, 11])
    mate_ids = list(mate_ids or [1, 2, 3])
    lengths = dict(lengths or {})

    at = {}                                   # char -> [tiles]
    numbered = {}                             # digit -> tile (our body order)
    for y, row in enumerate(cells):
        for x, c in enumerate(row):
            if c == EMPTY:
                continue
            t = geo.idx(x, y)
            if c.isdigit():
                numbered[int(c)] = t
            else:
                at.setdefault(c, []).append(t)

    for t in at.get(KELP, []):                # a K cell is solid: four kelp edges
        for d in (N, E, S, W):
            geo.learn_edge(t, d, EDGE_KELP)
    if border_kelp:                           # stop the fixture wrapping around
        for x in range(bw):
            geo.learn_edge(geo.idx(x, 0), N, EDGE_KELP)
            geo.learn_edge(geo.idx(x, bh - 1), S, EDGE_KELP)
        for y in range(bh):
            geo.learn_edge(geo.idx(0, y), W, EDGE_KELP)
            geo.learn_edge(geo.idx(bw - 1, y), E, EDGE_KELP)

    if OUR_HEAD not in at:
        raise ValueError("board has no H (our head)")
    head = at[OUR_HEAD][0]
    if numbered:
        body = [head] + [numbered[i] for i in sorted(numbered)]
    elif OUR_NECK in at:                      # h names the segment behind the head
        neck = at[OUR_NECK][0]
        body = [head] + _chain(geo, neck, at.get(OUR_BODY, []), "our dragon")
    else:
        body = _chain(geo, head, at.get(OUR_BODY, []), "our dragon")

    enemies = []
    for i, hc in enumerate(ENEMY_HEADS):
        if hc not in at:
            continue
        eh = at[hc][0]
        segs = _chain(geo, eh, at.get(ENEMY_BODIES[i], []), f"enemy {hc}")
        did = enemy_ids[i] if i < len(enemy_ids) else 90 + i
        enemies.append(Dragon(did, eh, segs, max(lengths.get(hc, len(segs)), 2),
                              False, acts_before=did < my_id))
    allies = []
    if MATE_HEAD in at:
        for i, mh in enumerate(at[MATE_HEAD]):
            segs = _chain(geo, mh, at.get(MATE_BODY, []), "teammate") if i == 0 else [mh]
            did = mate_ids[i] if i < len(mate_ids) else 80 + i
            allies.append(Dragon(did, mh, segs, max(lengths.get(MATE_HEAD, len(segs)), 2),
                                 True, acts_before=did < my_id))

    st = State(geo, my_id, head, body, my_length or len(body), enemies, allies,
               at.get(PEARL, []), [round_num] * (bw * bh), round_num,
               longest_ally=longest_ally)
    st.open_tiles = set(at.get(OPEN, []))
    return st


def both_orders(text, **kw):
    """The same board twice: enemies with LOWER ids (they commit first), then
    HIGHER ids (they react to us). Tempo logic is half the engine, so every
    scenario should pass in both."""
    kw.pop("enemy_ids", None)
    my_id = kw.get("my_id", 5)
    return [("enemies first", build(text, enemy_ids=[my_id - 4, my_id - 3, my_id - 2], **kw)),
            ("enemies after", build(text, enemy_ids=[my_id + 4, my_id + 5, my_id + 6], **kw))]


def show(st, mark=()):
    """Render a State back to ASCII (debugging aid)."""
    geo = st.geo
    grid = [[EMPTY] * geo.W for _ in range(geo.H)]
    for i, t in enumerate(st.body):
        x, y = geo.xy(t)
        grid[y][x] = OUR_HEAD if i == 0 else (OUR_NECK if i == 1 else OUR_BODY)
    for n, d in enumerate(st.enemies):
        for i, t in enumerate(d.segs):
            x, y = geo.xy(t)
            grid[y][x] = ENEMY_HEADS[n] if i == 0 else ENEMY_BODIES[n]
    for d in st.allies:
        for i, t in enumerate(d.segs):
            x, y = geo.xy(t)
            grid[y][x] = MATE_HEAD if i == 0 else MATE_BODY
    for t in range(geo.size):                 # kelp is on edges: a solid tile is K
        if all(geo.step(t, d) < 0 for d in (N, E, S, W)):
            x, y = geo.xy(t)
            grid[y][x] = KELP
    for t in st.pearls:
        x, y = geo.xy(t)
        grid[y][x] = PEARL
    for t in mark:
        x, y = geo.xy(t) if isinstance(t, int) else t
        grid[y][x] = "*"
    return "\n".join(" ".join(r) for r in grid)
