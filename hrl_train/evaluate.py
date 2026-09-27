"""Evaluate one bot against another on the simulator, in parallel.

Every map x both team sides x N seeds. Reports wins/losses/draws, deaths per
side, and, for an HRL bot, option usage: how often the manager picked each
option, how long it ran, length gained per turn while it ran, and how often
the dragon died while it was running (Phase 7 of HRL_CHECKLIST.md).

    python hrl_train/evaluate.py hrlbot mybot --seeds 3
    python hrl_train/evaluate.py hrlbot mybot --manager scripted --maps arena default
    python hrl_train/evaluate.py hrlbot mybot --weights hrl_train/runs/x/weights.py
"""
import argparse
import collections
import glob
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def load_weights_module(path):
    """A manager_weights.py file, or a w_N.json snapshot from train_manager.py."""
    if path.endswith(".json"):
        import types
        return types.SimpleNamespace(**json.load(open(path)))
    import importlib.util
    spec = importlib.util.spec_from_file_location("manager_weights_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def configure(spec, manager_kind=None, weights=None, sets=()):
    """Point an HRL BotSpec at a manager (and optional weights file)."""
    for item in sets:
        k, v = item.split("=", 1)
        setattr(spec.config, k, eval(v))
    if "manager" not in spec.mods:
        return
    mgr_mod = spec.mods["manager"]
    if weights:
        w = load_weights_module(weights)
        spec.brain_factory = lambda sp, s, d: sp.main.Brain(s.W, s.H, mgr_mod.LearnedManager(w))
    elif manager_kind:
        spec.brain_factory = lambda sp, s, d: sp.main.Brain(s.W, s.H, mgr_mod.make(manager_kind))


def option_stats(logs, team, names):
    """Per option: [picks, turns, length gained, deaths while running]."""
    out = collections.defaultdict(lambda: [0, 0, 0, 0])
    for lg in logs.values():
        if lg.team != team or not lg.decisions:
            continue
        ds = lg.decisions
        for i, d in enumerate(ds):
            s = out[names[d["option"]]]
            s[0] += 1
            if i + 1 < len(ds):
                s[1] += ds[i + 1]["round"] - d["round"]
                s[2] += ds[i + 1]["length"] - d["length"]
            elif lg.death_round is not None:
                s[1] += lg.death_round - d["round"] + 1
                s[2] += lg.death_len - d["length"]
                s[3] += 1
    return dict(out)


def run_one(job):
    import botenv
    (map_path, seed, bot, other, side, manager_kind, weights, other_manager, sets) = job
    a_dir, b_dir = (bot, other) if side == "A" else (other, bot)
    me = botenv.BotSpec.load(bot)
    them = botenv.BotSpec.load(other)
    configure(me, manager_kind, weights, sets)
    if them is not me:
        configure(them, other_manager)
    specs = {"A": me if side == "A" else them, "B": them if side == "A" else me}
    t0 = time.time()
    r = botenv.play_game(map_path, seed, specs["A"], specs["B"], record=(side,))
    s = r["sim"]
    them_side = "B" if side == "A" else "A"
    names = me.mods["options"].NAMES if "options" in me.mods else []
    alive = lambda team: [d for d in s.dragons.values() if d.alive and d.team == team]
    return {
        "map": os.path.basename(map_path)[:-4], "seed": seed, "side": side,
        "winner": r["winner"], "result": r["result"], "rounds": r["rounds"],
        "outcome": "WIN" if r["winner"] == side else ("LOSS" if r["winner"] == them_side else "DRAW"),
        "deaths_ours": sum(1 for d in s.dragons.values() if d.team == side and not d.alive),
        "deaths_theirs": sum(1 for d in s.dragons.values() if d.team == them_side and not d.alive),
        "longest_ours": max((d.length for d in alive(side)), default=0),
        "longest_theirs": max((d.length for d in alive(them_side)), default=0),
        "options": option_stats(r["logs"], side, names) if names else {},
        "causes": collections.Counter(
            lg.death_cause.split(" ")[0] + (" " + lg.death_cause.split(" ")[1] if " " in lg.death_cause else "")
            for lg in r["logs"].values() if lg.team == side and lg.death_round is not None),
        "secs": time.time() - t0,
    }


def summarise(results, label=""):
    wins = sum(r["outcome"] == "WIN" for r in results)
    losses = sum(r["outcome"] == "LOSS" for r in results)
    draws = len(results) - wins - losses
    by_map = collections.defaultdict(lambda: [0, 0, 0])
    for r in results:
        by_map[r["map"]][("WIN", "LOSS", "DRAW").index(r["outcome"])] += 1
    lines = [f"{label}{wins} wins, {losses} losses, {draws} draws  "
             f"(win rate {wins / max(1, len(results)):.0%}, n={len(results)})"]
    for m, (w, l, d) in sorted(by_map.items()):
        lines.append(f"  {m:18s} W{w:3d} L{l:3d} D{d:3d}")
    opts = collections.defaultdict(lambda: [0, 0, 0, 0])
    causes = collections.Counter()
    for r in results:
        for k, v in r["options"].items():
            for i in range(4):
                opts[k][i] += v[i]
        causes.update(r["causes"])
    if opts:
        total = sum(v[0] for v in opts.values())
        lines.append(f"  {'option':18s} {'picked':>7s} {'share':>6s} {'avg turns':>9s} "
                     f"{'len/turn':>8s} {'deaths':>6s}")
        for k, (n, turns, gain, dead) in sorted(opts.items(), key=lambda x: -x[1][0]):
            lines.append(f"  {k:18s} {n:7d} {n / total:6.1%} {turns / max(1, n):9.2f} "
                         f"{gain / max(1, turns):8.3f} {dead:6d}")
    if causes:
        lines.append("  our deaths by cause: " + ", ".join(f"{k} {v}" for k, v in causes.most_common()))
    lines.append(f"  mean deaths/game ours {sum(r['deaths_ours'] for r in results) / max(1, len(results)):.1f}"
                 f" theirs {sum(r['deaths_theirs'] for r in results) / max(1, len(results)):.1f}")
    return "\n".join(lines)


def evaluate(bot, other, maps, seeds, manager_kind=None, weights=None, other_manager=None,
             sets=(), workers=None, seed0=1000):
    jobs = [(m, seed0 + s, bot, other, side, manager_kind, weights, other_manager, tuple(sets))
            for m in maps for s in range(seeds) for side in ("A", "B")]
    with ProcessPoolExecutor(max_workers=workers or max(1, os.cpu_count() - 2)) as ex:
        return list(ex.map(run_one, jobs))


def map_paths(names=None):
    if names:
        return [os.path.join(ROOT, "maps", n if n.endswith(".map") else n + ".map") for n in names]
    return sorted(glob.glob(os.path.join(ROOT, "maps", "*.map")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("other")
    ap.add_argument("--maps", nargs="*")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--manager", choices=("scripted", "learned"))
    ap.add_argument("--weights", help="a manager_weights.py file for the first bot")
    ap.add_argument("--other-manager", choices=("scripted", "learned"))
    ap.add_argument("--set", action="append", default=[], help="NAME=VALUE for the first bot's config")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--json", help="write raw results here")
    args = ap.parse_args()
    t0 = time.time()
    res = evaluate(args.bot, args.other, map_paths(args.maps), args.seeds, args.manager,
                   args.weights, args.other_manager, args.set, args.workers)
    print(summarise(res, f"{args.bot} vs {args.other}: "))
    print(f"  ({time.time() - t0:.0f}s)")
    if args.json:
        json.dump(res, open(args.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
