"""Per-turn read-only view of the world.

All decision code works on a Snapshot, never on helper.Controller, so tests
can build fake turns without the engine. Plain classes with __slots__ are
used on purpose: importing `dataclasses` costs millions of CPU points on the
judge, and every split child pays module import cost on its first turn.
"""

import config
from geometry import EDGE_KELP


class HeadInfo:
    __slots__ = ("id", "pos", "dir", "visible_len", "teammate")

    def __init__(self, dragon_id, pos, direction, visible_len, teammate):
        self.id = dragon_id
        self.pos = pos
        self.dir = direction
        self.visible_len = visible_len
        self.teammate = teammate

    def __repr__(self):
        return f"HeadInfo(id={self.id}, pos={self.pos}, len>={self.visible_len}, mate={self.teammate})"


class Snapshot:
    """What this dragon knows this turn.

    occ maps tile -> (dragon_id, is_head, is_teammate, dir) for every visible
    dragon segment. dir is the int direction the segment faces (a head faces
    where it is heading, a body segment faces towards its head).
    """

    __slots__ = ("round", "W", "H", "my_id", "my_len", "my_dir", "head",
                 "occ", "visible", "countdowns", "pearls",
                 "body", "own_index", "walls", "heads", "release")

    def __init__(self, round_num, W, H, my_id, my_len, my_dir, head,
                 occ, visible, countdowns, pearls):
        self.round = round_num
        self.W = W
        self.H = H
        self.my_id = my_id
        self.my_len = my_len
        self.my_dir = my_dir
        self.head = head
        self.occ = occ
        self.visible = visible
        self.countdowns = countdowns    # tile -> countdown (-1 = never spawns)
        self.pearls = pearls            # list of tiles with a pearl now
        self.body = None
        self.own_index = None
        self.walls = None
        self.heads = None
        self.release = None

    def finalize(self, geo, body=None):
        """Derive body order, walls and other heads. Needs edges already learned."""
        self.body = body if body is not None else trace_body(geo, self.occ, self.head, self.my_id, self.my_len)
        self.own_index = {t: i for i, t in enumerate(self.body)}
        my_id = self.my_id
        walls = set()
        heads = []
        release = {}
        own = self.own_index
        for t, (did, is_head, mate, d) in self.occ.items():
            if did == my_id:
                if t not in own:
                    # our own segment whose chain left vision and came back:
                    # we can't know when it frees, so treat it as a wall
                    walls.add(t)
                continue
            walls.add(t)
            if is_head:
                seg = trace_body(geo, self.occ, t, did, 10 ** 6)
                heads.append(HeadInfo(did, t, d, len(seg), mate))
                if tail_is_real(geo, seg, self.visible):
                    # whole dragon visible: segment j frees after (len - j) of its
                    # moves (+ margin in case it eats), like our own body
                    n = len(seg)
                    for j, st in enumerate(seg):
                        release[st] = n - j + config.ENEMY_TAIL_MARGIN
        self.walls = walls
        self.heads = heads
        self.release = release
        return self


def tail_is_real(geo, seg, visible):
    """True if the traced chain really ends here: every neighbour of its last
    segment is visible, so a further segment would have been seen."""
    for n in geo.neighbours(seg[-1]):
        if n >= 0 and n not in visible:
            return False
    return True


def trace_body(geo, occ, head, dragon_id, max_len):
    """Follow a dragon from its head through visible segments.

    A segment belongs next in the chain if it is ours, is not a head, and its
    facing direction steps (portal-aware) back onto the current segment.
    """
    body = [head]
    seen = {head}
    cur = head
    while len(body) < max_len:
        nxt = -1
        for d in (0, 1, 2, 3):
            n = geo.step(cur, d)
            if n < 0 or n in seen:
                continue
            o = occ.get(n)
            if o is None or o[0] != dragon_id or o[1]:
                continue
            if geo.step(n, o[3]) == cur:
                nxt = n
                break
        if nxt < 0:
            break
        body.append(nxt)
        seen.add(nxt)
        cur = nxt
    return body


def build(ct, game, geo, dir_index):
    """Read the helper controller once and produce a finalized Snapshot.

    Also records every kelp/portal edge seen this turn into `geo`, because the
    body trace needs portal-aware stepping.
    """
    W, H = game.width, game.height
    my_id = ct.get_id()
    my_team = ct.get_team()
    occ = {}
    visible = set()
    countdowns = {}
    pearls = []
    learn = geo.learn_edge
    for tile in ct.get_tiles():
        pos = tile.position
        i = pos.y * W + pos.x
        visible.add(i)
        countdowns[i] = tile.pearl_time
        if tile.pearl:
            pearls.append(i)
        part = tile.dragon_part
        if part is not None:
            occ[i] = (part.dragon_id, part.is_dragon_head,
                      part.team == my_team, dir_index[part.dir])
        # tile._edges is (N, E, S, W); only kelp/portal edges are recorded.
        d = 0
        for e in tile._edges:
            k = e.edge_type.value
            if k:
                learn(i, d, EDGE_KELP if k == 1 else k, e.portal_id)
            d += 1
    head_pos = ct.get_position()
    head = head_pos.y * W + head_pos.x
    snap = Snapshot(game.round_num, W, H, my_id, ct.get_length(),
                    dir_index[ct.get_dir()], head, occ, visible, countdowns, pearls)
    return snap.finalize(geo)
