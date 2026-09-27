"""One turn's board, in the shape the Instinct modules want.

Built from a Snapshot + WorldMemory (the real bot) or from an ASCII fixture
(instinct_tests/boards.py). Nothing here searches; it just gathers.

Two safety tiers (instinct_engine.md 4.4) run through everything:
  TIER_A  worst case: unknown bodies never vacate, enemies sprint as far as
          they can afford, phantom heads exist. Only Tier A can call a move safe.
  TIER_B  best estimate: enemy length = max(visible, last known, 2), tails
          released on that estimate, sprints priced by the length they cost.
"""

import config

TIER_A, TIER_B = 0, 1


class Dragon:
    """Another dragon as we currently understand it."""
    __slots__ = ("id", "head", "segs", "length", "teammate", "phantom", "acts_before")

    def __init__(self, did, head, segs, length, teammate, phantom=False, acts_before=False):
        self.id = did
        self.head = head
        self.segs = segs            # visible segments, head first where known
        self.length = length        # estimate: max(visible, last known, 2)
        self.teammate = teammate
        self.phantom = phantom      # injected at a vision edge (Tier A only)
        self.acts_before = acts_before   # lower id: already moved this round

    def sprint(self, tier):
        """Steps it can take in one round. Sprinting x costs x-1 length."""
        if tier == TIER_A:
            return max(1, min(self.length - 1, config.INSTINCT_MAX_SPRINT))
        return 1                    # Tier B: enemies rarely pay for a sprint

    def __repr__(self):
        return (f"Dragon(id={self.id}, head={self.head}, L~{self.length}, "
                f"{'ally' if self.teammate else 'enemy'}{', phantom' if self.phantom else ''})")


class State:
    """Everything the Instinct modules read. `snap`/`mem` may be None in tests."""
    __slots__ = ("geo", "snap", "mem", "W", "H", "my_id", "head", "body", "L",
                 "enemies", "allies", "pearls", "seen_round", "round", "longest_ally",
                 "open_tiles")

    def __init__(self, geo, my_id, head, body, L, enemies=(), allies=(), pearls=(),
                 seen_round=None, round_num=0, snap=None, mem=None, longest_ally=False):
        self.geo = geo
        self.snap = snap
        self.mem = mem
        self.W, self.H = geo.W, geo.H
        self.my_id = my_id
        self.head = head
        self.body = list(body)          # head first, known segments only
        self.L = L
        self.enemies = list(enemies)
        self.allies = list(allies)
        self.pearls = set(pearls)
        self.seen_round = seen_round
        self.round = round_num
        self.longest_ally = longest_ally    # we hold the team's longest-dragon tiebreak
        self.open_tiles = set()             # fixtures may name "the open board" with O

    # ------------------------------------------------------------ blocked --
    def own_index(self):
        """tile -> index in our body (head 0). Segment i frees after L-i moves."""
        return {t: i for i, t in enumerate(self.body)}

    def blocked(self, tier=TIER_A, include_own=True):
        """Tiles no route may pass through. Kelp lives on edges, so Geo handles it."""
        out = set()
        for d in self.enemies:
            out.update(d.segs)
        for d in self.allies:
            out.update(d.segs)
        if include_own:
            out.update(self.body)
        return out

    def release(self, tier):
        """tile -> the move after which it opens up, for other dragons' segments.
        Tier A releases nothing (worst case); Tier B uses the length estimate."""
        out = {}
        if tier == TIER_A:
            return out
        for d in self.enemies + self.allies:
            n = len(d.segs)
            for i, t in enumerate(d.segs):
                out[t] = max(out.get(t, 0), d.length - i + config.ENEMY_TAIL_MARGIN
                             if n else 0)
        return out

    def xy(self, t):
        return self.geo.xy(t)

    def __repr__(self):
        return (f"State(me={self.geo.xy(self.head)}, L={self.L}, "
                f"enemies={[self.geo.xy(d.head) for d in self.enemies]})")


def from_snapshot(snap, mem, longest_ally=None):
    """Build a State from the live bot's per-turn snapshot."""
    enemies, allies = [], []
    for h in snap.heads:
        segs = [t for t, o in snap.occ.items() if o[0] == h.id]
        est = max(len(segs), h.visible_len, 2)
        d = Dragon(h.id, h.pos, segs, est, h.teammate, acts_before=h.id < snap.my_id)
        (allies if h.teammate else enemies).append(d)
    if longest_ally is None:
        longest_ally = mem.is_longest(snap) if mem is not None else False
    return State(mem.geo, snap.my_id, snap.head, snap.body, snap.my_len,
                 enemies, allies, snap.pearls, mem.seen_round, snap.round,
                 snap, mem, longest_ally)
