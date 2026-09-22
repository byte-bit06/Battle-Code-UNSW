"""Local re-implementation of the UNSW Battlecode rules, for play and testing.

The official engine (`unswbc run`) is always the source of truth; this exists
so a human can play against our agent with a full-board view. Rules follow
the docs, plus details verified against the real engine with probe bots:
  * map edges parse identically (22,724 edges checked, 0 mismatches)
  * portal exits, spawn timing (a pearl appears the round after countdown 1,
    only on an empty tile), and "a splitting dragon doesn't move".

Coordinates are (x, y); directions are ints 0 N, 1 E, 2 S, 3 W.
"""
import random

import mapfile

DX = (0, 1, 0, -1)
DY = (-1, 0, 1, 0)
OPP = (2, 3, 0, 1)
MAX_ROUNDS = 500
UNIT_LIMIT = 64
VISION = 3
KELP_HIT = "kelp"


class Dragon:
    __slots__ = ("id", "team", "cells", "dirs", "alive", "inbox", "controller",
                 "death_cause", "death_round", "indicator", "born")

    def __init__(self, did, team, cells, dirs, born=0):
        self.id = did
        self.team = team          # "A" or "B"
        self.cells = cells        # head first
        self.dirs = dirs          # head: heading; body: direction towards the head
        self.alive = True
        self.inbox = []           # sonar messages, read at the start of its next turn
        self.controller = None
        self.death_cause = ""
        self.death_round = -1
        self.indicator = ""
        self.born = born

    @property
    def head(self):
        return self.cells[0]

    @property
    def length(self):
        return len(self.cells)


class Sim:
    def __init__(self, map_path, seed=None, duel=False):
        self.map = m = mapfile.load(map_path)
        self.W, self.H = m.W, m.H
        self.rng = random.Random(seed)
        self.round = 0
        self.over = False
        self.result = ""
        self.winner = None
        self.events = []          # (round, text)
        self.pearls = set()
        self.occ = {}             # (x, y) -> Dragon
        self.dragons = {}
        self._build_edges()
        self._build_countdowns()
        starts = list(m.dragons)
        if duel:                                   # first dragon of each team only
            keep = {next(i for i, tm, _ in starts if tm == "A"), next(i for i, tm, _ in starts if tm == "B")}
            starts = [s for s in starts if s[0] in keep]
        for did, team, cells in starts:
            cells = [tuple(c) for c in cells]
            dirs = [self._dir_between(cells[i], cells[i - 1]) if i else
                    (self._dir_between(cells[1], cells[0]) if len(cells) > 1 else 0)
                    for i in range(len(cells))]
            d = Dragon(did, team, cells, dirs)
            self.dragons[did] = d
            for c in cells:
                self.occ[c] = d
        self.next_id = max(self.dragons) + 1 if self.dragons else 0

    # ------------------------------------------------------------ map --
    def _build_edges(self):
        m = self.map
        self.portals = {}
        for (x, y), (t, pid) in m.north.items():
            if t == mapfile.PORTAL:
                self.portals.setdefault(pid, []).append(("N", x, y))
        for (x, y), (t, pid) in m.west.items():
            if t == mapfile.PORTAL:
                self.portals.setdefault(pid, []).append(("W", x, y))

    def edge(self, x, y, d):
        return mapfile.edge_of(self.map, x, y, d)

    def _edge_rep(self, x, y, d):
        W, H = self.W, self.H
        if d == 0:
            return ("N", x, y)
        if d == 2:
            return ("N", x, (y + 1) % H)
        if d == 3:
            return ("W", x, y)
        return ("W", (x + 1) % W, y)

    def step(self, pos, d):
        """Tile reached moving from pos in direction d; KELP_HIT for kelp;
        portals teleport (you exit on the far side of the partner edge)."""
        x, y = pos
        t, pid = self.edge(x, y, d)
        if t == mapfile.KELP:
            return KELP_HIT
        if t == mapfile.PORTAL:
            me = self._edge_rep(x, y, d)
            for rep in self.portals.get(pid, ()):
                if rep != me:
                    kind, px, py = rep
                    if kind == "N":        # horizontal edge: north tile (px, py-1), south tile (px, py)
                        return (px, py) if d == 2 else (px, (py - 1) % self.H)
                    return (px, py) if d == 1 else ((px - 1) % self.W, py)
        return ((x + DX[d]) % self.W, (y + DY[d]) % self.H)

    def _dir_between(self, a, b):
        for d in range(4):
            if self.step(a, d) == b:
                return d
        for d in range(4):
            if ((a[0] + DX[d]) % self.W, (a[1] + DY[d]) % self.H) == b:
                return d
        return 0

    def mirror(self, x, y):
        s = self.map.symmetry
        if s == "y":
            return (self.W - 1 - x, y)
        if s == "x":
            return (x, self.H - 1 - y)
        if s == "xy":
            return (self.W - 1 - x, self.H - 1 - y)
        return (x, y)

    def _build_countdowns(self):
        """Mirror tiles share one countdown (they spawn together if empty)."""
        self.groups = {}          # key -> [tiles]
        self.group_of = {}
        for (x, y), (lo, hi) in self.map.gaps.items():
            if hi <= 0:
                continue
            key = min((x, y), self.mirror(x, y))
            self.groups.setdefault(key, []).append((x, y))
            self.group_of[(x, y)] = key
        self.cd = {k: self.rng.randint(*self.map.gaps[k if k in self.map.gaps else tiles[0]])
                   for k, tiles in self.groups.items()}

    def countdown(self, tile):
        k = self.group_of.get(tile)
        return -1 if k is None else self.cd[k]

    # ---------------------------------------------------------- rounds --
    def alive_ids(self, team=None):
        return sorted(i for i, d in self.dragons.items() if d.alive and (team is None or d.team == team))

    def start_round(self):
        """Countdowns tick at the start of each round, before anyone moves."""
        for k, tiles in self.groups.items():
            self.cd[k] -= 1
            if self.cd[k] <= 0:
                for t in tiles:
                    if t not in self.occ and t not in self.pearls:
                        self.pearls.add(t)
                lo, hi = self.map.gaps[tiles[0]]
                self.cd[k] = self.rng.randint(lo, hi)

    def turn_order(self):
        """Yields dragons in ascending id; children born this round act later in it."""
        last = -1
        while True:
            nxt = [i for i, d in self.dragons.items() if d.alive and i > last]
            if not nxt:
                return
            last = min(nxt)
            yield self.dragons[last]

    def end_round(self):
        a, b = self.alive_ids("A"), self.alive_ids("B")
        self.round += 1
        if not a and not b:
            self._finish(None, "both teams eliminated")
        elif not a:
            self._finish("B", "by elimination")
        elif not b:
            self._finish("A", "by elimination")
        elif self.round >= MAX_ROUNDS:
            la = max(self.dragons[i].length for i in a)
            lb = max(self.dragons[i].length for i in b)
            if la != lb:
                self._finish("A" if la > lb else "B", "on longest dragon")
            else:
                ta = sum(self.dragons[i].length for i in a)
                tb = sum(self.dragons[i].length for i in b)
                if ta != tb:
                    self._finish("A" if ta > tb else "B", "on total length")
                else:
                    self._finish(None, "draw after 500 rounds")

    def _finish(self, winner, how):
        self.over = True
        self.winner = winner
        self.result = (f"Team {winner} wins {how}" if winner else how.capitalize())
        self.log(self.result)

    def log(self, text):
        self.events.append((self.round, text))

    # --------------------------------------------------------- actions --
    def apply(self, d, action):
        """action: ("move", [dirs]) | ("split", n) | None (no valid action)."""
        if action is None:
            return self.kill(d, "no valid action")
        kind, arg = action
        if kind == "split":
            return self.split(d, arg)
        dirs = list(arg)
        if not dirs or any(x not in (0, 1, 2, 3) for x in dirs):
            return self.kill(d, "no valid action")
        for i, direction in enumerate(dirs):
            if i >= 1:                           # every extra step costs a segment
                if d.length - 1 < 2:
                    return self.kill(d, "over-sprinted")
                tail = d.cells.pop()
                d.dirs.pop()
                del self.occ[tail]
            if not self._step_once(d, direction):
                return False
        return True

    def _step_once(self, d, direction):
        nxt = self.step(d.head, direction)
        if nxt == KELP_HIT:
            self.kill(d, "hit kelp")
            return False
        other = self.occ.get(nxt)                # checked BEFORE anything moves
        if other is not None:
            if other is d:
                self.kill(d, "hit itself")
            elif other.head == nxt:
                self.kill(d, "head-to-head")
                self.kill(other, "head-to-head")
            else:
                self.kill(d, f"hit dragon {other.id}")
            return False
        d.cells.insert(0, nxt)
        d.dirs[0] = direction                    # old head now points to the new head
        d.dirs.insert(0, direction)
        self.occ[nxt] = d
        if nxt in self.pearls:
            self.pearls.discard(nxt)             # grow: tail stays this step
        else:
            tail = d.cells.pop()
            d.dirs.pop()
            del self.occ[tail]
        return True

    def split(self, d, n):
        L = d.length
        if n < 2 or L - n < 2 or len(self.alive_ids(d.team)) >= UNIT_LIMIT:
            return self.kill(d, "illegal split")
        rear = d.cells[L - n:]
        rear_dirs = d.dirs[L - n:]
        d.cells = d.cells[:L - n]
        d.dirs = d.dirs[:L - n]
        cells = list(reversed(rear))
        # child faces away from the parent; body segments point towards the new head
        dirs = [OPP[rear_dirs[n - 1]]] + [OPP[rear_dirs[n - i]] for i in range(1, n)]
        child = Dragon(self.next_id, d.team, cells, dirs, born=self.round)
        self.next_id += 1
        self.dragons[child.id] = child
        for c in cells:
            self.occ[c] = child
        self.log(f"dragon {d.id} split off dragon {child.id} (length {n})")
        return child

    def kill(self, d, cause):
        if not d.alive:
            return False
        d.alive = False
        d.death_cause = cause
        d.death_round = self.round
        for i, c in enumerate(d.cells):
            if self.occ.get(c) is d:
                del self.occ[c]
            if i % 2 == 0:
                self.pearls.add(c)               # every second segment from the head
        self.log(f"dragon {d.id} ({d.team}, length {d.length}) died: {cause}")
        return False

    def sonar(self, d, message):
        """Ray from the head in the facing direction; first dragon hit receives it."""
        if not d.alive:
            return None
        pos = d.head
        for _ in range(self.W + self.H):
            pos = self.step(pos, d.dirs[0])
            if pos == KELP_HIT:
                return None
            other = self.occ.get(pos)
            if other is not None:
                other.inbox.append(message)
                return other
        return None

    # ---------------------------------------------------------- vision --
    def vision_tiles(self, d):
        hx, hy = d.head
        return [((hx + dx) % self.W, (hy + dy) % self.H)
                for dy in range(-VISION, VISION + 1) for dx in range(-VISION, VISION + 1)]
