"""Entry point. Turn order: Safety -> Forage -> Exploration fallback.

Removed from the old main.py (and why):
  * split-at-length-4 block : kept every dragon at length 2-3 (bad for the
    longest-dragon tiebreak, and too short to sprint). See maybe_split().
  * get_manhattan_distance / a_star_search : ignored portals and only
    searched visible tiles -> replaced by geometry.py + routing.py.
  * is_safe : replaced by safety.py (frozen interface for the Defence team).
  * nearest-pearl + random exploration : replaced by forage.forage_turn().
"""

import time

import helper as unswbc
from helper import Direction

import comms
import config
import forage
import memory
import safety
import snapshot

DIRS = Direction.get_direction_list()          # index 0 N, 1 E, 2 S, 3 W
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}


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
    local arena (arena/play.py) can run many dragons in one process."""

    def __init__(self, width: int, height: int):
        self.mem = memory.WorldMemory(width, height)
        self.comms = comms.Comms()
        self.first_turn = True
        self.debug = ""
        self.target = None

    def maybe_split(self, ct, snap, safe) -> bool:
        """Split policy (engine-verified: a splitting parent does NOT move this turn,
        it just loses its rear `child` segments).

        1. Emergency ONLY (default): `safe` is empty, meaning every direction is
           kelp, a body segment or a head - moving anywhere is certain death. We
           split instead: standing still is collision-free, and the shorter body
           opens space behind us. A dragon that still has any legal move never splits.
        2. Growth/redundancy splitting is OFF (config.ENABLE_SPLIT = False) until
           single dragons forage well. TODO(Memory_Engine) owns turning it back on.
        """
        L = snap.my_len
        if not safe and config.ENABLE_EMERGENCY_SPLIT and L >= 4:
            child = max(2, L // 2)
            if ct.can_split(child):
                ct.do_split(child)
                return True
        if not config.ENABLE_SPLIT:
            return False
        if (snap.round < config.SPLIT_LAST_ROUND and L >= config.SPLIT_MIN_LENGTH
                and ct.get_unit_count() < config.SPLIT_TARGET_UNITS
                and ct.can_split(config.SPLIT_CHILD_SIZE)):
            ct.do_split(config.SPLIT_CHILD_SIZE)
            return True
        return False

    def turn(self, ct, game) -> None:
        # A new process (every split child!) pays ~40M points compiling modules on
        # its first turn, so the first turn gets a much smaller search budget.
        budget = config.FIRST_TURN_BUDGET_S if self.first_turn else config.TIME_BUDGET_S
        self.first_turn = False
        deadline = Deadline(budget)
        mem = self.mem
        snap = snapshot.build(ct, game, mem.geo, DIR_INDEX)
        mem.update(snap)
        if config.ENABLE_SONAR:
            self.comms.receive(ct.get_sonar_messages(), snap, mem)
        safe = safety.get_safe_moves(snap, mem)
        self.target = None
        if self.maybe_split(ct, snap, safe):
            self.debug = "SPLIT (no legal move)"
            return
        fallback = safety.emergency_move(snap, mem, safe)
        forage.LAST_DEBUG = ""
        try:
            action = forage.forage_turn(snap, mem, safe, deadline)
        except forage.ForageTimeout:
            action = [fallback]
        except Exception:
            action = [fallback]          # never crash, never output nothing
        if not action:
            action = [fallback]
        if len(action) == 1:
            ct.make_move(DIRS[action[0]])
        else:
            ct.make_moves([DIRS[d] for d in action])
        self.target = forage.LAST_TARGET[0]
        self.debug = forage.LAST_DEBUG
        if config.ENABLE_SONAR:
            target, tdist = forage.LAST_TARGET
            msg = self.comms.choose(snap, mem, target, tdist, mem.deaths_seen)
            if msg is not None:
                ct.send_sonar(msg)
        if config.DEBUG:
            used = (time.perf_counter() - deadline.t0) * 1000
            ct.set_indicator_string(f"{forage.LAST_DEBUG} {used:.1f}ms")


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
