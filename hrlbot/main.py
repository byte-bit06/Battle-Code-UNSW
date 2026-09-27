"""HRL bot entry point.

Every turn:
  1. build state      snapshot.py + memory.py + symmetry.py (+ sonar in)
  2. manager          only when the current option stopped, ran for
                      HRL_DECIDE_EVERY turns, or danger just appeared:
                      mask options whose can_start fails, rank the rest
  3. option           option.step(t) -> move / sprint / split; if it has
                      nothing to do, fall back down the manager's ranking
  4. safety shield    options.shield() vetoes anything that dies
  5. sonar out        comms.py, unchanged

The first turn of every process (including each split child) takes the cheap
path of the pre-HRL bot: imports alone cost ~78M of the 100M points.
See HRL_CHECKLIST.md for the design.
"""

import time

import helper as unswbc
from helper import Direction

import comms
import config
import forage
import memory
import options
import safety
import snapshot

# features, manager and manager_weights are imported on a dragon's SECOND turn
# (the first one never consults the manager): measured on the judge, a first
# turn already spends ~80M of the 100M points, most of it on imports.
features = manager = None


def _load_manager_modules():
    global features, manager
    if manager is None:
        import features as _f
        import manager as _m
        features, manager = _f, _m

DIRS = Direction.get_direction_list()          # index 0 N, 1 E, 2 S, 3 W
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}
EXPLORE = options.IDX["EXPLORE"]


class Deadline:
    """perf_counter is a virtual clock on the judge (1 ns == 1 CPU point)."""
    __slots__ = ("t0", "budget")

    def __init__(self, budget_s: float):
        self.t0 = time.perf_counter()
        self.budget = budget_s

    def remaining(self) -> float:
        return self.budget - (time.perf_counter() - self.t0)

    def check(self) -> None:
        if time.perf_counter() - self.t0 > self.budget:
            raise forage.ForageTimeout()


class Brain:
    """One dragon's decision maker. All per-dragon state lives here, so the
    simulator (arena/, hrl_train/) can run many dragons in one process."""

    def __init__(self, width: int, height: int, manager_obj=None):
        self.mem = memory.WorldMemory(width, height)
        self.comms = comms.Comms()
        self.first_turn = True
        self.debug = ""
        self.target = None
        self.options = options.make_options()
        self.manager = manager_obj  # built lazily on the first decision (see above)
        self.cur = None             # index of the running option
        self.cur_turns = 0
        self.cur_danger = False
        # training hooks (unused in a real match)
        self.recorder = None        # fn(dict) called once per manager decision
        self.epsilon = config.HRL_EPSILON
        self.rng = None

    # ------------------------------------------------------------ manager --
    def _decide(self, t):
        _load_manager_modules()
        if self.manager is None:
            self.manager = manager.make()
        mask = []
        for o in self.options:
            try:
                mask.append(bool(o.can_start(t)))
            except Exception:
                mask.append(False)
        mask[EXPLORE] = True        # always available: the manager can't be stuck
        feats = features.build(t, mask)
        ranked = self.manager.rank(feats, mask)
        ranked = manager.explore_rank(ranked, mask, self.epsilon, self.rng)
        return feats, mask, ranked or [EXPLORE]

    def _step(self, i, t):
        # heavy options must not push the turn past the judge's CPU limit
        if time.perf_counter() - t.deadline.t0 > config.INSTINCT_HARD_S:
            return None
        try:
            return self.options[i].step(t)
        except Exception:
            if config.INSTINCT_RAISE:
                raise
            return None

    def run_options(self, t):
        cur = self.cur
        stopped = cur is None
        if not stopped:
            o = self.options[cur]
            try:
                stopped = o.one_shot or o.should_stop(t)
            except Exception:
                stopped = True
        danger = t.danger()
        interrupt = danger and not self.cur_danger
        decision = None
        if stopped or interrupt or self.cur_turns >= config.HRL_DECIDE_EVERY:
            decision = self._decide(t)
            ranked = decision[2]
        else:
            ranked = [cur]
        action, chosen = None, None
        for n, i in enumerate(ranked[:4]):
            if i != cur or stopped:
                self.options[i].start(t)
            action = self._step(i, t)
            if action is not None:
                chosen = i
                break
            if decision is None:     # the running option ran dry: ask the manager
                decision = self._decide(t)
                for j in decision[2][:3]:
                    self.options[j].start(t)
                    action = self._step(j, t)
                    if action is not None:
                        chosen = j
                        break
                break
        if action is None and chosen is None:
            chosen = EXPLORE
            self.options[EXPLORE].start(t)
            action = self._step(EXPLORE, t)
        if decision is not None:
            self.cur_turns = 0
            self.cur_danger = danger
            if self.recorder is not None:
                feats, mask, _r = decision
                self.recorder({"round": t.snap.round, "feats": feats, "mask": mask,
                               "option": chosen, "length": t.snap.my_len})
        if chosen != self.cur:
            self.cur_turns = 0
        self.cur = chosen
        self.cur_turns += 1
        return action

    # --------------------------------------------------------------- turn --
    def turn(self, ct, game) -> None:
        # A new process (every split child!) pays ~40M points compiling modules on
        # its first turn, so the first turn gets a much smaller search budget.
        budget = config.FIRST_TURN_BUDGET_S if self.first_turn else config.TIME_BUDGET_S
        was_first, self.first_turn = self.first_turn, False
        deadline = Deadline(budget)
        mem = self.mem
        snap = snapshot.build(ct, game, mem.geo, DIR_INDEX)
        mem.update(snap)
        if config.ENABLE_SONAR:
            self.comms.receive(ct.get_sonar_messages(), snap, mem)
        t = options.Turn(ct, snap, mem, deadline, was_first)
        forage.LAST_TARGET = (None, None)
        forage.LAST_DEBUG = ""
        action = None
        L = snap.my_len
        if not t.legal and config.ENABLE_EMERGENCY_SPLIT and L >= 4 and ct.can_split(max(2, L // 2)):
            action = ("split", max(2, L // 2))      # no legal move: a splitter stands still
            self.debug = "SPLIT (no legal move)"
        elif not t.legal:
            action = None            # every step is death: emergency_move picks a head if any
        elif was_first:
            try:                                     # the pre-HRL bot's cheap first turn
                mv = forage.forage_turn(snap, mem, t.safe, deadline)
                action = ("move", mv) if mv else None
            except Exception:
                action = None
            self.debug = "first turn"
        else:
            action = self.run_options(t)
            self.debug = options.NAMES[self.cur] if self.cur is not None else ""
        action = options.shield(t, action)
        if action is None:
            action = ("move", [safety.emergency_move(snap, mem, t.safe)])
        if action[0] == "split":
            ct.do_split(action[1])
            return
        moves = action[1]
        if len(moves) == 1:
            ct.make_move(DIRS[moves[0]])
        else:
            ct.make_moves([DIRS[d] for d in moves])
        self.target = forage.LAST_TARGET[0]
        if config.ENABLE_SONAR:
            target, tdist = forage.LAST_TARGET
            msg = self.comms.choose(snap, mem, target, tdist, mem.deaths_seen)
            if msg is not None:
                ct.send_sonar(msg)
        if config.DEBUG:
            used = (time.perf_counter() - deadline.t0) * 1000
            ct.set_indicator_string(f"{self.debug} {used:.1f}ms")


def main() -> None:
    ct, game = unswbc.init()
    brain = Brain(game.width, game.height)
    while unswbc.update(ct, game):
        try:
            brain.turn(ct, game)
        except Exception:
            # last line of defence: some action must always be sent
            ct.make_move(ct.get_dir())
        unswbc.end_turn()


if __name__ == "__main__":
    main()
