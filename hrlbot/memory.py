"""Persistent world memory.

A dragon's program keeps running between turns, so this object survives for
the whole life of the dragon. Split children are new processes and start
empty. Flat lists indexed by tile are used instead of dicts of tuples because
they are much cheaper on the judge's metered interpreter.
"""

import config
from geometry import Geo, EDGE_KELP
from symmetry import SymmetryTracker

SRC_SEEN = 1
SRC_MIRROR = 2


class WorldMemory:
    __slots__ = ("geo", "W", "H", "size", "cd_val", "cd_round", "cd_src",
                 "seen_round", "pearls", "sym", "_mirrored_keys", "_mirror_version",
                 "reports", "claims", "enemy_reports", "best_len_heard", "best_len_round",
                 "prev_occ", "deaths_seen", "block_seen", "nbx", "explore_goal")

    def __init__(self, width: int, height: int):
        self.geo = Geo(width, height)
        self.W = width
        self.H = height
        self.size = width * height
        self.cd_val = [None] * self.size     # last known countdown (-1 = never spawns)
        self.cd_round = [0] * self.size      # round that countdown was valid for
        self.cd_src = [0] * self.size        # SRC_SEEN or SRC_MIRROR
        self.seen_round = [-1] * self.size   # last round the tile was in vision
        self.pearls = {}                     # tile -> round last seen with a pearl
        self.sym = SymmetryTracker()
        self._mirrored_keys = set()
        self._mirror_version = -1
        # --- filled by teammates' sonar (comms.py) ---
        self.reports = {}          # tile -> (pearl count, round, kind) death drops / clusters
        self.claims = {}           # tile -> (round, claimant's distance)
        self.enemy_reports = {}    # tile -> (round, length)
        self.best_len_heard = 0    # longest teammate length heard recently
        self.best_len_round = -10 ** 6
        # --- own observations used for reports and exploration ---
        self.prev_occ = {}         # other dragons' segments last turn: tile -> dragon id
        self.deaths_seen = []      # [(tile, pearls)] deaths noticed this turn
        B = config.EXPLORE_BLOCK
        self.nbx = (width + B - 1) // B
        self.block_seen = [-1] * (self.nbx * ((height + B - 1) // B))
        self.explore_goal = None   # (tile, round chosen)

    # ------------------------------------------------------------ update --
    def update(self, snap):
        """Merge this turn's observations. Edges were already learned by
        snapshot.build (the body trace needs them)."""
        now = snap.round
        cd_val, cd_round, cd_src, seen = self.cd_val, self.cd_round, self.cd_src, self.seen_round
        for i, c in snap.countdowns.items():
            cd_val[i] = c
            cd_round[i] = now
            cd_src[i] = SRC_SEEN
            seen[i] = now

        B = config.EXPLORE_BLOCK
        nbx, W = self.nbx, self.W
        block_seen = self.block_seen
        for i in snap.visible:
            block_seen[(i // W // B) * nbx + (i % W) // B] = now

        pearls = self.pearls
        here = set(snap.pearls)
        # death detection: pearls appearing where another dragon's body was last turn
        new_on_bodies = [p for p in here if p not in pearls and p in self.prev_occ]
        self.deaths_seen = [(new_on_bodies[0], len(new_on_bodies))] if len(new_on_bodies) >= 2 else []
        self.prev_occ = {t: o[0] for t, o in snap.occ.items() if o[0] != snap.my_id}
        for p in here:
            pearls[p] = now
        for i in snap.visible:
            if i in pearls and i not in here:
                del pearls[i]          # visible and empty: it was eaten
        if now % config.PEARL_CLEANUP_EVERY == 0:
            limit = now - config.PEARL_STALE_ROUNDS
            for p in [p for p, r in pearls.items() if r < limit]:
                del pearls[p]
            limit = now - config.REPORT_STALE_ROUNDS
            for d in (self.reports, self.claims, self.enemy_reports):
                for k in [k for k, v in d.items() if (v[1] if d is self.reports else v[0]) < limit]:
                    del d[k]
        reports = self.reports
        if reports:
            for i in snap.visible:
                if i in reports:
                    del reports[i]       # we can see the real thing now

        self.sym.observe(snap, self)
        if self.sym.locked() is not None:
            self.apply_mirror(snap)

    # ------------------------------------------------------- predictions --

    def apply_mirror(self, snap):
        """After lock-in, copy this turn's countdowns and all known kelp to the
        mirror side of the map, so we can plan in areas we never visited."""
        hyp = self.sym.locked()
        geo = self.geo
        now = snap.round
        cd_val, cd_round, cd_src = self.cd_val, self.cd_round, self.cd_src
        visible = snap.visible
        for i, c in snap.countdowns.items():
            m = geo.mirror(i, hyp)
            if m in visible:
                continue
            if cd_src[m] == SRC_SEEN and cd_round[m] >= now:
                continue       # never overwrite fresher direct observation
            cd_val[m] = c
            cd_round[m] = now
            cd_src[m] = SRC_MIRROR
        if geo.version != self._mirror_version:
            done = self._mirrored_keys
            for key, (kind, _) in list(geo.special.items()):
                if kind != EDGE_KELP or key in done:
                    continue
                done.add(key)
                t, d = key // 4, key % 4
                mt = geo.mirror(t, hyp)
                md = geo.mirror_dir(d, hyp)
                geo.learn_edge(mt, md, EDGE_KELP)
                done.add(geo.edge_key(mt, md))
            self._mirror_version = geo.version

    # ------------------------------------------------------ teammate info --
    def is_longest(self, snap):
        """Do we believe we're the team's longest dragon (the tiebreak holder)?"""
        if snap.my_len < config.LONGEST_MIN_LENGTH:
            return False
        if snap.round - self.best_len_round > config.LONGEST_MEMORY_ROUNDS:
            return True
        return snap.my_len >= self.best_len_heard

    def claimed_by_other(self, t, my_dist, now):
        c = self.claims.get(t)
        if c is None or now - c[0] > config.CLAIM_ROUNDS:
            return False
        return c[1] < my_dist

    def best_cluster(self, snap):
        """(tile, count) for the densest visible group of >= 3 pearls, else None."""
        ps = snap.pearls
        if len(ps) < 3:
            return None
        geo = self.geo
        best, best_n = None, 0
        for p in ps:
            n = sum(1 for q in ps if geo.manhattan(p, q) <= 2)
            if n > best_n:
                best, best_n = p, n
        return (best, best_n) if best_n >= 3 else None

    # --------------------------------------------------------------- hooks --
