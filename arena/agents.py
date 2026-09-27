"""Controllers for the local arena.

AgentController runs OUR REAL BOT (mybot/main.py's Brain) in-process. It gets
exactly what the engine would give it: the 7x7 vision as helper Tile objects,
its length, heading, id, team and sonar messages, through a fake Controller
that mimics helper.Controller. So what you see in the arena is the same code
you submit.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mybot"))

import helper                    # noqa: E402  (mybot/helper.py)
import main as botmain           # noqa: E402  (mybot/main.py, provides Brain)
from fake import FakeGame, FakeController   # noqa: E402  (arena/fake.py, shared with hrl_train)


class AgentController:
    """Our bot. One Brain per dragon (dragons share no memory, as in the real game)."""
    kind = "agent"

    def __init__(self, sim):
        self.brain = botmain.Brain(sim.W, sim.H)

    def act(self, sim, dragon):
        game = FakeGame(sim)
        helper.game = game
        ct = FakeController(sim, dragon, helper)
        try:
            self.brain.turn(ct, game)
        except Exception:
            ct.action = ("move", [dragon.dirs[0]])
        return ct.action, ct.sonar_out

    @property
    def target(self):
        return self.brain.target

    @property
    def debug(self):
        return self.brain.debug


class HumanController:
    """Fed by the UI: a direction, a queued sprint, or a split request."""
    kind = "human"

    def __init__(self):
        self.direction = None
        self.sprint = []
        self.split_request = None
        self.ready = False            # turn-based mode: has the player chosen?

    def act(self, sim, dragon):
        if self.split_request:
            n = self.split_request
            self.split_request = None
            self.ready = False
            return ("split", n), None
        if len(self.sprint) >= 2:
            dirs = self.sprint[:max(1, dragon.length - 1)]
            self.sprint = []
            self.direction = dirs[-1]
            self.ready = False
            return ("move", dirs), None
        self.sprint = []
        d = dragon.dirs[0] if self.direction is None else self.direction
        self.ready = False
        return ("move", [d]), None

    @property
    def target(self):
        return None

    debug = ""


def take_turn(sim, dragon):
    """One dragon's full turn: decide, apply, then cast sonar if still alive.
    A child created by a split gets its own fresh AgentController (no memory)."""
    action, message = dragon.controller.act(sim, dragon)
    result = sim.apply(dragon, action)
    if hasattr(result, "cells"):              # split -> new dragon
        result.controller = AgentController(sim)
    if message is not None and dragon.alive:
        sim.sonar(dragon, message)
    return result


def run_headless(map_path, seed=0, duel=False, max_rounds=500):
    """Agent vs agent without graphics (used by tests and for quick checks)."""
    import sim as simmod
    s = simmod.Sim(map_path, seed=seed, duel=duel)
    for d in s.dragons.values():
        d.controller = AgentController(s)
    while not s.over and s.round < max_rounds:
        s.start_round()
        for d in s.turn_order():
            take_turn(s, d)
        s.end_round()
    return s
