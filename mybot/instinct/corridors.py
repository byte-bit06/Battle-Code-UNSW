"""Escape connectivity: corridor count, cut tiles, chambers (4.3).

Volume is a lagging signal; connectivity is a leading one. Three dragons
closing in show up here several turns before flood-fill volume notices.

Tiles are ints (y * W + x) everywhere inside the bot. cut_tile() returns an
(x, y) pair, because that is what a board fixture is written in.
"""

import config
import routing
from instinct.state import TIER_A

BIG = 10 ** 6


def _tile(st, t):
    """Accept a tile index or an (x, y) pair."""
    return st.geo.idx(t[0], t[1]) if isinstance(t, tuple) else t


def open_region(st, head=None, open_dist=None):
    """The open board: tiles at least `open_dist` away from our head, measured
    with kelp only (dragons move, kelp does not)."""
    head = st.head if head is None else _tile(st, head)
    if st.open_tiles:
        return set(st.open_tiles)
    open_dist = config.INSTINCT_OPEN_DIST if open_dist is None else open_dist
    geo = st.geo
    seen = {head: 0}
    queue = [head]
    qi = 0
    out = set()
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        k = seen[cur] + 1
        for n in geo.neighbours(cur):
            if n < 0 or n in seen:
                continue
            seen[n] = k
            if k >= open_dist:
                out.add(n)
            else:
                queue.append(n)
    return out


def _path_out(st, head, goal_set, removed, blocked, own, L, release, radius=None):
    """Shortest path from head into goal_set, avoiding `removed`. -> [tiles]."""
    geo = st.geo
    walls = blocked | removed
    dist = {head: 0}
    parent = {}
    queue = [head]
    qi = 0
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        if cur in goal_set:
            path = [cur]
            while path[-1] != head:
                path.append(parent[path[-1]])
            path.reverse()
            return path
        k = dist[cur] + 1
        if k > (config.INSTINCT_CORRIDOR_RADIUS if radius is None else radius):
            continue
        for n in geo.neighbours(cur):
            if n < 0 or n in dist or n in walls:
                continue
            oi = own.get(n)
            if oi is not None and k <= L - oi:
                continue
            if n in release and k <= release[n]:
                continue
            dist[n] = k
            parent[n] = cur
            queue.append(n)
    return None


def corridor_count(st, head=None, k_max=3, open_dist=None, tier=TIER_A, extra_blocked=(),
                   open_set=None, radius=None):
    """How many independent ways out of here (cheap min-cut estimate, 4.3).

    0 = already sealed, sprint or trade. 1 = one cut tile stands between us and
    the open board. >= 2 = healthy, Tarjan can stay off.

    `open_set` is the joint-envelope free set (control.free_set(), 4.2): the
    tiles no enemy can reach by the horizon. Pass it whenever enemies exist -
    escaping into space they already cover is not an escape. With no open_set
    the target is the geometric ring, which is only right on an empty board.
    """
    head = st.head if head is None else _tile(st, head)
    if open_set is not None:
        goal = set(open_set) - {head}
        if not goal:
            return 0                      # nowhere safe to run to: already sealed
    else:
        goal = open_region(st, head, open_dist)
        if not goal:
            return k_max
    blocked = st.blocked(tier, include_own=False) | set(extra_blocked)
    own = st.own_index()
    own.pop(head, None)
    release = st.release(tier)
    removed = set()
    for k in range(k_max):
        p = _path_out(st, head, goal, removed, blocked, own, st.L, release, radius)
        if p is None:
            return k
        removed.update(p[1:-1])           # interior only: keep head and the exit
    return k_max


def cut_tile(st, head=None, open_dist=None, tier=TIER_A):
    """The single tile that seals us in, as (x, y), or None if there isn't
    exactly one. Only meaningful when corridor_count == 1."""
    head = st.head if head is None else _tile(st, head)
    goal = open_region(st, head, open_dist)
    if not goal:
        return None
    blocked = st.blocked(tier, include_own=False)
    own = st.own_index()
    own.pop(head, None)
    release = st.release(tier)
    p = _path_out(st, head, goal, set(), blocked, own, st.L, release)
    if p is None:
        return None                        # already sealed: nothing to guard
    for t in p[1:-1]:
        if _path_out(st, head, goal, {t}, blocked, own, st.L, release) is None:
            return st.geo.xy(t)
    return None


def region(st, head=None, tier=TIER_A, cap=None, extra_blocked=()):
    """The connected free area our head sits in (a chamber, if sealed)."""
    head = st.head if head is None else _tile(st, head)
    cap = config.INSTINCT_REGION_CAP if cap is None else cap
    blocked = st.blocked(tier) | set(extra_blocked)
    blocked.discard(head)
    geo = st.geo
    seen = {head}
    queue = [head]
    qi = 0
    while qi < len(queue) and len(seen) < cap:
        cur = queue[qi]
        qi += 1
        for n in geo.neighbours(cur):
            if n < 0 or n in seen or n in blocked:
                continue
            seen.add(n)
            queue.append(n)
    return seen
