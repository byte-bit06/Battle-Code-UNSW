"""Instinct_Engine under scripted attack (instinct_engine.md section 7).

The attackers CHEAT: they read the whole board, not a 7x7 window, and they are
deterministic. That makes them harder than a real opponent and repeatable,
which is what we want from an acceptance bar.

    python tools/instinct_arena.py --ladder
    python tools/instinct_arena.py --scenario A2 --rounds 200 --show

Ladder:
    A0 greedy chaser   one dragon, shortest path to our head
    A1 pincer          two dragons closing from opposite sides
    A2 sealer          sits on the articulation point of our escape region
    A3 kamikaze        a length-2 dragon trading itself for our biggest
    A4 chamber         A2, sealing a chamber that holds pearls (forced growth)
    A5 ghost           approaches only from outside our vision

Every scenario runs twice, with the attackers holding LOWER ids than us and
then HIGHER, because tempo is half the engine.

The defender runs the SHIPPED path (danger gate + per-level budgets), not the
ungated ladder: measuring the more capable path scored an engine we do not
submit and inverted the headline result. Always run `instinct-off` alongside
anything else - see instinct_tests/MEASUREMENT.md.

Reported per run: rounds survived, death cause, and lead time - how many
rounds before contact our corridor count first dropped below 2. Survival is
binary and noisy; lead time says whether we saw it coming.
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "arena"))
sys.path.insert(0, os.path.join(ROOT, "mybot"))

import config   # noqa: E402  (mybot/config.py)

config.INSTINCT_RAISE = True   # never measure a silently-degraded engine again
import mapfile   # noqa: E402
import sim as simmod   # noqa: E402
from geometry import Geo, N, E, S, W, EDGE_KELP   # noqa: E402
from instinct import control, corridors, ladder, space, tempo   # noqa: E402
from instinct.state import Dragon, State, TIER_A   # noqa: E402

DIRS = (N, E, S, W)
DXY = ((0, -1), (1, 0), (0, 1), (-1, 0))
VISION = 3


# --------------------------------------------------------------- scenarios --
def write_map(path, W, H, dragons, kelp=(), pearl_tiles=()):
    """dragons: [(team, [(x, y), ...]) ...] in ID ORDER (line order = id)."""
    lines = [f"MAP {W} {H}", "SYMMETRY xy"]
    for (x, y) in pearl_tiles:
        lines.append(f"TILE {x} {y} 8 12")
    S_ = 2 * (W + 1)
    for (x, y, side) in kelp:                      # side 'N' or 'W' of tile (x, y)
        idx = y * S_ + (x if side == "N" else W + 1 + x)
        lines.append(f"EDGE {idx} 1 -1")
    for team, cells in dragons:
        flat = " ".join(f"{x} {y}" for x, y in cells)
        lines.append(f"DRAGON {0 if team == 'A' else 1} {len(cells)} {flat}")
    open(path, "w").write("\n".join(lines) + "\n")
    return path


# ------------------------------------------------------------- the defender --
class Defender:
    """Our dragon: Instinct only, and only what a 7x7 window shows."""
    kind = "agent"

    def __init__(self, sim):
        self.geo = Geo(sim.W, sim.H)
        self.seen = [-1] * (sim.W * sim.H)
        self.known_len = {}
        self.plan = None
        self.log = []              # per round: (round, corridor_count, ram_exposure)
        self.no_action = 0

    def tile(self, xy):
        return xy[1] * self.geo.W + xy[0]

    def state(self, sim, d):
        geo = self.geo
        vis = set(sim.vision_tiles(d))
        for xy in vis:                                   # learn kelp we can see
            self.seen[self.tile(xy)] = sim.round
            for di, (dx, dy) in enumerate(DXY):
                if sim.edge(xy[0], xy[1], di)[0] == mapfile.KELP:
                    geo.learn_edge(self.tile(xy), DIRS[di], EDGE_KELP)
        enemies, allies = [], []
        by_dragon = {}
        for xy in vis:
            o = sim.occ.get(xy)
            if o is not None and o is not d:
                by_dragon.setdefault(o.id, []).append(xy)
        for did, cells in by_dragon.items():
            other = sim.dragons[did]
            head = other.head if other.head in vis else cells[0]
            segs = [self.tile(c) for c in cells]
            if head in vis:                              # keep the head first
                segs.remove(self.tile(head))
                segs.insert(0, self.tile(head))
            est = max(len(segs), self.known_len.get(did, 0), 2)
            self.known_len[did] = est
            drag = Dragon(did, self.tile(head), segs, est, other.team == d.team,
                          acts_before=did < d.id)
            (allies if drag.teammate else enemies).append(drag)
        body = [self.tile(c) for c in d.cells]
        pearls = [self.tile(p) for p in sim.pearls if p in vis]
        return State(geo, d.id, body[0], body, d.length, enemies, allies, pearls,
                     self.seen, sim.round)

    def act(self, sim, d):
        st = self.state(sim, d)
        if not config.USE_INSTINCT:
            # control group: no Instinct at all. Any legal move, preferring the
            # one with the most open neighbours (roughly the old safety.py).
            best, best_v = None, None
            for dd in (0, 1, 2, 3):
                if space.walk(st, [dd]) is None:
                    continue
                n = st.geo.step(st.head, dd)
                v = sum(1 for m in st.geo.neighbours(n)
                        if m >= 0 and m not in st.body and m not in st.blocked())
                if best_v is None or v > best_v:
                    best, best_v = dd, v
            self.log.append((sim.round, 3, 0))
            return ("move", [best if best is not None else d.dirs[0]]), None
        # the SHIPPED path: the danger gate and the per-level budgets the bot
        # actually runs (main.py). ladder.decide() is the ungated version and
        # measuring it would score an engine we do not submit.
        if not ladder.danger(st):
            action, _info = ("move", [ladder.l0_reflex(st)]), {"level": "calm"}
            self.plan = None
            if action[1][0] is None:
                action = None
        else:
            action, self.plan, _info = ladder.decide_budgeted(st, self.plan)
        # log the signal the engine actually steers on: corridor count to the
        # joint-envelope frontier, not to a distance ring
        ctrl = control.build_control(st, horizon=6)
        self.log.append((sim.round,
                         corridors.corridor_count(st, open_set=ctrl.free_frontier(6)),
                         tempo.ram_exposure(st)))
        if action is None:
            self.no_action += 1
            return ("move", [d.dirs[0]]), None            # doomed; still submit something
        if action[0] == "split":
            return ("split", action[1]), None
        return ("move", action[1]), None

    target = None
    debug = ""


# ------------------------------------------------------------- attackers --
def bfs(sim, start, blocked=()):
    """Full-board distances (the attackers cheat)."""
    dist = {start: 0}
    queue = [start]
    qi = 0
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        for di in range(4):
            n = sim.step(cur, di)
            if n == simmod.KELP_HIT or n in dist or n in blocked:
                continue
            dist[n] = dist[cur] + 1
            queue.append(n)
    return dist


def step_towards(sim, d, goal, avoid_heads=True):
    """One legal step that most reduces true distance to `goal`."""
    blocked = {c for x in sim.dragons.values() if x.alive for c in x.cells}
    blocked.discard(goal)
    dist = bfs(sim, goal, blocked - {d.head})
    best, best_v = None, None
    for di in range(4):
        n = sim.step(d.head, di)
        if n == simmod.KELP_HIT:
            continue
        o = sim.occ.get(n)
        if o is not None and n != goal:
            continue
        if avoid_heads and o is not None and o.team == d.team:
            continue
        v = dist.get(n, 10 ** 6)
        if best_v is None or v < best_v:
            best, best_v = di, v
    return ("move", [best if best is not None else d.dirs[0]]), None


class Attacker:
    kind = "script"
    target = None
    debug = ""

    def __init__(self, sim, role=0):
        self.role = role

    def prey(self, sim, d):
        alive = [x for x in sim.dragons.values() if x.alive and x.team != d.team]
        return max(alive, key=lambda x: x.length) if alive else None


class A0Greedy(Attacker):
    """Shortest path to our head. The baseline."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        return step_towards(sim, d, p.head) if p else (("move", [d.dirs[0]]), None)


class A1Pincer(Attacker):
    """Two dragons approaching from opposite sides, by true distance."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        if p is None:
            return ("move", [d.dirs[0]]), None
        hx, hy = p.head
        off = 3 if self.role == 0 else -3
        goal = ((hx + off) % sim.W, hy) if self.role % 2 == 0 else (hx, (hy + off) % sim.H)
        if sim.occ.get(goal) is not None or abs(off) <= 1:
            goal = p.head
        d_now = bfs(sim, p.head).get(d.head, 99)
        return step_towards(sim, d, p.head if d_now <= 2 else goal)


class A2Sealer(Attacker):
    """Sits on the articulation point of our escape region."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        if p is None:
            return ("move", [d.dirs[0]]), None
        cut = cut_tile_of(sim, p)
        return step_towards(sim, d, cut or p.head)


class A3Kamikaze(Attacker):
    """A length-2 dragon running at our largest dragon for the trade."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        return step_towards(sim, d, p.head) if p else (("move", [d.dirs[0]]), None)


class A4Chamber(A2Sealer):
    """A2, but it prefers to seal a chamber that holds pearls (forced growth)."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        if p is None:
            return ("move", [d.dirs[0]]), None
        cut = cut_tile_of(sim, p, prefer_pearls=True)
        return step_towards(sim, d, cut or p.head)


class A5Ghost(Attacker):
    """Approaches only from outside the 7x7 window, then charges."""
    def act(self, sim, d):
        p = self.prey(sim, d)
        if p is None:
            return ("move", [d.dirs[0]]), None
        hx, hy = p.head
        dx = min(abs(d.head[0] - hx), sim.W - abs(d.head[0] - hx))
        dy = min(abs(d.head[1] - hy), sim.H - abs(d.head[1] - hy))
        cheb = max(dx, dy)
        st = full_state(sim, p)
        boxed = corridors.corridor_count(st) <= 1
        if boxed or cheb > VISION + 1:
            return step_towards(sim, d, p.head)           # charge, or close in unseen
        ring = [((hx + ox) % sim.W, (hy + oy) % sim.H)
                for ox, oy in ((VISION + 1, 0), (-(VISION + 1), 0), (0, VISION + 1), (0, -(VISION + 1)))]
        ring.sort(key=lambda g: bfs(sim, g).get(d.head, 99))
        return step_towards(sim, d, ring[0])


LADDER = {"A0": (A0Greedy, 1), "A1": (A1Pincer, 2), "A2": (A2Sealer, 2),
          "A3": (A3Kamikaze, 1), "A4": (A4Chamber, 2), "A5": (A5Ghost, 1)}


# ------------------------------------------------------ full-board helpers --
def full_state(sim, prey):
    """The prey's position as an Instinct State, with the WHOLE board known
    (attackers cheat; also used to score how boxed in the defender is)."""
    geo = Geo(sim.W, sim.H)
    for x in range(sim.W):
        for y in range(sim.H):
            for di in range(4):
                if sim.edge(x, y, di)[0] == mapfile.KELP:
                    geo.learn_edge(y * sim.W + x, DIRS[di], EDGE_KELP)
    t = lambda xy: xy[1] * sim.W + xy[0]
    enemies = []
    for o in sim.dragons.values():
        if o.alive and o is not prey:
            enemies.append(Dragon(o.id, t(o.head), [t(c) for c in o.cells], o.length,
                                  o.team == prey.team, acts_before=o.id < prey.id))
    body = [t(c) for c in prey.cells]
    return State(geo, prey.id, body[0], body, prey.length, enemies, [],
                 [t(p) for p in sim.pearls], [0] * (sim.W * sim.H), sim.round)


def cut_tile_of(sim, prey, prefer_pearls=False):
    st = full_state(sim, prey)
    cut = corridors.cut_tile(st)
    if cut is None and prefer_pearls:
        region = corridors.region(st)
        pearly = [p for p in st.pearls if p in region]
        if pearly:
            return sim.dragons[prey.id].head
    return (cut[0], cut[1]) if cut else None


# ------------------------------------------------------------------ runner --
def chamber_walls(W, H):
    """A chamber-heavy board: six rooms joined by single-tile doorways.

    The open ladder is where corridor analysis should NOT pay - there is always
    another way round. This is the board it exists for (MEASUREMENT.md).
    """
    kelp = []
    doors_v = {3, 9}                      # doorways in the vertical walls
    doors_h = {2, 8, 14}                  # doorways in the horizontal wall
    for x in (5, 11):
        for y in range(H):
            if y not in doors_v:
                kelp.append((x, y, "W"))
    for x in range(W):
        if x not in doors_h:
            kelp.append((x, 6, "N"))
    return kelp


def run(scenario, attackers_first, rounds=300, W=17, H=13, show=False, seed=0,
        board="open"):
    cls, count = LADDER[scenario]
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"instinct_{scenario}_{seed}.map")
    rng = random.Random(seed)
    # seed 0 keeps the fixed layout; later seeds jitter both sides' starts, so a
    # score is not one lucky geometry repeated
    ox, oy = (0, 0) if seed == 0 else (rng.randint(-1, 3), rng.randint(-4, 4))
    ax, ay = (0, 0) if seed == 0 else (rng.randint(-2, 1), rng.randint(-4, 4))
    me = [(3 + ox, 6 + oy), (2 + ox, 6 + oy), (1 + ox, 6 + oy)]
    spots = [[(13 + ax, 6 + ay), (14 + ax, 6 + ay)],
             [(13 + ax, 2 + ay), (14 + ax, 2 + ay)],
             [(13 + ax, 10 + ay), (14 + ax, 10 + ay)]][:count]
    if scenario == "A3":
        spots = [[(13 + ax, 6 + ay), (14 + ax, 6 + ay)]]  # length 2: the trade
        me = [(3 + ox, 6 + oy), (2 + ox, 6 + oy), (1 + ox, 6 + oy),
              (1 + ox, 5 + oy), (1 + ox, 4 + oy), (1 + ox, 3 + oy)]
    clamp = lambda c: (min(max(c[0], 1), W - 2), min(max(c[1], 1), H - 2))
    me = [clamp(c) for c in me]
    spots = [[clamp(c) for c in s] for s in spots]
    if len({c for c in me} | {c for s in spots for c in s}) < len(me) + sum(len(s) for s in spots):
        return None                                       # jitter overlapped: skip
    kelp = [(x, 0, "N") for x in range(W)] + [(x, H - 1, "N") for x in range(W)]
    kelp += [(0, y, "W") for y in range(H)] + [(W - 1, y, "W") for y in range(H)]
    if board == "chamber":
        kelp += chamber_walls(W, H)
        me = [(2, 3), (1, 3), (1, 2)]                  # inside the top-left room
        spots = [[(8, 3), (9, 3)], [(14, 3), (15, 3)], [(8, 9), (9, 9)]][:len(spots)]
    pearls = [(5, 5), (6, 5), (5, 7), (6, 7)] if scenario == "A4" else []
    pearls = [p for p in pearls if p not in me and all(p not in s for s in spots)]
    mine = ("A", me)
    theirs = [("B", s) for s in spots]
    order = theirs + [mine] if attackers_first else [mine] + theirs
    write_map(tmp, W, H, order, kelp, pearls)

    s = simmod.Sim(tmp, seed=seed)
    defender = None
    roles = 0
    for did, d in sorted(s.dragons.items()):
        if d.team == "A":
            d.controller = defender = Defender(s)
        else:
            d.controller = cls(s, roles)
            roles += 1
    me_id = next(i for i, d in s.dragons.items() if d.team == "A")

    contact = None
    while not s.over and s.round < rounds:
        s.start_round()
        for d in list(s.turn_order()):
            if not d.alive:
                continue
            action, _ = d.controller.act(s, d)
            res = s.apply(d, action)
            if hasattr(res, "cells"):
                res.controller = Defender(s) if res.team == "A" else cls(s, roles)
        mine_alive = [d for d in s.dragons.values() if d.alive and d.team == "A"]
        if contact is None and mine_alive:
            for d in s.dragons.values():
                if d.alive and d.team == "B":
                    for m in mine_alive:
                        dx = min(abs(d.head[0] - m.head[0]), s.W - abs(d.head[0] - m.head[0]))
                        dy = min(abs(d.head[1] - m.head[1]), s.H - abs(d.head[1] - m.head[1]))
                        if max(dx, dy) <= 1:
                            contact = s.round
        s.end_round()
        if not mine_alive:
            break

    dead = [d for d in s.dragons.values() if d.team == "A" and not d.alive]
    cause = classify_death(dead[0].death_cause) if dead else "survived"
    # lead time: how early the corridor count warned us, counting only warnings
    # BEFORE contact (a warning after contact told us nothing useful)
    limit = contact if contact is not None else 10 ** 6
    warned = next((r for r, c, _ in defender.log if c < 2 and r <= limit), None)
    lead = (contact - warned) if (contact is not None and warned is not None) else None
    return dict(scenario=scenario, order="attackers first" if attackers_first else "we move first",
                rounds=s.round, cause=cause, contact=contact, warned=warned, lead=lead,
                no_action=defender.no_action,
                alive=len([d for d in s.dragons.values() if d.team == "A" and d.alive]))


def classify_death(cause):
    if cause is None:
        return "survived"
    if "kelp" in cause:
        return "wall"
    if "itself" in cause:
        return "self"
    if "head-to-head" in cause:
        return "head-to-head"
    if "dragon" in cause:
        return "other body"
    return cause


# ------------------------------------------------------------- ablation --
# One key term at a time. With nine terms some are dead weight, and escape_depth
# is the first suspect now that free_volume exists.
# "minimal" is the three-term engine: safe + options + free_volume, nothing else.
# If it matches full, the envelopes and corridors are not worth their CPU here.
# free_volume is deleted, so "full" IS what used to be measured as no-volume.
# "bare" = safety + options only: both ram and corridor now ablate POSITIVE, so
# the question is whether either earns its place at all.
# ram and corridor are gone from the key; "no-ram" now cuts the two paths where
# ram survives (l0_reflex and the tight hint).
ABLATIONS = ["full", "no-options", "no-ram", "instinct-off"]
ABLATE_TERMS = {}


def sweep(names, seeds, rounds, board="open"):
    """-> (survived, decided, causes) over scenario x id order x seed."""
    survived = total = 0
    causes = {}
    for name in names:
        for first in (True, False):
            for seed in range(seeds):
                r = run(name, first, rounds, seed=seed, board=board)
                if r is None:
                    continue
                total += 1
                survived += r["cause"] == "survived"
                causes[r["cause"]] = causes.get(r["cause"], 0) + 1
    return survived, total, causes


def main():
    import config
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=sorted(LADDER))
    ap.add_argument("--ladder", action="store_true")
    ap.add_argument("--ablate", action="store_true", help="turn off one key term at a time")
    ap.add_argument("--seeds", type=int, default=1, help="randomised starts per scenario")
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--board", choices=("open", "chamber"), default="open",
                    help="chamber: six rooms joined by single-tile doorways")
    args = ap.parse_args()
    names = sorted(LADDER) if args.ladder or args.ablate or not args.scenario else [args.scenario]

    if args.ablate:
        print(f"ablation on the {args.board} board: {len(names)} scenarios "
              f"x 2 id orders x {args.seeds} seeds")
        for label in ABLATIONS:
            config.INSTINCT_ABLATE = ABLATE_TERMS.get(
                label, "" if label in ("full", "instinct-off") else label[3:])
            config.USE_INSTINCT = label != "instinct-off"
            s, n, causes = sweep(names, args.seeds, args.rounds, args.board)
            print(f"  {label:13s} survived {s:3d}/{n:3d}  {causes}", flush=True)
        config.INSTINCT_ABLATE, config.USE_INSTINCT = "", True
        return

    causes = {}
    print(f"{'scenario':10s} {'ids':16s} {'seed':>4s} {'rounds':>6s} {'outcome':>12s} "
          f"{'contact':>7s} {'warned':>6s} {'lead':>5s}")
    for name in names:
        for first in (True, False):
            for seed in range(args.seeds):
                r = run(name, first, args.rounds, seed=seed, board=args.board)
                if r is None:
                    continue
                causes[r["cause"]] = causes.get(r["cause"], 0) + 1
                print(f"{name:10s} {r['order']:16s} {seed:4d} {r['rounds']:6d} "
                      f"{r['cause']:>12s} {str(r['contact']):>7s} {str(r['warned']):>6s} "
                      f"{str(r['lead']):>5s}"
                      + ("  NO-ACTION x%d" % r["no_action"] if r["no_action"] else ""), flush=True)
    print(chr(10) + "deaths by cause:", causes)


if __name__ == "__main__":
    main()
