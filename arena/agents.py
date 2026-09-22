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
from helper import Direction, EdgeType, Team, Position, Tile, DragonPart, Edge  # noqa: E402
import main as botmain           # noqa: E402  (mybot/main.py, provides Brain)

DIRS = Direction.get_direction_list()
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}
EDGE_TYPES = {0: EdgeType.EMPTY, 1: EdgeType.KELP, 2: EdgeType.PORTAL}


class FakeGame:
    def __init__(self, sim):
        self.width, self.height = sim.W, sim.H
        self.round_num = sim.round
        self.unit_limit = 64

    def get_round_num(self):
        return self.round_num

    def get_map_size(self):
        return self.width, self.height

    def get_unit_limit(self):
        return self.unit_limit


class FakeController:
    """The subset of helper.Controller our bot uses, backed by the simulator."""

    def __init__(self, sim, dragon, game):
        self.sim, self.d, self.game = sim, dragon, game
        self.action = None
        self.sonar_out = None
        self.messages = list(dragon.inbox)
        dragon.inbox.clear()
        self._tiles = None

    # --- reading ---
    def get_id(self):
        return self.d.id

    def get_team(self):
        return Team.A if self.d.team == "A" else Team.B

    def get_length(self):
        return self.d.length

    def get_dir(self):
        return DIRS[self.d.dirs[0]]

    def get_position(self):
        x, y = self.d.head
        return Position(x, y)

    def get_unit_count(self):
        return len(self.sim.alive_ids(self.d.team))

    def get_sonar_messages(self):
        return list(self.messages)

    def get_tiles(self):
        if self._tiles is None:
            self._tiles = [self._tile(t) for t in self.sim.vision_tiles(self.d)]
        return list(self._tiles)

    def get_tile(self, pos):
        for t in self.get_tiles():
            if t.position.x == pos.x and t.position.y == pos.y:
                return t
        return None

    def _tile(self, t):
        sim = self.sim
        x, y = t
        part = None
        o = sim.occ.get(t)
        if o is not None:
            idx = o.cells.index(t)
            part = DragonPart(Position(x, y), o.id, Team.A if o.team == "A" else Team.B,
                              DIRS[o.dirs[idx]], idx == 0)
        edges = []
        for d in range(4):
            typ, pid = sim.edge(x, y, d)
            edges.append(Edge(d in (0, 2), EDGE_TYPES[typ], pid if typ == 2 else -1))
        return Tile(Position(x, y), part, sim.countdown(t), t in sim.pearls, tuple(edges))

    # --- acting (only the last action counts, like the engine) ---
    def make_move(self, direction):
        self.action = ("move", [DIR_INDEX[direction]])

    def make_moves(self, directions):
        self.action = ("move", [DIR_INDEX[d] for d in directions])

    def can_split(self, child_size):
        L = self.d.length
        return child_size >= 2 and L - child_size >= 2 and self.get_unit_count() < 64

    def do_split(self, child_size):
        self.action = ("split", child_size)

    def send_sonar(self, message):
        if isinstance(message, int) and 0 <= message <= 0xFFFFFFFF:
            self.sonar_out = message
            return True
        return False

    def set_indicator_string(self, text):
        self.d.indicator = str(text)

    def output_log(self, text):
        pass


class AgentController:
    """Our bot. One Brain per dragon (dragons share no memory, as in the real game)."""
    kind = "agent"

    def __init__(self, sim):
        self.brain = botmain.Brain(sim.W, sim.H)

    def act(self, sim, dragon):
        game = FakeGame(sim)
        helper.game = game
        ct = FakeController(sim, dragon, game)
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
