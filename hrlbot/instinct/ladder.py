"""The reflex ladder and plan memory (instinct_engine.md 4.9).

L0 runs before any search and always yields a legal action, so a turn can
never end with no action (which is death). Each level overwrites the answer
only after it completes, so the answer on file is always usable.

Plan memory: on a timeout we follow the next step of last turn's escape route
(re-validated by L0) instead of a fresh myopic step. Panicking coherently
beats panicking randomly.
"""

import time

import config
from instinct import policy, space, tempo
from instinct.state import TIER_A, TIER_B


TIMINGS = {"L0": [], "L1": [], "state": [], "total": []}


def _clock(name, t0):
    if config.INSTINCT_PROFILE:
        TIMINGS[name].append(time.perf_counter() - t0)


def danger(st, dist=None):
    """Cheap pre-check: is any enemy head near enough to matter this turn?
    Manhattan on head tiles only - no search - so calm turns cost ~nothing."""
    dist = config.INSTINCT_DANGER_DIST if dist is None else dist
    man = st.geo.manhattan
    head = st.head
    return any(man(head, d.head) <= dist for d in st.enemies)


def decide_budgeted(st, plan=None, unit_count=1, t0=None, deadline=None, tier=TIER_A):
    """The ladder with a HARD wall-clock cutoff at every step.

    Measured on the judge: exceeding the CPU limit kills the dragon even when a
    valid action has already been printed, so each level is gated on elapsed
    time BEFORE it starts, and L2 may simply never run on a slow turn.
    -> (action, plan, info); info["level"] says how far we got.
    """
    t0 = time.perf_counter() if t0 is None else t0
    elapsed = lambda: time.perf_counter() - t0
    info = {"level": "L0"}

    k = policy.should_split(st, unit_count=unit_count, tier=tier)
    if k is not None:
        return ("split", k), plan, {"level": "split"}

    t = time.perf_counter()
    reflex = l0_reflex(st)
    _clock("L0", t)
    if reflex is None:                       # nothing legal: Tier B, then the trade
        return decide(st, plan, unit_count, deadline, tier)
    action = ("move", [reflex])
    if plan is not None:
        step = plan.next_step(st)
        if step is not None:
            action, info["level"] = ("move", [step]), "plan"

    # cheap tightness hint for L1 (ram BFS is radius-limited; a corridor count
    # is not, so L1 must not pay for one)
    _tight_hint[0] = (config.INSTINCT_ABLATE != "ram"
                      and tempo.ram_exposure(st, st.head, tier) > 0)
    key = None
    if elapsed() < config.INSTINCT_L1_MAX_S:
        t = time.perf_counter()
        try:
            moves, key = l1_shallow(st, tier)
            if moves is not None:
                action, info["level"], info["key"] = ("move", moves), "L1", key
        except Exception:
            if config.INSTINCT_RAISE:
                raise
        _clock("L1", t)
    if action[0] == "move":
        plan = plan or Plan()
        plan.advance(action[1][0], st.round)
    info["elapsed"] = elapsed()
    _clock("total", t0)
    return action, plan, info


class Plan:
    __slots__ = ("route", "round")

    def __init__(self, route=(), round_num=-1):
        self.route = list(route)
        self.round = round_num

    def next_step(self, st):
        """The step this plan wants now, if it is still legal."""
        if not self.route or st.round != self.round + 1:
            return None
        d = self.route[0]
        return d if space.walk(st, [d], TIER_A) is not None else None

    def advance(self, taken, round_num):
        if self.route and self.route[0] == taken:
            self.route.pop(0)
        else:
            self.route = []
        self.round = round_num


def l0_reflex(st):
    """Safest legal single step, no search: avoid kelp and bodies, then tiles
    an enemy head can reach, then tiles a lower-id teammate may take."""
    geo = st.geo
    no_ram = config.INSTINCT_ABLATE == "ram"      # see decide_budgeted
    best, best_rank = None, None
    for d in (0, 1, 2, 3):
        # exposure has to be read on the board AFTER the step: our own tail is
        # still blocking enemy paths beforehand, which UNDER-counts the threat
        nxt = policy.after_move(st, [d], TIER_A)
        if nxt is None:
            continue
        n = nxt.head
        rank = (0 if no_ram else -tempo.ram_exposure(nxt, n, TIER_A),
                0 if tempo.yields_to_teammate(nxt, n) else 1,
                sum(1 for m in geo.neighbours(n) if m >= 0 and m not in nxt.body))
        if best_rank is None or rank > best_rank:
            best, best_rank = d, rank
    return best


_tight_hint = [False]      # set by decide_budgeted from the acute check (no extra BFS)


def l1_shallow(st, tier=TIER_A):
    """The whole ranking: Tier A legality, and how many legal moves the step
    leaves us. No control layer and no corridor min-cut - both measured as costs
    (MEASUREMENT.md), and without them nothing here needs a BFS per candidate."""
    return policy.best_move(st, tier=tier, tight=_tight_hint[0])


def decide(st, plan=None, unit_count=1, deadline=None, tier=TIER_A):
    """Run the ladder as far as the budget allows.
    -> (action, plan, info) where action is ("move", [dirs]) or ("split", k)."""
    info = {"level": 0}
    reflex = l0_reflex(st)
    action = ("move", [reflex]) if reflex is not None else None
    k = policy.should_split(st, unit_count=unit_count, tier=tier)
    if k is not None:
        info["level"] = "split"
        return ("split", k), plan, info
    if action is None:                       # nothing legal: Tier B, then ram
        moves, _key = policy.best_move(st, tier=TIER_B)
        if moves is not None:
            return ("move", moves), plan, {"level": "tierB"}
        # doomed: nothing is legal. Ram the biggest head we are allowed to trade
        # with (both dragons die, and they drop ceil(L/2) pearls for a teammate)
        for e in sorted(tempo.ram_threats(st), key=lambda x: -x.length):
            if not policy.may_trade(st, e):
                continue
            for d in (0, 1, 2, 3):
                if st.geo.step(st.head, d) == e.head:
                    return ("move", [d]), plan, {"level": "trade"}
        return None, plan, info
    if plan is not None:
        step = plan.next_step(st)
        if step is not None:
            action = ("move", [step])
            info["level"] = "plan"
    try:
        if deadline is not None:
            deadline.check()
        moves, key = l1_shallow(st, tier)
        if moves is not None:
            action, info["level"], info["key"] = ("move", moves), 1, key
        if deadline is not None:
            deadline.check()
    except Exception:
        pass                                  # keep whatever completed
    if action[0] == "move":
        plan = plan or Plan()
        plan.advance(action[1][0], st.round)
    return action, plan, info
