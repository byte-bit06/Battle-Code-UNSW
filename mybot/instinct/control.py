"""Time-expanded board control D[d][v] (instinct_engine.md 4.1).

Reduced to one job: producing the frontier that corridor_count aims at. The
volume/depth scoring this module used to feed the key is GONE - MEASURED on the
shipped path, free_volume was harmful on both board types (chamber 28 vs 16
without it, open 20 vs 17), and escape_depth before it ablated to nothing. Built
ONCE per turn, never per candidate.

D[me][v]     moves we need to stand on v, our own tail releasing over time
D[enemy][v]  ROUNDS the first enemy needs, its affordable sprint included
margin(v)    D[enemy][v] - D[me][v].  margin == 0 is contested: a shared
             arrival is a mutual kill, so it is neutral and dangerous, never ours.

Shared with Flood_Engine: attacking is this same computation run on a target.
"""

import config
import routing
from instinct.state import TIER_A

CONTESTED = 0


class Control:
    __slots__ = ("st", "tier", "horizon", "me", "enemy", "enemy_by")

    def __init__(self, st, tier, horizon, me, enemy, enemy_by):
        self.st = st
        self.tier = tier
        self.horizon = horizon
        self.me = me              # tile -> our moves to reach it
        self.enemy = enemy        # tile -> rounds for the first enemy to reach it
        self.enemy_by = enemy_by  # tile -> which enemy that is

    def margin(self, v):
        """> 0 we get there first, 0 contested (mutual kill), < 0 theirs.
        Unreachable-by-them counts as a large positive margin."""
        mine = self.me.get(v)
        if mine is None:
            return None
        return self.enemy.get(v, 10 ** 6) - mine

    def contested(self, v):
        return self.margin(v) == CONTESTED

    def ours(self, v):
        m = self.margin(v)
        return m is not None and m > 0

    def free_set(self, horizon=None):
        """free[H] (4.2): tiles we can reach that no enemy can reach by then.
        This is what "the open board" means once enemies exist - a geometric
        distance ring is a claim about space, not about safety."""
        h = self.horizon if horizon is None else horizon
        return {v for v, d in self.me.items() if d <= h and self.ours(v)}

    def free_frontier(self, horizon=None):
        """The OUTER edge of free[H]: the furthest tiles we still own within the
        horizon. Corridor count must run to this, not to the whole free set -
        the tile under our nose is free too, and escaping to it is not escaping."""
        f = self.free_set(horizon)
        if not f:
            return f
        far = max(self.me[v] for v in f)
        if far == 0:
            return set()
        return {v for v in f if self.me[v] == far}

def _enemy_rounds(st, tier, horizon, node_cap):
    """tile -> (rounds, dragon id) for the first enemy able to stand there."""
    geo = st.geo
    out, by = {}, {}
    for d in st.enemies:
        speed = d.sprint(tier)
        walls = set(st.body)
        for o in st.enemies + st.allies:
            if o is not d:
                walls.update(o.segs)
        own = {t: i for i, t in enumerate(d.segs)}
        dist, _p, _u = routing.bfs(geo, d.head, walls, own, d.length, node_cap,
                                   horizon * speed)
        for v, steps in dist.items():
            rounds = (steps + speed - 1) // speed
            if not d.acts_before:
                pass                      # acts after us this round: same round counts
            if rounds < out.get(v, 10 ** 6):
                out[v] = rounds
                by[v] = d.id
    return out, by


def build_control(st, horizon=None, tier=TIER_A, node_cap=None):
    horizon = config.INSTINCT_HORIZON if horizon is None else horizon
    node_cap = config.INSTINCT_NODE_CAP if node_cap is None else node_cap
    geo = st.geo
    walls = st.blocked(tier, include_own=False)
    mine, _p, _u = routing.bfs(geo, st.head, walls, st.own_index(), st.L,
                               node_cap, horizon, release=st.release(tier))
    enemy, by = _enemy_rounds(st, tier, horizon, node_cap)
    return Control(st, tier, horizon, mine, enemy, by)
