"""Phase 4: train the options that need it, one at a time, then freeze them.

The weak options are rule-based policies with a handful of parameters, so
"training" them is policy search: the cross-entropy method (CEM) over those
parameters, scored on FULL games on the real maps (the scenario boards turned
out to be too open for HUNT to ever kill - see HRL_CHECKLIST.md). While tuning,
the manager is forced to run the option whenever its initiation set holds, so
each score measures that option, on its own reward:

  HUNT / SPLIT_AND_PINCER  kills while the option ran - our deaths while it ran,
                           plus the game result
  ECON_SPLIT               team length at the end, plus the game result
  CAMP_CLUSTER             length gained per turn while camping, plus the result

Common random numbers: every candidate plays the same maps, seeds and sides.

    python hrl_train/tune_options.py HUNT --iters 4 --pop 10
"""
import argparse
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# name -> (kind, low, high); kind "f" float, "i" int
SPACES = {
    # only HOW an option plays is tuned here; WHEN to use it is the manager's job
    "HUNT": {"HUNT_W_SQUEEZE": ("f", 0, 3), "HUNT_W_OWN": ("f", 0, 2),
             "HUNT_W_CLOSE": ("f", 0, 3), "HUNT_AHEAD": ("i", 0, 4)},
    "ECON_SPLIT": {"ECON_CHILD": ("i", 2, 6)},
    "CAMP_CLUSTER": {"CAMP_WINDOW": ("i", 4, 16), "CAMP_RADIUS": ("i", 4, 10)},
}

_DEFAULTS = {}


def _active_rounds(lg, idx):
    """Rounds (inclusive start, exclusive end) during which option idx ran."""
    out = []
    ds = lg.decisions
    for i, d in enumerate(ds):
        if d["option"] != idx:
            continue
        end = ds[i + 1]["round"] if i + 1 < len(ds) else (
            lg.death_round + 1 if lg.death_round is not None else 10 ** 6)
        out.append((d["round"], end))
    return out


def score_game(name, idx, r, side):
    win = 1.0 if r["winner"] == side else (0.5 if r["winner"] is None else 0.0)
    s = r["sim"]
    logs = [lg for lg in r["logs"].values() if lg.team == side]
    if name in ("HUNT", "SPLIT_AND_PINCER"):
        kills = deaths = 0
        for lg in logs:
            spans = _active_rounds(lg, idx)
            if name == "SPLIT_AND_PINCER":        # credit the fight that follows the split
                spans = [(a, a + 20) for a, _b in spans]
            inside = lambda rd: any(a <= rd < b for a, b in spans)
            kills += sum(1 for rd, _l in lg.kills if inside(rd))
            if lg.death_round is not None and inside(lg.death_round):
                deaths += 1
        return 2 * win + 0.5 * (kills - deaths), {"kills": kills, "deaths": deaths, "win": win}
    if name == "ECON_SPLIT":
        total = sum(d.length for d in s.dragons.values() if d.alive and d.team == side)
        return 2 * win + total / 50.0, {"team_len": total, "win": win}
    if name == "CAMP_CLUSTER":
        gain = turns = 0
        for lg in logs:
            ds = lg.decisions
            for i, d in enumerate(ds):
                if d["option"] == idx and i + 1 < len(ds):
                    gain += ds[i + 1]["length"] - d["length"]
                    turns += ds[i + 1]["round"] - d["round"]
        return 2 * win + 5 * gain / max(1, turns), {"gain_per_turn": gain / max(1, turns), "win": win}
    raise KeyError(name)


def _job(job):
    import botenv
    import scenarios
    name, params, map_path, seed, side = job
    me = botenv.BotSpec.load("hrlbot")
    cfg = me.config
    if not _DEFAULTS:
        for space in SPACES.values():
            for k in space:
                _DEFAULTS[k] = getattr(cfg, k)
    for k, v in _DEFAULTS.items():
        setattr(cfg, k, v)
    for k, v in params.items():
        setattr(cfg, k, v)
    mgr, O = me.mods["manager"], me.mods["options"]
    idx = O.IDX[name]
    me.brain_factory = lambda sp, s, d: sp.main.Brain(s.W, s.H, scenarios.Forced(idx, mgr.ScriptedManager()))
    other = botenv.BotSpec.load("mybot")
    a, b = (me, other) if side == "A" else (other, me)
    r = botenv.play_game(map_path, seed, a, b, record=(side,))
    return score_game(name, idx, r, side)


def sample(space, mean, std, rng):
    out = {}
    for k, (kind, lo, hi) in space.items():
        v = min(hi, max(lo, rng.gauss(mean[k], std[k])))
        out[k] = int(round(v)) if kind == "i" else round(v, 3)
    return out


def evaluate(pool, name, candidates, games):
    jobs = [(name, c, m, s, side) for c in candidates for (m, s, side) in games]
    res = list(pool.map(_job, jobs))
    n = len(games)
    out = []
    for i, c in enumerate(candidates):
        chunk = res[i * n:(i + 1) * n]
        info = {}
        for _s, d in chunk:
            for k, v in d.items():
                info[k] = info.get(k, 0) + v / n
        out.append((sum(x[0] for x in chunk) / n, c, info))
    return out


def tune(name, iters, pop, elite, seeds, workers, log):
    import glob
    space = SPACES[name]
    rng = random.Random(7)
    maps = sorted(glob.glob(os.path.join(ROOT, "maps", "*.map")))
    games = [(m, 2000 + s, side) for m in maps for s in range(seeds) for side in ("A", "B")]
    sys.path.insert(0, os.path.join(ROOT, "hrlbot"))
    import config as defaults_cfg                        # hrlbot/config.py
    sys.path.pop(0)
    base = {k: getattr(defaults_cfg, k) for k in space}
    mean = {k: float(v) for k, v in base.items()}
    std = {k: (hi - lo) / 4.0 for k, (_kind, lo, hi) in space.items()}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        base_res = evaluate(pool, name, [base], games)[0]
        log(f"{name} defaults {base}: score {base_res[0]:.3f} {fmt(base_res[2])}")
        best = base_res
        for it in range(iters):
            cands = [sample(space, mean, std, rng) for _ in range(pop)]
            res = sorted(evaluate(pool, name, cands, games), key=lambda x: -x[0])
            top = res[:elite]
            for k, (kind, lo, hi) in space.items():
                vals = [c[k] for _s, c, _i in top]
                mean[k] = sum(vals) / len(vals)
                var = sum((v - mean[k]) ** 2 for v in vals) / len(vals)
                std[k] = max(math.sqrt(var), (hi - lo) / 20.0)
            log(f"  iter {it + 1}: best {top[0][0]:.3f} {top[0][1]} {fmt(top[0][2])}")
            if top[0][0] > best[0]:
                best = top[0]
        # re-check the winner against the defaults on fresh seeds (no lucky picks)
        fresh = [(m, 3000 + s, side) for m in maps for s in range(seeds) for side in ("A", "B")]
        final = evaluate(pool, name, [base, best[1]], fresh)
        log(f"  fresh seeds: defaults {final[0][0]:.3f} {fmt(final[0][2])} | "
            f"tuned {final[1][0]:.3f} {fmt(final[1][2])}")
        keep = best[1] if final[1][0] > final[0][0] else base
        log(f"  KEEP {keep}")
        return keep


def fmt(info):
    return "{" + ", ".join(f"{k} {v:.2f}" for k, v in info.items()) + "}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--pop", type=int, default=10)
    ap.add_argument("--elite", type=int, default=3)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    out_path = os.path.join(HERE, "results", "tuning.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def log(msg):
        print(msg, flush=True)
        with open(out_path, "a") as f:
            f.write(msg + "\n")
    log(f"=== tune_options {time.strftime('%Y-%m-%d %H:%M')} iters={args.iters} pop={args.pop}")
    kept = {}
    for name in args.names or list(SPACES):
        kept[name] = tune(name, args.iters, args.pop, args.elite, args.seeds, args.workers, log)
    log("RESULT " + json.dumps(kept))


if __name__ == "__main__":
    main()
