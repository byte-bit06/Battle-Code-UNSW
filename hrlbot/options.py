"""The option library: the abstract actions the HRL manager chooses between.

Every option has the same three parts (the Options framework):
    can_start(t)   initiation set: may the manager pick it this turn?
    step(t)        internal policy: ("move", [dirs]) | ("split", k) | None
    should_stop(t) termination: hand control back to the manager

step() returning None also ends the option (it had nothing useful to do).
Nothing here is allowed to be the last word on safety: shield() in this file
vetoes any action that is illegal or, under danger, fails Instinct's Tier A
check. Directions are ints 0 N, 1 E, 2 S, 3 W throughout.

Most options wrap the engines that already exist (forage.py, instinct/*).
HUNT, SPLIT_AND_PINCER, PORTAL_TRAVEL and STALL are new.
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
                 "first", "_st", "_fctx", "_danger", "_facts", "_split_k")

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
        """Instinct's defensive split size, or None (cached: it runs BFSes)."""
        if self._split_k == -1:
            self._split_k = None
            if self.danger() and len(self.snap.body) >= self.snap.my_len >= 4:
                from instinct import policy
                self._split_k = policy.should_split(self.st(), unit_count=self.unit_count)
        return self._split_k

    def facts(self):
        if self._facts is None:
            self._facts = Facts(self)
        return self._facts


class Facts:
    """Cheap situation summary (no BFS). Shared by the initiation sets and
    the manager's features, so the manager sees what the options see."""

    __slots__ = ("pearls_near", "nearest_pearl", "cluster", "reports_near",
                 "predicted_soon", "camp_tile", "enemies", "nearest_enemy",
                 "allies", "portal", "explored", "hunt_target", "ram_dir")

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
        self.allies = sum(1 for h in snap.heads if h.teammate)

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

        # HUNT target: the nearest enemy we clearly outsize
        L = snap.my_len
        self.hunt_target = None
        if L >= config.HUNT_MIN_LEN:
            for m, h in self.enemies:
                if m > config.HUNT_RADIUS:
                    break
                known_len = h.pos in snap.release        # whole dragon in view
                need = config.HUNT_MARGIN + (0 if known_len else 3)
                if L >= h.visible_len + need:
                    self.hunt_target = h
                    break

        # RAM: an enemy head we can step onto right now
        self.ram_dir = None
        for d in (0, 1, 2, 3):
            n = geo.step(head, d)
            o = occ.get(n) if n >= 0 else None
            if o is not None and o[1] and not o[2]:
                self.ram_dir = (d, o[0])
                break


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

    def should_stop(self, t):
        return t.facts().predicted_soon == 0


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

    def should_stop(self, t):
        f = t.facts()
        return f.cluster == 0 and f.reports_near == 0


class Explore(Option):
    """Go where we have not looked recently. Always available."""
    name = "EXPLORE"

    def step(self, t):
        return ("move", [forage.explore(t.fctx(), use_goal=config.ENABLE_EXPLORE_GOAL)])

    def should_stop(self, t):
        f = t.facts()           # something to eat in sight: let the manager look again
        return f.pearls_near > 0 or f.predicted_soon > 0


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
    """Cut off a smaller enemy. Kills in this game come from an enemy head
    running into a body, so the hunter lays its body ACROSS the enemy's path:
    it heads for the tile HUNT_AHEAD steps in front of the enemy head, shrinks
    the enemy's reachable room, keeps its own room, and never steps where any
    enemy head could ram it. If the target slips out of view it follows the
    last sighting for HUNT_MEMORY turns."""
    name = "HUNT"

    def __init__(self):
        self.target = None
        self.last = None           # (tile ahead of the target, round seen)

    def can_start(self, t):
        return not t.first and t.facts().hunt_target is not None

    def start(self, t):
        h = t.facts().hunt_target
        self.target = h.id if h is not None else None
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
    """Split so the child starts behind an enemy near our tail: two heads on
    it instead of one. The child is a new program; its manager decides alone."""
    name = "SPLIT_AND_PINCER"
    one_shot = True

    def can_start(self, t):
        f = t.facts()
        snap = t.snap
        h = f.hunt_target
        if t.first or h is None or snap.my_len < config.PINCER_MIN_LEN or t.unit_count >= 64:
            return False
        # the enemy is alongside our REAR half (of what we can see): the child,
        # which leaves head-first from our tail, starts on its side of us
        man = t.mem.geo.manhattan
        body = snap.body
        rear = body[len(body) // 2:]
        return bool(rear) and min(man(s, h.pos) for s in rear) <= config.PINCER_TAIL_RADIUS \
            and min(man(s, h.pos) for s in rear) < man(snap.head, h.pos)

    def step(self, t):
        from instinct import tempo
        k = t.snap.my_len // 2
        if not t.ct.can_split(k) or tempo.ram_exposure(t.st()) > 0:
            return None             # a splitting parent stands still: must be unrammable
        return ("split", k)


class RamTrade(Option):
    """Deliberate head-to-head: both die. Only when the trade is worth it."""
    name = "RAM_TRADE"
    one_shot = True

    def can_start(self, t):
        f = t.facts()
        if t.first or f.ram_dir is None:
            return False
        from instinct import policy
        st = t.st()
        for e in st.enemies:
            if e.id == f.ram_dir[1]:
                return policy.may_trade(st, e)
        return False

    def step(self, t):
        rd = t.facts().ram_dir
        return ("move", [rd[0]]) if rd is not None else None


class Escape(Option):
    """Instinct's reflex ladder: break out of a closing net. Exactly the
    pre-HRL bot's danger mode: when the ladder's own key says we are calm (safe
    and nobody can ram us), the Forage engine keeps the turn."""
    name = "ESCAPE"

    def __init__(self):
        self.plan = None
        self.calm = 0

    def can_start(self, t):
        return t.danger()

    def start(self, t):
        self.calm = 0

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

    def should_stop(self, t):
        self.calm = 0 if t.danger() else self.calm + 1
        return self.calm >= 2


class DefensiveSplit(Option):
    """Boxed in but unrammable this round: split so one half survives."""
    name = "DEFENSIVE_SPLIT"
    one_shot = True

    def can_start(self, t):
        return t.split_k() is not None

    def step(self, t):
        k = t.split_k()
        return ("split", k) if k is not None and t.ct.can_split(k) else None


class EconSplit(Option):
    """Long, safe and alone: bud off a child to farm a second area."""
    name = "ECON_SPLIT"
    one_shot = True

    def can_start(self, t):
        snap = t.snap
        f = t.facts()
        if snap.my_len < config.ECON_MIN_LEN or snap.round >= config.ECON_LAST_ROUND:
            return False
        if t.unit_count >= config.ECON_MAX_UNITS:
            return False
        if f.nearest_enemy is not None and f.nearest_enemy[0] <= config.ECON_CLEAR_RADIUS:
            return False
        return t.ct.can_split(config.ECON_CHILD)

    def step(self, t):
        return ("split", config.ECON_CHILD) if t.ct.can_split(config.ECON_CHILD) else None


class Stall(Option):
    """Protect the longest dragon: coil in safe space, keep options open, stay
    away from enemy heads, eat only what is free (tiebreak = longest dragon)."""
    name = "STALL"

    def can_start(self, t):
        snap = t.snap
        if t.first or snap.my_len < config.STALL_MIN_LEN:
            return False
        return snap.round >= config.STALL_ROUND or t.mem.is_longest(snap)

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


def make_options():
    """Fresh option instances for one dragon (options hold per-dragon state).
    The ORDER is the manager's action space: never reorder without retraining."""
    return [Forage(), CampCluster(), Scavenge(), Explore(), PortalTravel(), Hunt(),
            SplitAndPincer(), RamTrade(), Escape(), DefensiveSplit(), EconSplit(), Stall()]


NAMES = [o.name for o in make_options()]
N_OPTIONS = len(NAMES)
IDX = {n: i for i, n in enumerate(NAMES)}


# ================================================================= shield ==
def shield(t, action):
    """Return `action` if it is safe to send, otherwise a replacement or None.

    Never learned, never switched off:
      * a split must be legal (an illegal split kills the parent);
      * a move's first step must not be certain death (kelp, a body, our tail);
      * a sprint must be affordable and collision-free all the way;
      * under danger, a single step that fails Instinct's Tier A check (no
        legal follow-up even if no body ever moves) is swapped for the reflex.
    """
    if action is None:
        return None
    kind, arg = action
    if kind == "split":
        return action if t.ct.can_split(arg) else None
    dirs = list(arg)
    snap = t.snap
    if not dirs:
        return None
    if dirs[0] not in t.legal:
        # the one deliberate exception: a single step onto an ENEMY head is a
        # trade (both die), which RAM_TRADE only proposes when policy.may_trade
        n = t.mem.geo.step(snap.head, dirs[0])
        o = snap.occ.get(n) if n >= 0 else None
        if len(dirs) == 1 and o is not None and o[1] and not o[2]:
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
