"""One small test board per option (Phase 1/2/4 of HRL_CHECKLIST.md).

Each scenario is a board where one option should clearly help. It runs twice:
  forced    the manager must pick the option under test whenever its
            initiation set holds (scripted ranking otherwise)
  scripted  the plain scripted manager (never picks the new options)
so every row says whether the option beats the baseline in its own niche.

    python hrl_train/scenarios.py                  # all scenarios, 8 seeds
    python hrl_train/scenarios.py HUNT RAM_TRADE --seeds 16
"""
import argparse
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import botenv   # noqa: E402

TMP = os.path.join(os.environ.get("TEMP", "/tmp"), "hrl_scenarios")
DXY = ((0, -1), (1, 0), (0, 1), (-1, 0))


# ================================================================ boards ==
def write_map(path, W, H, dragons, kelp=(), spawn=(), portals=(), gap=(8, 12)):
    """dragons: [(team, [(x, y) head first...])] in id order.
    kelp: (x, y, 'N'|'W') edges. spawn: tiles that grow pearls (gap range).
    portals: (x, y, 'N'|'W', pid)."""
    lines = [f"MAP {W} {H}"]
    for item in spawn:
        (x, y), g = (item, gap) if len(item) == 2 and isinstance(item[0], int) else item
        lines.append(f"TILE {x} {y} {g[0]} {g[1]}")
    S = 2 * (W + 1)
    idx = lambda x, y, side: y * S + (x if side == "N" else W + 1 + x)
    for (x, y, side) in kelp:
        lines.append(f"EDGE {idx(x, y, side)} 1 -1")
    for (x, y, side, pid) in portals:
        lines.append(f"EDGE {idx(x, y, side)} 2 {pid}")
    for team, cells in dragons:
        flat = " ".join(f"{x} {y}" for x, y in cells)
        lines.append(f"DRAGON {0 if team == 'A' else 1} {len(cells)} {flat}")
    os.makedirs(TMP, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def border(W, H):
    """Kelp all round, so the board does not wrap."""
    return ([(x, 0, "N") for x in range(W)] + [(0, y, "W") for y in range(H)])


def line(x, y, n, dx=-1, dy=0):
    return [(x + i * dx, y + i * dy) for i in range(n)]


# ============================================================== players ==
def bfs(sim, start, blocked=()):
    dist = {start: 0}
    queue = [start]
    qi = 0
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        for d in range(4):
            n = sim.step(cur, d)
            if n == "kelp" or n in dist or n in blocked:
                continue
            dist[n] = dist[cur] + 1
            queue.append(n)
    return dist


class Chaser:
    """Cheats (reads the whole board): runs at the longest enemy head."""

    def act(self, sim, d):
        prey = [x for x in sim.dragons.values() if x.alive and x.team != d.team]
        if not prey:
            return ("move", [d.dirs[0]]), None
        goal = max(prey, key=lambda x: x.length).head
        blocked = {c for x in sim.dragons.values() if x.alive for c in x.cells}
        blocked.discard(goal)
        dist = bfs(sim, goal, blocked - {d.head})
        best, best_v = d.dirs[0], None
        for di in range(4):
            n = sim.step(d.head, di)
            if n == "kelp":
                continue
            if sim.occ.get(n) is not None and n != goal:
                continue
            v = dist.get(n, 10 ** 6)
            if best_v is None or v < best_v:
                best, best_v = di, v
        return ("move", [best]), None


class Coiler:
    """Length-3 dragon circling a 2x2 square forever (a passive neighbour)."""

    def act(self, sim, d):
        h, neck = d.cells[0], d.cells[1]
        for di in range(4):                 # keep turning the same way round
            n = sim.step(h, di)
            if n != "kelp" and n not in sim.occ and n != neck:
                return ("move", [di]), None
        return ("move", [d.dirs[0]]), None


# ============================================================ scenarios ==
# Each returns dict(map, rounds, setup, stop, metric, opp) where metric(sim, a)
# -> (success: bool, value: float) and `a` holds per-run observations.

def s_forage(seed, rng):
    W = H = 16
    me = line(8, 8, 3)
    m = write_map(f"{TMP}/forage_{seed}.map", W, H, [("A", me), ("B", [(1, 1), (2, 1), (2, 2)])])
    spots = set()
    while len(spots) < 8:
        p = (8 + rng.randint(-6, 6), 8 + rng.randint(-6, 6))
        if p not in me and abs(p[0] - 8) + abs(p[1] - 8) >= 2 and p[1] > 3:
            spots.add(p)
    return dict(map=m, rounds=40, setup=lambda s: s.pearls.update(spots), opp="coiler",
                metric=lambda s, a: _grown(s, 3, 6))


def s_camp(seed, rng):
    W = H = 16
    me = line(8, 8, 3)
    spawn = [((8 + dx, 8 + dy), (5, 7)) for dx, dy in ((2, 0), (3, 1), (2, 2), (-2, 1), (-3, -2), (0, -3))]
    m = write_map(f"{TMP}/camp_{seed}.map", W, H, [("A", me), ("B", [(1, 1), (2, 1), (2, 2)])],
                  spawn=spawn)
    return dict(map=m, rounds=60, setup=None, opp="coiler", metric=lambda s, a: _grown(s, 3, 10))


def s_scavenge(seed, rng):
    W = H = 16
    me = line(6, 8, 3)
    # a dead dragon's drop: a pearl on every second segment of a zig-zag body
    corpse = [(9, 6), (9, 8), (9, 10), (11, 6), (11, 8), (11, 10), (13, 8)]
    decoys = [(1, 13), (2, 14)]
    m = write_map(f"{TMP}/scav_{seed}.map", W, H, [("A", me), ("B", [(14, 1), (15, 1), (15, 2)])])
    setup = lambda s: s.pearls.update(corpse + decoys)
    return dict(map=m, rounds=20, setup=setup, opp="coiler",
                metric=lambda s, a: _eaten_from(s, corpse, 5))


def s_explore(seed, rng):
    W = H = 32
    kelp = []
    for x in (10, 21):                           # three wide rooms joined by doors
        kelp += [(x, y, "W") for y in range(H) if y % 8 not in (3, 4)]
    me = line(4, 16, 3)
    m = write_map(f"{TMP}/explore_{seed}.map", W, H, [("A", me), ("B", [(28, 2), (29, 2), (29, 3)])],
                  kelp=kelp)
    return dict(map=m, rounds=100, setup=None, opp="coiler", track_seen=True,
                metric=lambda s, a: (len(a["seen"]) / (W * H) >= 0.45 and _alive(s),
                                     len(a["seen"]) / (W * H)))


def s_portal(seed, rng):
    W, H = 24, 12
    kelp = [(12, y, "W") for y in range(H)] + [(0, y, "W") for y in range(H)]
    me = line(3, 6 + rng.randint(-2, 2), 3, dx=-1)
    portals = [(6, 6, "W", 7), (18, 6, "W", 7)]
    m = write_map(f"{TMP}/portal_{seed}.map", W, H, [("A", me), ("B", [(20, 1), (21, 1), (21, 2)])],
                  kelp=kelp, portals=portals)
    return dict(map=m, rounds=30, setup=None, opp="coiler",
                stop=lambda s: _heads(s, "A") and all(h[0] >= 12 for h in _heads(s, "A")),
                metric=lambda s, a: (any(h[0] >= 12 for h in _heads(s, "A")), s.round))


def s_hunt(seed, rng):
    W = H = 13
    me = line(9, 6, 10, dx=-1)[:7] + [(3, 7), (3, 8), (4, 8)]
    ex, ey = 9 + rng.randint(-1, 1), 10
    enemy = [(ex, ey), (ex + 1, ey), (ex + 2, ey)]
    m = write_map(f"{TMP}/hunt_{seed}.map", W, H, [("A", me), ("B", enemy)], kelp=border(W, H))
    return dict(map=m, rounds=80, setup=None, opp="mybot", stop=lambda s: not _heads(s, "B"),
                metric=lambda s, a: (not _heads(s, "B") and _alive(s), s.round))


def s_pincer(seed, rng):
    W = H = 15
    # coiled, so the enemy by our tail is also inside our head's 7x7 window
    me = [(8, 7), (7, 7), (6, 7), (5, 7), (5, 8), (6, 8), (7, 8), (8, 8), (9, 8), (9, 9),
          (8, 9), (7, 9)]
    o = rng.randint(0, 1)
    enemy = [(6 - o, 10), (5 - o, 10), (4 - o, 10)]
    m = write_map(f"{TMP}/pincer_{seed}.map", W, H, [("A", me), ("B", enemy)], kelp=border(W, H))
    return dict(map=m, rounds=80, setup=None, opp="mybot", stop=lambda s: not _heads(s, "B"),
                metric=lambda s, a: (not _heads(s, "B") and _alive(s), s.round))


def s_ram(seed, rng):
    W = H = 11
    me = line(4, 5, 3, dx=-1)
    enemy = [(6, 5)] + line(7, 5, 3, dx=1) + [(9, 6), (9, 7), (8, 7), (7, 7), (6, 7), (5, 7), (4, 7), (3, 7)]
    m = write_map(f"{TMP}/ram_{seed}.map", W, H, [("B", enemy), ("A", me)], kelp=border(W, H))
    return dict(map=m, rounds=6, setup=None, opp="chaser", stop=lambda s: not _heads(s, "B"),
                metric=lambda s, a: (not _heads(s, "B"), s.round))


def s_escape(seed, rng):
    W, H = 17, 13
    oy = rng.randint(-2, 2)
    me = line(3, 6 + oy, 3)
    a1 = [(13, 2), (14, 2), (15, 2)]
    a2 = [(13, 10), (14, 10), (15, 10)]
    m = write_map(f"{TMP}/escape_{seed}.map", W, H, [("B", a1), ("B", a2), ("A", me)],
                  kelp=border(W, H))
    return dict(map=m, rounds=150, setup=None, opp="chaser",
                metric=lambda s, a: (_alive(s), s.round))


def s_defensive_split(seed, rng):
    W = H = 16
    kelp = border(W, H)
    # a sealed 4x3 room (x 6..9, y 6..8) holding a length-10 coil with two free tiles
    kelp += [(x, 6, "N") for x in range(6, 10)] + [(x, 9, "N") for x in range(6, 10)]
    kelp += [(6, y, "W") for y in range(6, 9)] + [(10, y, "W") for y in range(6, 9)]
    me = [(8, 6), (9, 6), (9, 7), (8, 7), (7, 7), (6, 7), (6, 8), (7, 8), (8, 8), (9, 8)]
    ey = 6 + rng.randint(0, 1)                    # a neighbour outside: Instinct's danger gate
    enemy = [(13, ey), (14, ey), (14, ey + 1)]
    m = write_map(f"{TMP}/defsplit_{seed}.map", W, H, [("B", enemy), ("A", me)], kelp=kelp)
    return dict(map=m, rounds=40, setup=None, opp="coiler",
                metric=lambda s, a: (_alive(s), s.round))


def s_econ(seed, rng):
    W = H = 20
    spawn = [((x, y), (6, 14)) for x in range(W) for y in range(H) if (x + y) % 3 == 0]
    me = line(10, 10, 10, dx=-1)
    m = write_map(f"{TMP}/econ_{seed}.map", W, H, [("A", me), ("B", [(1, 18), (2, 18), (2, 19)])],
                  spawn=spawn)
    return dict(map=m, rounds=150, setup=None, opp="coiler",
                metric=lambda s, a: (_team_len(s, "A") >= 45, _team_len(s, "A")))


def s_stall(seed, rng):
    W = H = 16
    spawn = [((x, y), (6, 14)) for x in range(W) for y in range(H) if (x * 7 + y) % 5 == 0]
    me = line(10, 8, 14, dx=-1)[:9] + [(2, 9), (2, 10), (3, 10), (4, 10), (5, 10)]
    e1 = line(8, 3 + rng.randint(0, 1), 6)
    e2 = line(10, 13, 6)
    m = write_map(f"{TMP}/stall_{seed}.map", W, H, [("B", e1), ("B", e2), ("A", me)], spawn=spawn)
    return dict(map=m, rounds=500, start_round=420, setup=None, opp="mybot",
                metric=lambda s, a: (any(d.alive and d.length >= 12 for d in s.dragons.values()
                                         if d.team == "A"), s.round))


SCENARIOS = {
    "FORAGE": s_forage, "CAMP_CLUSTER": s_camp, "SCAVENGE": s_scavenge, "EXPLORE": s_explore,
    "PORTAL_TRAVEL": s_portal, "HUNT": s_hunt, "SPLIT_AND_PINCER": s_pincer, "RAM_TRADE": s_ram,
    "ESCAPE": s_escape, "DEFENSIVE_SPLIT": s_defensive_split, "ECON_SPLIT": s_econ, "STALL": s_stall,
}


# ============================================================== metrics ==
def _alive(s, team="A"):
    return any(d.alive for d in s.dragons.values() if d.team == team)


def _heads(s, team):
    return [d.head for d in s.dragons.values() if d.alive and d.team == team]


def _team_len(s, team):
    return sum(d.length for d in s.dragons.values() if d.alive and d.team == team)


def _grown(s, start, need):
    L = max((d.length for d in s.dragons.values() if d.alive and d.team == "A"), default=0)
    return L - start >= need, L - start


def _eaten_from(s, tiles, need):
    left = sum(1 for t in tiles if t in s.pearls)
    return (len(tiles) - left >= need and _alive(s)), len(tiles) - left


# ================================================================ runner ==
class Forced:
    """Rank the option under test first whenever it is available."""
    name = "forced"

    def __init__(self, idx, fallback):
        self.idx, self.fallback = idx, fallback

    def rank(self, feats, mask):
        r = self.fallback.rank(feats, mask)
        if mask[self.idx]:
            return [self.idx] + [i for i in r if i != self.idx]
        return r


def run(name, seed, mode="forced", sets=(), weights=None):
    """-> (success, value, picks of the tested option)"""
    rng = random.Random(seed)
    sc = SCENARIOS[name](seed, rng)
    me = botenv.BotSpec.load("hrlbot")
    for k, v in sets:
        setattr(me.config, k, v)
    mgr = me.mods["manager"]
    idx = me.mods["options"].IDX[name]
    if mode == "forced":
        make_mgr = lambda: Forced(idx, mgr.ScriptedManager())
    elif mode == "learned":
        make_mgr = lambda: mgr.LearnedManager(weights) if weights else mgr.make("learned")
    else:
        make_mgr = lambda: mgr.ScriptedManager()
    me.brain_factory = lambda sp, s, d: sp.main.Brain(s.W, s.H, make_mgr())
    opp = {"mybot": botenv.BotSpec.load("mybot"),
           "chaser": botenv.Scripted(lambda s, d: Chaser()),
           "coiler": botenv.Scripted(lambda s, d: Coiler())}[sc["opp"]]
    obs = {"seen": set()}
    stop = sc.get("stop")
    if sc.get("track_seen"):
        def stop(s, inner=stop):
            for d in s.dragons.values():
                if d.alive and d.team == "A":
                    obs["seen"].update(s.vision_tiles(d))
            return inner(s) if inner else False
    start = sc.get("start_round", 0)
    r = botenv.play_game(sc["map"], seed, me, opp, max_rounds=start + sc["rounds"] if start else sc["rounds"],
                         record=("A",), setup=sc["setup"], stop=stop, start_round=start)
    ok, value = sc["metric"](r["sim"], obs)
    picks = sum(1 for lg in r["logs"].values() for d in lg.decisions if d["option"] == idx)
    return bool(ok), value, picks


def _job(args):
    return args, run(*args)


def sweep(names, seeds, modes=("forced", "scripted"), sets=(), workers=None, weights=None):
    jobs = [(n, s, m, tuple(sets), weights) for n in names for m in modes for s in range(seeds)]
    out = {}
    with ProcessPoolExecutor(max_workers=workers or max(1, os.cpu_count() - 2)) as ex:
        for (n, s, m, _sets, _w), res in ex.map(_job, jobs):
            out.setdefault((n, m), []).append(res)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--seeds", type=int, default=8)
    args = ap.parse_args()
    names = args.names or list(SCENARIOS)
    res = sweep(names, args.seeds)
    print(f"{'option':18s} {'forced: success':>16s} {'mean':>7s} {'picks':>6s}   "
          f"{'scripted: success':>17s} {'mean':>7s}")
    for n in names:
        f = res[(n, "forced")]
        b = res[(n, "scripted")]
        fs = sum(x[0] for x in f)
        bs = sum(x[0] for x in b)
        fm = sum(float(x[1]) for x in f) / len(f)
        bm = sum(float(x[1]) for x in b) / len(b)
        fp = sum(x[2] for x in f) / len(f)
        print(f"{n:18s} {fs:>9d}/{len(f):<6d} {fm:7.2f} {fp:6.1f}   {bs:>10d}/{len(b):<6d} {bm:7.2f}",
              flush=True)


if __name__ == "__main__":
    main()
