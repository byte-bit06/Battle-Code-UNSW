"""Timed space and forced growth (instinct_engine.md 4.5).

Eating a pearl is automatic: there is no way to decline, and the tail does not
advance that turn. In the open that is a gift. In a chamber it is an attack,
because every pearl delays every later tail release by one step.
"""

import config
import routing
from instinct.state import TIER_A


def timed_space(st, tier=TIER_A, cap=None):
    """Tiles we can still reach, our own segments freeing up over time, and
    every pearl on the way DELAYING those releases (4.5).

        release_time(seg_i) = dist_from_tail(i) + pearls_eaten_before(t)

    routing.timed_area uses a fixed schedule (k > L - i), which is optimistic in
    a chamber: eating is not optional, and each pearl holds the tail still for a
    turn, so the tile we were counting on does not open when we thought.
    """
    cap = config.INSTINCT_REGION_CAP if cap is None else cap
    geo = st.geo
    blocked = st.blocked(tier, include_own=False)
    own = st.own_index()
    pearls = st.pearls
    L = st.L
    start = st.head
    dist = {start: 0}
    eaten = {start: 0}                    # pearls swallowed on the way here
    queue = [start]
    qi = 0
    while qi < len(queue) and len(dist) < cap:
        cur = queue[qi]
        qi += 1
        k = dist[cur] + 1
        ate = eaten[cur]
        for n in geo.neighbours(cur):
            if n < 0 or n in dist or n in blocked:
                continue
            oi = own.get(n)
            if oi is not None and k <= L - oi + ate:      # pearls push the release out
                continue
            dist[n] = k
            eaten[n] = ate + (1 if n in pearls else 0)
            queue.append(n)
    return min(len(dist) - 1, cap)


def walk(st, moves, tier=TIER_A):
    """Step our body along `moves` against the real rules, pearls included.
    -> routing.SimResult, or None if it collides (that includes our own tail)."""
    blocked = st.blocked(tier, include_own=False)
    return routing.simulate(st.geo, st.body, st.L, moves, st.pearls, blocked,
                            release=st.release(tier))


def forced_growth(st, moves, tier=TIER_A):
    """Length this route forces on us (pearls we cannot decline). -1 if it dies."""
    sim = walk(st, moves, tier)
    if sim is None:
        return -1
    return sim.L - st.L


def survivable_chamber(st, tiles=None, tier=TIER_A, route=None):
    """A chamber holds us only if usable_tiles >= L + pearls_on_route (4.5).
    Pearls inside are length we will be forced to take on, and there is no way
    to decline them."""
    from instinct import corridors
    tiles = corridors.region(st, tier=tier) if tiles is None else tiles
    pearls = len(self_pearls(st, set(route) if route is not None else tiles))
    return len(tiles) >= st.L + pearls


def self_pearls(st, tiles):
    return {p for p in st.pearls if p in tiles}


def corpse_pearls(dragon, geo=None):
    """Where a dead dragon's drop lands: ceil(L/2) pearls, one on every second
    segment from the head. A fresh corpse is terrain to path around."""
    return set(dragon.segs[0::2])


def route_survives(st, moves, depth=None, tier=TIER_A):
    """Walk the route, then ask whether the GROWN body still has moves left."""
    depth = config.INSTINCT_SURVIVE_DEPTH if depth is None else depth
    sim = walk(st, moves, tier)
    if sim is None:
        return False
    blocked = st.blocked(tier, include_own=False)
    ok = routing.survives(st.geo, sim.body, sim.L, blocked, depth,
                          config.INSTINCT_NODE_CAP)
    return bool(ok)
