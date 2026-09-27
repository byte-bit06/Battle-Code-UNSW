"""The engine's side of the helper API, backed by the simulator.

A bot reads the game through helper.Controller / helper.Game. These fakes
answer the same calls from a sim.Sim, so the SAME bot code runs in the local
arena (agents.py), in the HRL training env (hrl_train/botenv.py) and in tests.

`helper` is the bot's own helper module: every bot folder has its own copy,
and each copy's Direction enum is a different class, so the fake must build
its answers from the helper of the bot it is serving.
"""


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
    """What helper.Controller offers, for one dragon on one turn. Only the
    last action counts, like the engine; the sonar message is sent afterwards."""

    def __init__(self, sim, dragon, helper):
        self.sim, self.d, self.h = sim, dragon, helper
        self.dirs = helper.Direction.get_direction_list()
        self.dir_index = {d: i for i, d in enumerate(self.dirs)}
        self.action = None
        self.sonar_out = None
        self.messages = list(dragon.inbox)
        dragon.inbox.clear()
        self._tiles = None

    # --- reading ---
    def get_id(self):
        return self.d.id

    def get_team(self):
        return self.h.Team.A if self.d.team == "A" else self.h.Team.B

    def get_length(self):
        return self.d.length

    def get_dir(self):
        return self.dirs[self.d.dirs[0]]

    def get_position(self):
        x, y = self.d.head
        return self.h.Position(x, y)

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
        sim, h = self.sim, self.h
        x, y = t
        part = None
        o = sim.occ.get(t)
        if o is not None:
            idx = o.cells.index(t)
            part = h.DragonPart(h.Position(x, y), o.id, h.Team.A if o.team == "A" else h.Team.B,
                                self.dirs[o.dirs[idx]], idx == 0)
        types = {0: h.EdgeType.EMPTY, 1: h.EdgeType.KELP, 2: h.EdgeType.PORTAL}
        edges = []
        for d in range(4):
            typ, pid = sim.edge(x, y, d)
            edges.append(h.Edge(d in (0, 2), types[typ], pid if typ == 2 else -1))
        return h.Tile(h.Position(x, y), part, sim.countdown(t), t in sim.pearls, tuple(edges))

    # --- acting ---
    def make_move(self, direction):
        self.action = ("move", [self.dir_index[direction]])

    def make_moves(self, directions):
        self.action = ("move", [self.dir_index[d] for d in directions])

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

    def output_log(self, *text):
        pass
