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
