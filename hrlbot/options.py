"""The option library: the moves the HRL manager chooses between, every turn.

The manager (the AI) has full autonomy: it picks one option EVERY turn and the
option only answers "what is my move this turn?". Options hold no opinion on
WHEN they should be used - that is learned. Each has:
    can_start(t)   feasibility only: is this move physically possible now?
                   (e.g. RAM_TRADE needs an enemy head next to ours)
    step(t)        this turn's action: ("move", [dirs]) | ("split", k) | None
    start(t)       reset its memory (a hunt target, an escape plan) when the
                   manager switches to it; picking it again keeps the memory
    should_stop(t) its memory is stale (e.g. PORTAL_TRAVEL already jumped)

step() returning None means it has nothing to do; the Brain falls back to the
manager's next choice. shield() in this file vetoes anything illegal, and is
the only hard-coded rule. Directions are ints 0 N, 1 E, 2 S, 3 W throughout.

Most options wrap the engines that already exist (forage.py, instinct/*).
HUNT, SPLIT_AND_PINCER, PORTAL_TRAVEL, STALL and the FEED options are new.
"""

import time

import config
import forage
import routing
import safety

INF = float("inf")


# ============================================================ turn context ==
class Turn:
    """Everything one turn's options read, with the expensive parts built lazily
    and at most once (a BFS costs ~3M points on the judge)."""

    __slots__ = ("ct", "snap", "mem", "safe", "legal", "deadline", "unit_count",
                 "first", "_st", "_fctx", "_danger", "_facts", "_split_k", "_rammable")

    def __init__(self, ct, snap, mem, deadline, first):
        self.ct = ct
        self.snap = snap
        self.mem = mem
        self.deadline = deadline
        self.first = first
        self.unit_count = ct.get_unit_count()
        safe, risky, gamble = safety.classify_all(snap, mem)
        self.safe = safe or risky or gamble      # best class, as safety.get_safe_moves
        self.legal = safe + risky + gamble       # everything that is not certain death
        self._st = None
        self._fctx = None
        self._danger = None
        self._facts = None
        self._split_k = -1
        self._rammable = None

    def st(self):
        """Instinct's board State (no search, just gathering)."""
        if self._st is None:
            from instinct import state as instinct_state
            self._st = instinct_state.from_snapshot(self.snap, self.mem)
        return self._st

    def fctx(self):
        """Forage's per-turn context: one capped BFS from our head."""
        if self._fctx is None:
            self._fctx = forage.make_ctx(self.snap, self.mem, self.safe, self.deadline)
        return self._fctx

    def danger(self):
        if self._danger is None:
            if self.first:
                self._danger = False     # imports alone cost ~78M points on turn 1
            else:
                from instinct import ladder
                self._danger = ladder.danger(self.st())
        return self._danger

    def split_k(self):
        """The split size that saves both halves when we are boxed in (Instinct's
        should_split), or None. Cached: it runs BFSes, so it is only asked when
        we are down to two legal moves or fewer (a box always gets there first)."""
        if self._split_k == -1:
            self._split_k = None
            if (not self.first and len(self.legal) <= 2
                    and len(self.snap.body) >= self.snap.my_len >= 4):
                from instinct import policy
                self._split_k = policy.should_split(self.st(), unit_count=self.unit_count)
        return self._split_k

    def rammable(self):
        """Can an enemy head reach ours before our next turn (a mutual kill)?"""
        if self._rammable is None:
            f = self.facts()
            self._rammable = False
            if not self.first and f.nearest_enemy is not None and f.nearest_enemy[0] <= 6:
                from instinct import tempo
                self._rammable = tempo.ram_exposure(self.st()) > 0
        return self._rammable

    def facts(self):
        if self._facts is None:
            self._facts = Facts(self)
        return self._facts


class Facts:
    """Cheap situation summary (no BFS). Shared by the initiation sets and
    the manager's features, so the manager sees what the options see."""

    __slots__ = ("pearls_near", "nearest_pearl", "cluster", "reports_near",
                 "predicted_soon", "camp_tile", "enemies", "nearest_enemy",
                 "allies", "ally_bodies", "portal", "explored", "ram_dir", "feed_dir")

    def __init__(self, t):
        snap, mem = t.snap, t.mem
        geo = mem.geo
        head = snap.head
        man = geo.manhattan
        now = snap.round

        known = set(mem.pearls)
        known.update(snap.pearls)
        near = [p for p in known if man(p, head) <= config.BFS_RADIUS]
        self.pearls_near = len(near)
        self.nearest_pearl = min((man(p, head) for p in near), default=99)
        close = [p for p in near if man(p, head) <= config.SCAVENGE_RADIUS]
        best = 0
        if len(close) >= config.SCAVENGE_MIN_PEARLS:
            for p in close:
                n = 0
                for q in close:
                    if man(p, q) <= 2:
                        n += 1
                if n > best:
                    best = n
        self.cluster = best if best >= config.SCAVENGE_MIN_PEARLS else 0
        self.reports_near = sum(1 for tile in mem.reports
                                if man(tile, head) <= config.FAR_GOAL_RADIUS)

        # spawn tiles about to fire nearby (CAMP_CLUSTER)
        W = mem.W
        hx, hy = head % W, head // W
        R = config.CAMP_RADIUS
        cd_val, cd_round = mem.cd_val, mem.cd_round
        soon, camp, camp_cd = 0, None, INF
        occ = snap.occ
        for dy in range(-R, R + 1):
            span = R - abs(dy)
            for dx in range(-span, span + 1):
                i = geo.idx(hx + dx, hy + dy)
                v = cd_val[i]
                if v is None or v < 1 or i in known or i in occ:
                    continue
                T = v - (now - cd_round[i])
                if 1 <= T <= config.CAMP_WINDOW:
                    soon += 1
                    if T < camp_cd:
                        camp, camp_cd = i, T
        self.predicted_soon = soon
        self.camp_tile = camp

        self.enemies = [(man(h.pos, head), h) for h in snap.heads if not h.teammate]
        self.enemies.sort(key=lambda e: e[0])
        self.nearest_enemy = self.enemies[0] if self.enemies else None
        self.allies = [(man(h.pos, head), h) for h in snap.heads if h.teammate]
        self.allies.sort(key=lambda e: e[0])
        # teammates' visible BODY segments (not heads): dragon id -> [tiles]
        self.ally_bodies = {}
        my_id = snap.my_id
        for tile, (did, is_head, mate, _d) in occ.items():
            if mate and did != my_id and not is_head:
                self.ally_bodies.setdefault(did, []).append(tile)

        # nearest known portal edge (its far end may still be unknown: vision
        # never reaches through a portal, so most pairs are only learned by using them)
        self.portal = None
        for keys in geo.portal_pairs.values():
            for key in keys:
                a = key // 4
                m = man(a, head)
                if m <= config.PORTAL_RADIUS and (self.portal is None or m < self.portal):
                    self.portal = m
        seen = mem.block_seen
        self.explored = sum(1 for b in seen if b >= 0) / len(seen)

        # an enemy head we can step onto (RAM) / a teammate body we can step
        # onto (FEED) right now
        self.ram_dir = None
        self.feed_dir = None
        for d in (0, 1, 2, 3):
            n = geo.step(head, d)
            o = occ.get(n) if n >= 0 else None
            if o is None:
                continue
            if o[1] and not o[2] and self.ram_dir is None:
                self.ram_dir = (d, o[0])
            elif not o[1] and o[2] and o[0] != my_id and self.feed_dir is None:
                self.feed_dir = (d, o[0])


# ================================================================ options ==
class Option:
    name = "?"
    one_shot = False             # acts once (splits, rams) then hands back control

    def can_start(self, t):
        return True

    def start(self, t):
        pass

    def step(self, t):
        return None

    def should_stop(self, t):
        return False


class Forage(Option):
    """The whole Forage engine: live pearls, piles and predicted spawns scored
    against each other (its joint score is what makes it good; splitting the
    target kinds into separate options lost 38 of 48 games). CAMP_CLUSTER and
    SCAVENGE are the specialists that commit to one kind of target."""
    name = "FORAGE"

    def can_start(self, t):
        return True     # its own search (radius BFS_RADIUS) decides; None = nothing to eat

    def step(self, t):
        mv = forage.forage_turn(t.snap, t.mem, t.safe, t.deadline, fallback=False, c=t.fctx())
        return ("move", mv) if mv else None


class CampCluster(Option):
    """Curl up by spawn tiles that are about to fire and eat them on time."""
    name = "CAMP_CLUSTER"

    def can_start(self, t):
        return t.facts().predicted_soon > 0

    def step(self, t):
        c = t.fctx()
        mv = forage.forage_turn(t.snap, t.mem, t.safe, t.deadline, kinds=("predicted",),
                                fallback=False, c=c)
        if mv:
            return ("move", mv)
        target = t.facts().camp_tile
        if target is None:
            return None
        # hold: stay close to the next spawn without boxing ourselves in
        geo, head = c.geo, t.snap.head
        need = forage.first_step_need(c)
        best, best_key = None, None
        for d in t.safe:
            n = geo.step(head, d)
            if n < 0:
                continue
            key = (forage.first_step_area(c, d) >= need, -geo.manhattan(n, target))
            if best_key is None or key > best_key:
                best, best_key = d, key
        return ("move", [best]) if best is not None else None


class Scavenge(Option):
    """Race to a pile of pearls (a death drop or a cluster), including piles
    teammates reported over sonar."""
    name = "SCAVENGE"

    def can_start(self, t):
        f = t.facts()
        return f.cluster > 0 or f.reports_near > 0

    def step(self, t):
        c = t.fctx()
        mv = forage.forage_turn(t.snap, t.mem, t.safe, t.deadline, kinds=("cluster",),
                                fallback=False, c=c)
        if mv:
            return ("move", mv)
        # head for the nearest reported pile outside our search radius
        geo, head = c.geo, t.snap.head
        reports = sorted(t.mem.reports, key=lambda tile: geo.manhattan(tile, head))
        need = forage.first_step_need(c)
        for goal in reports[:2]:
            d, _eta = forage.frontier_step(c, goal)
            if d is not None and d in t.safe and forage.first_step_area(c, d) >= need:
                forage.LAST_TARGET = (goal, geo.manhattan(goal, head))
                return ("move", [d])
        return None


class Explore(Option):
    """Go where we have not looked recently. Always available."""
    name = "EXPLORE"

    def step(self, t):
        return ("move", [forage.explore(t.fctx(), use_goal=config.ENABLE_EXPLORE_GOAL)])


class PortalTravel(Option):
    """Jump through a portal to a staler part of the map. A portal whose far
    end we have never seen is a gamble (the exit could hold a body), so it is
    valued at PORTAL_UNKNOWN_GAIN rather than by the staleness of its exit."""
    name = "PORTAL_TRAVEL"

    def __init__(self):
        self.goal = None           # (entry tile, direction, exit tile or -2 if unknown)
        self.since = 0
        self.jumped = False

    def can_start(self, t):
        return t.facts().portal is not None

    def start(self, t):
        self.goal = None
        self.since = t.snap.round
        self.jumped = False

    def _stale(self, mem, tile, now):
        B = config.EXPLORE_BLOCK
        b = mem.block_seen[((tile // mem.W) // B) * mem.nbx + (tile % mem.W) // B]
        return now + 50 if b < 0 else now - b

    def _pick(self, t, c):
        geo, mem, head, now = c.geo, t.mem, t.snap.head, t.snap.round
        here = self._stale(mem, head, now)
        best, best_s = None, None
        for keys in geo.portal_pairs.values():
            for key in keys:
                a, side = key // 4, key % 4
                b = geo.plain(a, side)
                for entry, d in ((a, side), (b, (side + 2) % 4)):
                    if entry not in c.dist:
                        continue
                    exit_ = geo.step(entry, d)
                    if exit_ == -1:                       # kelp: not a portal after all
                        continue
                    if exit_ < 0:
                        gain = config.PORTAL_UNKNOWN_GAIN
                    else:
                        gain = self._stale(mem, exit_, now) - here
                    if gain < config.PORTAL_MIN_GAIN:
                        continue
                    s = gain - config.C_D * c.dist[entry]
                    if best_s is None or s > best_s:
                        best, best_s = (entry, d, exit_), s
        return best

    def step(self, t):
        c = t.fctx()
        head = t.snap.head
        if self.goal is None or self.goal[0] not in c.dist:
            self.goal = self._pick(t, c)
        if self.goal is None:
            return None
        entry, d, exit_ = self.goal
        if head == entry:
            self.jumped = True
            return ("move", [d])
        path = routing.path_to(c.parent, head, entry)
        if not path or path[0] not in t.safe:
            return None
        forage.LAST_TARGET = (entry, len(path))
        return ("move", [path[0]])

    def should_stop(self, t):
        return self.jumped or t.snap.round - self.since > 30


class Hunt(Option):
    """Go after the nearest visible enemy. Kills in this game come from an enemy
    head running into a body, so the hunter lays its body across the enemy's
    path: it closes on the tile HUNT_AHEAD steps in front of the enemy head,
    shrinks the enemy's reachable room, keeps its own room, and never steps
    where any enemy head could ram it. If the target slips out of view it
    follows the last sighting for HUNT_MEMORY turns."""
    name = "HUNT"

    def __init__(self):
        self.target = None
        self.last = None           # (tile ahead of the target, round seen)

    def can_start(self, t):
        return not t.first and t.facts().nearest_enemy is not None

    def start(self, t):
        ne = t.facts().nearest_enemy
        self.target = ne[1].id if ne is not None else None
        self.last = None

    def _enemy(self, st):
        for e in st.enemies:
            if e.id == self.target:
                return e
        return None

    def _ahead(self, geo, e_head, e_dir):
        p = e_head
        for _ in range(config.HUNT_AHEAD):
            n = geo.step(p, e_dir)
            if n < 0:
                break
            p = n
        return p

    def step(self, t):
        from instinct import policy, space, tempo
        st = t.st()
        e = self._enemy(st)
        geo = st.geo
        if e is None:
            if self.last is None or st.round - self.last[1] > config.HUNT_MEMORY:
                return None
            c = t.fctx()              # lost sight of it: go to where it was heading
            d, _eta = forage.frontier_step(c, self.last[0])
            if d is None or d not in t.safe or forage.first_step_area(c, d) < forage.first_step_need(c):
                return None
            return ("move", [d])
        e_dir = next((h.dir for h in t.snap.heads if h.id == e.id), 0)
        ahead = self._ahead(geo, e.head, e_dir)
        self.last = (ahead, st.round)
        need = min(st.L + 1, 31)
        best, best_key = None, None
        for d in (0, 1, 2, 3):
            nxt = policy.after_move(st, [d])
            if nxt is None:
                continue
            legal_after = policy.legal_moves(nxt)
            if not legal_after:
                continue
            exposed = tempo.ram_exposure(nxt, nxt.head) > 0
            mine = space.timed_space(nxt, cap=32)
            blocked = nxt.blocked()
            blocked.discard(e.head)
            theirs = routing.flood_fill(geo, e.head, blocked, config.HUNT_AREA_CAP)
            score = (-config.HUNT_W_SQUEEZE * theirs
                     + config.HUNT_W_OWN * min(mine, 2 * st.L)
                     - config.HUNT_W_CLOSE * geo.manhattan(nxt.head, ahead))
            key = (not exposed, mine >= need, score, len(legal_after))
            if best_key is None or key > best_key:
                best, best_key = d, key
        return ("move", [best]) if best is not None else None

    def should_stop(self, t):
        return self.last is not None and t.snap.round - self.last[1] > config.HUNT_MEMORY


class SplitAndPincer(Option):
    """Split in half with an enemy in view: two heads on it instead of one.
    The child leaves head-first from our tail and is a new program whose own
    manager decides what it does next."""
    name = "SPLIT_AND_PINCER"
    one_shot = True

    def can_start(self, t):
        return (not t.first and t.facts().nearest_enemy is not None
                and t.ct.can_split(t.snap.my_len // 2))

    def step(self, t):
        k = t.snap.my_len // 2
        return ("split", k) if t.ct.can_split(k) else None


class RamTrade(Option):
    """Head-to-head with an adjacent enemy head: both dragons die."""
    name = "RAM_TRADE"
    one_shot = True

    def can_start(self, t):
        return not t.first and t.facts().ram_dir is not None

    def step(self, t):
        rd = t.facts().ram_dir
        return ("move", [rd[0]], "ram") if rd is not None else None


class Escape(Option):
    """Instinct's reflex ladder: the safest move against every enemy head in
    view. When the ladder's own key says we are calm (safe and nobody can ram
    us), the Forage engine keeps the turn, as in the pre-HRL bot."""
    name = "ESCAPE"

    def __init__(self):
        self.plan = None

    def can_start(self, t):
        return not t.first

    def start(self, t):
        self.plan = None

    def step(self, t):
        from instinct import ladder
        action, self.plan, inf = ladder.decide_budgeted(
            t.st(), self.plan, t.unit_count, t.deadline.t0)
        if action is not None and action[0] == "split":
            return action
        key = inf.get("key") if action is not None else None
        if (bool(key) and key[0] and key[1] == 0) or action is None:
            if time.perf_counter() - t.deadline.t0 < config.INSTINCT_HARD_S:
                try:
                    mv = forage.forage_turn(t.snap, t.mem, t.safe, t.deadline, fallback=False,
                                            c=t.fctx())
                    if mv:
                        return ("move", mv)
                except forage.ForageTimeout:
                    pass
        return action


class DefensiveSplit(Option):
    """Boxed in: split at the size Instinct says leaves room for both halves."""
    name = "DEFENSIVE_SPLIT"
    one_shot = True

    def can_start(self, t):
        return t.split_k() is not None

    def step(self, t):
        k = t.split_k()
        return ("split", k) if k is not None and t.ct.can_split(k) else None


class EconSplit(Option):
    """Bud off a small child (ECON_CHILD long) to farm a second area."""
    name = "ECON_SPLIT"
    one_shot = True

    def can_start(self, t):
        return not t.first and t.ct.can_split(config.ECON_CHILD)

    def step(self, t):
        return ("split", config.ECON_CHILD) if t.ct.can_split(config.ECON_CHILD) else None


class Stall(Option):
    """Play for time: coil in safe space, keep moves open, stay away from enemy
    heads, eat only what is free (the round-500 tiebreak is the longest dragon)."""
    name = "STALL"

    def can_start(self, t):
        return not t.first

    def step(self, t):
        from instinct import policy, space, tempo
        st = t.st()
        geo = st.geo
        heads = [e.head for e in st.enemies]
        best, best_key = None, None
        for d in (0, 1, 2, 3):
            nxt = policy.after_move(st, [d])
            if nxt is None:
                continue
            legal_after = policy.legal_moves(nxt)
            if not legal_after:
                continue
            exposed = tempo.ram_exposure(nxt, nxt.head) if heads else 0
            room = min(space.timed_space(nxt, cap=24), 24)
            far = min((geo.manhattan(nxt.head, h) for h in heads), default=99)
            key = (-exposed, room >= min(st.L + 1, 24), len(legal_after), min(far, 8),
                   nxt.L - st.L, room)
            if best_key is None or key > best_key:
                best, best_key = d, key
        return ("move", [best]) if best is not None else None


class Feed(Option):
    """Sacrifice this dragon to a teammate: run into its BODY (never its head,
    which would kill both). We die and drop ceil(L/2) pearls on every second
    segment of our body, right beside the teammate, which the teammate can
    then eat - e.g. to make one dragon the longest for the round-500 tiebreak.
    Two variants so the AI also chooses WHO gets fed."""
    name = "FEED"
    pick = None                     # "longest" | "nearest"

    def __init__(self):
        self.target = None

    def can_start(self, t):
        return not t.first and bool(t.facts().ally_bodies)

    def _choose(self, t):
        f = t.facts()
        geo, head = t.mem.geo, t.snap.head
        if self.pick == "longest":
            size = {h.id: h.visible_len for _m, h in f.allies}
            return max(f.ally_bodies, key=lambda i: (size.get(i, 0), len(f.ally_bodies[i])))
        return min(f.ally_bodies, key=lambda i: min(geo.manhattan(s, head) for s in f.ally_bodies[i]))

    def start(self, t):
        self.target = None

    def step(self, t):
        f = t.facts()
        if self.target not in f.ally_bodies:
            if not f.ally_bodies:
                return None
            self.target = self._choose(t)
        geo, head = t.mem.geo, t.snap.head
        segs = set(f.ally_bodies[self.target])
        for d in (0, 1, 2, 3):                      # next to its body: go in
            if geo.step(head, d) in segs:
                return ("move", [d], "feed")
        c = t.fctx()                                # otherwise walk up beside it
        best, best_d = None, None
        for s in segs:
            for n in geo.neighbours(s):
                if n >= 0 and n in c.dist and (best is None or c.dist[n] < best_d):
                    best, best_d = n, c.dist[n]
        if best is None:
            return None
        path = routing.path_to(c.parent, head, best)
        if not path or path[0] not in t.safe:
            return None
        return ("move", [path[0]])


class FeedLongest(Feed):
    name = "FEED_LONGEST"
    pick = "longest"


class FeedNearest(Feed):
    name = "FEED_NEAREST"
    pick = "nearest"


def make_options():
    """Fresh option instances for one dragon (options hold per-dragon state).
    The ORDER is the manager's action space: never reorder without retraining."""
    return [Forage(), CampCluster(), Scavenge(), Explore(), PortalTravel(), Hunt(),
            SplitAndPincer(), RamTrade(), Escape(), DefensiveSplit(), EconSplit(), Stall(),
            FeedLongest(), FeedNearest()]


NAMES = [o.name for o in make_options()]
N_OPTIONS = len(NAMES)
IDX = {n: i for i, n in enumerate(NAMES)}


# ================================================================= shield ==
def shield(t, action):
    """Return `action` if it may be sent, otherwise a replacement or None.

    The only hard-coded rules in the bot. Never learned, never switched off:
      * a split must be legal (an illegal split kills the parent);
      * a move's first step must not be certain death (kelp, a body, our tail),
        EXCEPT the two deliberate deaths the AI can choose: a "ram" step onto an
        enemy head (RAM_TRADE) and a "feed" step onto a teammate's body (FEED);
      * a sprint must be affordable and collision-free all the way;
      * under danger, a single step that fails Instinct's Tier A check (no
        legal follow-up even if no body ever moves) is swapped for the reflex.
    Returns ("move", dirs) or ("split", k): the tag is dropped.
    """
    if action is None:
        return None
    kind, arg = action[0], action[1]
    tag = action[2] if len(action) > 2 else None
    if kind == "split":
        return action if t.ct.can_split(arg) else None
    dirs = list(arg)
    snap = t.snap
    if not dirs:
        return None
    if dirs[0] not in t.legal:
        n = t.mem.geo.step(snap.head, dirs[0])
        o = snap.occ.get(n) if n >= 0 else None
        if len(dirs) == 1 and o is not None and o[0] != snap.my_id:
            if tag == "ram" and o[1] and not o[2]:
                return ("move", dirs)
            if tag == "feed" and not o[1] and o[2]:
                return ("move", dirs)
        return None
    if len(dirs) > 1:
        if snap.my_len - (len(dirs) - 1) < 2:
            return None
        sim = routing.simulate(t.mem.geo, snap.body, snap.my_len, dirs,
                               set(snap.pearls), snap.walls, snap.release)
        if sim is None:
            return None
    elif config.HRL_SHIELD_TIER_A and t.danger():
        from instinct import ladder, policy
        st = t.st()
        nxt = policy.after_move(st, dirs)
        if nxt is None or not policy.legal_moves(nxt):
            alt = ladder.l0_reflex(st)
            if alt is not None and alt != dirs[0]:
                return ("move", [alt])
    return ("move", dirs)
