"""Build fake turns (Snapshot + WorldMemory) without the game engine.

Coordinates are (x, y) tuples; directions are ints 0 N, 1 E, 2 S, 3 W.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mybot"))

import geometry  # noqa: E402
import memory    # noqa: E402
import snapshot  # noqa: E402


class NoDeadline:
    def check(self):
        pass

    def remaining(self):
        return 1.0


def _dir_between(geo, a, b):
    """Direction d such that stepping from a lands on b."""
    for d in range(4):
        if geo.step(a, d) == b:
            return d
    for d in range(4):          # crosses kelp in a random test board: plain adjacency
        if geo.plain(a, d) == b:
            return d
    raise ValueError(f"tiles {geo.xy(a)} and {geo.xy(b)} are not adjacent")


def make(W, H, me, my_id=5, others=(), pearls=(), countdowns=None, default_cd=50,
         kelp=(), portals=(), round_num=10, my_len=None, visible=None, mem=None,
         update_memory=True):
    """Create (snap, mem).

    me       : list of (x, y) for our dragon, head first
    others   : list of (dragon_id, [(x, y) head first], is_teammate)
    kelp     : list of (x, y, d) kelp edges
    portals  : list of (x, y, d, portal_id) portal edges
    visible  : iterable of (x, y); default = the whole map
    """
    if mem is None:
        mem = memory.WorldMemory(W, H)
    geo = mem.geo
    for x, y, d in kelp:
        geo.learn_edge(geo.idx(x, y), d, geometry.EDGE_KELP)
    for x, y, d, pid in portals:
        geo.learn_edge(geo.idx(x, y), d, geometry.EDGE_PORTAL, pid)

    occ = {}

    def place(cells, did, mate):
        tiles = [geo.idx(x, y) for x, y in cells]
        for i, t in enumerate(tiles):
            if i == 0:
                d = _dir_between(geo, tiles[1], t) if len(tiles) > 1 else 0
            else:
                d = _dir_between(geo, t, tiles[i - 1])
            occ[t] = (did, i == 0, mate, d)
        return tiles

    my_tiles = place(me, my_id, True)
    for did, cells, mate in others:
        place(cells, did, mate)

    if visible is None:
        vis = set(range(W * H))
    else:
        vis = {geo.idx(x, y) for x, y in visible}
    cds = {t: default_cd for t in vis}
    for (x, y), c in (countdowns or {}).items():
        cds[geo.idx(x, y)] = c
    pearl_tiles = [geo.idx(x, y) for x, y in pearls]
    head_dir = occ[my_tiles[0]][3]
    snap = snapshot.Snapshot(round_num, W, H, my_id, my_len or len(me), head_dir,
                             my_tiles[0], occ, vis, cds, pearl_tiles)
    snap.finalize(geo)
    if update_memory:
        mem.update(snap)
    return snap, mem


def xy(geo, t):
    return geo.xy(t)
