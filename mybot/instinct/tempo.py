"""Turn order and ram exposure (instinct_engine.md 4.6, 4.10).

Turns run in ascending dragon id, so a lower id has already moved this round
and a higher id still gets to react to us. Between two of our turns EVERY
other dragon moves once, so any enemy head that can reach our head's tile
kills us, whatever the lengths.
"""

import config
import routing
from instinct.state import TIER_A

BEFORE, AFTER = "before", "after"


def classify(st):
    """dragon id -> BEFORE (already moved this round) or AFTER (reacts to us)."""
    return {d.id: (BEFORE if d.id < st.my_id else AFTER)
            for d in st.enemies + st.allies}


def _reach(st, dragon, target, tier, limit):
    """Can `dragon` put its head on `target` within `limit` steps?"""
    geo = st.geo
    walls = set(st.body)
    walls.discard(target)                 # the tile we are asking about
    for o in st.enemies + st.allies:
        if o is not dragon:
            walls.update(o.segs)
    own = {t: i for i, t in enumerate(dragon.segs)}
    own.pop(target, None)
    dist, _p, _u = routing.bfs(geo, dragon.head, walls, own, dragon.length,
                               config.INSTINCT_NODE_CAP, limit, goal=target)
    return dist.get(target)


def ram_exposure(st, tile=None, tier=TIER_A):
    """How many enemy heads can reach `tile` (our head by default) before we
    move again. Any one of them is a mutual kill, so the count is what the
    lexicographic key punishes (4.6)."""
    tile = st.head if tile is None else tile
    n = 0
    for d in st.enemies:
        steps = _reach(st, d, tile, tier, d.sprint(tier))
        if steps is not None and steps <= d.sprint(tier):
            n += 1
    return n


def ram_threats(st, tile=None, tier=TIER_A):
    """The enemy dragons behind ram_exposure, for the trade policy."""
    tile = st.head if tile is None else tile
    out = []
    for d in st.enemies:
        steps = _reach(st, d, tile, tier, d.sprint(tier))
        if steps is not None and steps <= d.sprint(tier):
            out.append(d)
    return out


def yields_to_teammate(st, tile, tier=TIER_A):
    """Anti-fratricide (4.10): the higher id yields. True if a LOWER-id
    teammate holds `tile` or could still be on it this round."""
    for a in st.allies:
        if a.id > st.my_id:
            continue                       # they yield to us, not the other way
        if tile in a.segs:
            return True
        steps = _reach(st, a, tile, tier, a.sprint(tier))
        if steps is not None and steps <= a.sprint(tier):
            return True
    return False
