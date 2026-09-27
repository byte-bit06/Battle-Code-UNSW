"""Headless games on the Python simulator (arena/sim.py) with ANY two bots.

Every bot folder uses the same module names (config, forage, main, ...), so a
bot is loaded once into its own set of module objects and those are swapped
into sys.modules right before each of its dragons takes a turn. Lazy imports
inside a bot (`from instinct import ladder`) therefore resolve to that bot's
own copy. Each dragon gets its own Brain, exactly as in the real game (a
split child starts with a blank one).

    spec = BotSpec.load("hrlbot")
    result = play_game("maps/arena.map", seed=1, a=spec, b=BotSpec.load("mybot"))
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "arena"))

import sim as simmod   # noqa: E402  (arena/sim.py)
from fake import FakeGame, FakeController   # noqa: E402,F401  (arena/fake.py)


# ============================================================ bot loading ==
class BotSpec:
    """One bot folder's modules, plus how to build a Brain for each dragon."""

    _cache = {}

    def __init__(self, path, mods):
        self.path = path
        self.mods = mods
        self.helper = mods["helper"]
        self.main = mods["main"]
        self.config = mods["config"]
        self.brain_factory = None     # fn(spec, sim, dragon) -> Brain; default below

    @classmethod
    def load(cls, bot_dir):
        path = os.path.abspath(os.path.join(ROOT, bot_dir))
        if path in cls._cache:            # modules are shared, the wrapper is not,
            return cls(path, cls._cache[path])   # so a bot can play itself differently
        names = set()
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            rel = os.path.relpath(root, path)
            pkg = "" if rel == "." else rel.replace(os.sep, ".") + "."
            for f in files:
                if f.endswith(".py"):
                    mod = f[:-3]
                    names.add(pkg[:-1] if mod == "__init__" else pkg + mod)
        top = {n.split(".")[0] for n in names}
        saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] in top}
        for k in saved:
            del sys.modules[k]
        sys.path.insert(0, path)
        try:
            import importlib
            for n in sorted(names, key=lambda n: (n != "main", n)):
                try:
                    importlib.import_module(n)
                except Exception:
                    pass                  # e.g. no manager_weights.py yet
            mods = {k: v for k, v in sys.modules.items() if k.split(".")[0] in top}
        finally:
            sys.path.remove(path)
            for k in list(sys.modules):
                if k.split(".")[0] in top:
                    del sys.modules[k]
            sys.modules.update(saved)
        cls._cache[path] = mods
        return cls(path, mods)

    def activate(self):
        """Install this bot's modules. Pair with `restored()` so they don't leak
        into code that imports another bot's modules later (e.g. the tests)."""
        sys.modules.update(self.mods)

    def new_brain(self, sim, dragon):
        self.activate()
        if self.brain_factory is not None:
            return self.brain_factory(self, sim, dragon)
        return self.main.Brain(sim.W, sim.H)


class restored:
    """Context manager: put every bot module name in sys.modules back the way it
    was afterwards (names a bot added are removed again)."""

    def __enter__(self):
        names = {k for mods in BotSpec._cache.values() for k in mods}
        self.saved = {k: sys.modules.get(k) for k in names}
        return self

    def __exit__(self, *exc):
        names = {k for mods in BotSpec._cache.values() for k in mods} | set(self.saved)
        for k in names:
            before = self.saved.get(k)
            if before is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = before
        return False


# ================================================================== games ==
class DragonLog:
    """Per-dragon bookkeeping for rewards."""
    __slots__ = ("id", "team", "decisions", "kills", "death_round", "death_len",
                 "death_cause", "split_credit", "born")

    def __init__(self, did, team, born):
        self.id = did
        self.team = team
        self.born = born
        self.decisions = []        # dicts from Brain.recorder
        self.kills = []            # (round, enemy length)
        self.death_round = None
        self.death_len = 0
        self.death_cause = ""
        self.split_credit = []     # (round, child length, child id)


class Scripted:
    """A non-bot player for scenarios: any object with act(sim, dragon) -> action.
    `make(sim, dragon)` returns the per-dragon player."""

    def __init__(self, make):
        self.make = make


def play_game(*args, **kwargs):
    """See _play_game. The bots' modules are swapped out again afterwards."""
    with restored():
        return _play_game(*args, **kwargs)


def _play_game(map_path, seed, a, b, max_rounds=500, record=(), on_brain=None,
               setup=None, stop=None, start_round=0):
    """Play one game. `a`, `b` are BotSpecs (or Scripted players). `record`
    lists the teams ("A"/"B") whose Brains get a decision recorder.
    on_brain(brain, dragon) runs after each Brain is built (training uses it to
    set epsilon etc.). Scenarios use setup(sim) (e.g. drop pearls), stop(sim)
    (end early) and start_round (e.g. start in the late game).
    -> dict(winner, result, rounds, logs, sim)"""
    s = simmod.Sim(map_path, seed=seed)
    s.round = start_round
    if setup is not None:
        setup(s)
    specs = {"A": a, "B": b}
    brains = {}
    logs = {}

    def attach(d):
        spec = specs[d.team]
        logs[d.id] = log = DragonLog(d.id, d.team, s.round)
        if isinstance(spec, Scripted):
            brains[d.id] = spec.make(s, d)
            return
        brain = spec.new_brain(s, d)
        if d.team in record and hasattr(brain, "recorder"):
            brain.recorder = log.decisions.append
        if on_brain is not None:
            on_brain(brain, d)
        brains[d.id] = brain

    for d in list(s.dragons.values()):
        attach(d)
    while not s.over and s.round < max_rounds:
        s.start_round()
        for d in s.turn_order():
            spec = specs[d.team]
            if isinstance(spec, Scripted):
                ct = FakeController.__new__(FakeController)
                ct.sonar_out = None
                ct.action = brains[d.id].act(s, d)[0]
            else:
                spec.activate()
                spec.helper.game = game = FakeGame(s)
                ct = FakeController(s, d, spec.helper)
                try:
                    brains[d.id].turn(ct, game)
                except Exception:
                    if os.environ.get("HRL_RAISE"):
                        raise
                    ct.action = ("move", [d.dirs[0]])
            before = {i for i, x in s.dragons.items() if x.alive}
            lengths = {i: s.dragons[i].length for i in before}
            result = s.apply(d, ct.action)
            if hasattr(result, "cells"):                       # a split child
                logs[d.id].split_credit.append((s.round, result.length, result.id))
                attach(result)
            if ct.sonar_out is not None and d.alive:
                s.sonar(d, ct.sonar_out)
            dead = [i for i in before if not s.dragons[i].alive]
            for i in dead:
                lg = logs[i]
                lg.death_round, lg.death_len = s.round, lengths[i]
                lg.death_cause = s.dragons[i].death_cause
            _credit_kills(s, d, dead, lengths, logs)
        s.end_round()
        if stop is not None and not s.over and stop(s):
            return {"winner": None, "result": "stopped", "rounds": s.round, "logs": logs,
                    "sim": s}
    if not s.over:
        s.round = max(s.round, simmod.MAX_ROUNDS - 1)
        s.end_round()
    return {"winner": s.winner, "result": s.result, "rounds": s.round, "logs": logs,
            "sim": s}


def _credit_kills(s, mover, dead, lengths, logs):
    """Who gets credit for an enemy death this move:
    * the mover rammed an enemy head (both die) -> the mover;
    * the mover crashed into dragon X's body   -> X, if X is on the other team."""
    for i in dead:
        victim = s.dragons[i]
        if i == mover.id:
            cause = victim.death_cause
            if cause.startswith("hit dragon "):
                killer = s.dragons.get(int(cause.split()[-1]))
                if killer is not None and killer.team != victim.team:
                    logs[killer.id].kills.append((s.round, lengths[i]))
        elif victim.team != mover.team:
            logs[mover.id].kills.append((s.round, lengths[i]))
