"""Scorecard: did each phase of IMPLEMENTATION_PLAN_vE.md do its job?

usage: python tools/check.py REPLAY_DIR [--baseline tools/baselines/vD_server.json] [--jobs 8]

REPLAY_DIR is either local games from harness.py (e.g. our bot vs aura_vD, then "them" IS vD
in the very same games) or server games from fetch_replays.py. Every metric is shown for us,
for the opponent in the same games, for vD's 104 server games (the baseline), and against the
plan's target, marked OK / CHECK / BAD. The block between the ==== lines at the end is the
part to paste back for review.
"""
import argparse
import collections
import glob
import json
import os
import pathlib
import re
import statistics as st
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report import _one  # noqa: E402

SELF = ("hit wall", "hit self", "hit other body")


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def side_metrics(games, who):
    """Per-side numbers. who = "us" or "them"."""
    m = {}
    n = len(games)
    sd = lambda g: g[who]
    m["pearls_r100"] = med([g["eaten_at"][100].get(sd(g), 0) for g in games])
    m["splits_r100"] = med([sum(s["team"] == sd(g) and s["round"] < 100 for s in g["splits"]) for g in games])
    m["cover"] = med([g["cover"][sd(g)] for g in games])
    m["spawn_cover"] = med([g["spawn_cover"][sd(g)] for g in games])
    m["orbit_pct"] = med([100 * g["loops"][sd(g)][2] / max(g["loops"][sd(g)][0], 1) for g in games if sd(g) in g["loops"]])
    deaths = [d for g in games for d in g["deaths"] if d["team"] == sd(g)]
    tot = max(len(deaths), 1)
    created = sum(g["start_dragons"] + sum(s["team"] == sd(g) for s in g["splits"]) for g in games)
    m["self_inflicted_share"] = sum(d["reason"] in SELF for d in deaths) / tot
    m["walls_per_100_created"] = 100 * sum(d["reason"] == "hit wall" for d in deaths) / max(created, 1)
    m["own_body_crashes_per_game"] = sum(1 for g in games for d in g["deaths"] if d["team"] == sd(g)
                                         and d["reason"] == "hit other body" and d["into"]
                                         and d["into"]["team"] == sd(g)) / n
    m["early_headon_per_game"] = sum(1 for g in games for d in g["deaths"] if d["team"] == sd(g)
                                     and d["reason"] == "head-to-head" and d["round"] < 100) / n
    m["headon_share"] = sum(d["reason"] == "head-to-head" for d in deaths) / tot
    m["feed_suicides_per_game"] = sum(1 for g in games for d in g["deaths"] if d["team"] == sd(g)
                                      and d["reason"] == "hit self" and d.get("free_nb", 0) > 0 and d["round"] >= 300) / n
    m["late_normal_splits_per_game"] = sum(1 for g in games for s in g["splits"] if s["team"] == sd(g)
                                           and s["round"] >= 300 and s.get("parent_len", 2) > 2) / n
    m["queen_splits_after_r60"] = sum(1 for g in games for s in g["splits"] if s["team"] == sd(g)
                                      and s["parent_is_queen"] and s["round"] >= 60)
    qdead = [next((d for d in g["deaths"] if d["team"] == sd(g) and d["is_queen"]), None) for g in games]
    m["queen_survival"] = sum(q is None for q in qdead) / n
    m["queen_max_len"] = med([max(r[sd(g)]["queen"] for r in g["series"]) for g in games])
    m["queen_killed_by_own_body"] = sum(1 for q in qdead if q and q["reason"] == "hit other body"
                                        and q["into"] and q["into"]["team"] == q["team"])
    rl = [g for g in games if g["result"]["end"] == "round limit"]
    if who == "us":
        m["round500_games"] = len(rl)
        m["round500_lost_while_ahead_total"] = sum(1 for g in rl if not g["won"] and
                                                   g["result"][g["us"]]["total"] > g["result"][g["them"]]["total"])
    return m


# metric, label, phase, target text, direction (+1 higher is better, -1 lower is better), target value
ROWS = [
    ("pearls_r100", "pearls eaten by round 100", "P4", ">= 0.8x them", +1, None),
    ("splits_r100", "splits by round 100", "P4", ">= 0.8x them", +1, None),
    ("early_headon_per_game", "head-on deaths before r100 / game", "P4", "<= 0.7x vD", -1, None),
    ("cover", "map covered by heads r0-149", "P3", ">= 0.50", +1, 0.50),
    ("spawn_cover", "pearl-spawn tiles visited r0-149", "P3", ">= 0.60", +1, 0.60),
    ("orbit_pct", "orbit moves (2x2 circling) %", "P3", "<= 3", -1, 3.0),
    ("queen_survival", "queen alive at the end (share)", "P2", ">= 0.60", +1, 0.60),
    ("queen_max_len", "queen max length (median)", "P2", ">= 8", +1, 8),
    ("queen_splits_after_r60", "queen splits after round 60 (total)", "P2", "= 0", -1, 0),
    ("queen_killed_by_own_body", "queen killed by our own body (games)", "P2", "= 0", -1, 0),
    ("feed_suicides_per_game", "feeding suicides r300+ / game", "P1", "far below vD (18.4)", -1, None),
    ("late_normal_splits_per_game", "normal splits r300+ / game", "P1", "= 0 (escape splits ok)", -1, 0),
    ("self_inflicted_share", "self-inflicted share of our deaths", "P5", "<= 0.40", -1, 0.40),
    ("walls_per_100_created", "wall deaths per 100 dragons made", "P5", "<= 0.5x vD", -1, None),
    ("own_body_crashes_per_game", "crashes into a teammate / game", "P5", "<= 0.5x vD", -1, None),
    ("headon_share", "head-on share of our deaths", "P6", "below vD vs traders", -1, None),
]


def status(key, us, them, base, direction, target):
    if us is None:
        return "-"
    if target is not None:
        if direction > 0:
            return "OK" if us >= target else ("CHECK" if base is None or us > base else "BAD")
        return "OK" if us <= target else ("CHECK" if base is None or us < base else "BAD")
    if key in ("pearls_r100", "splits_r100"):
        return "-" if not them else ("OK" if us >= 0.8 * them else ("CHECK" if us >= 0.5 * them else "BAD"))
    if base is None:
        return "-"
    ratio = {"early_headon_per_game": 0.7, "walls_per_100_created": 0.5, "own_body_crashes_per_game": 0.5,
             "feed_suicides_per_game": 0.3}.get(key, 1.0)
    if us <= ratio * base:
        return "OK"
    return "CHECK" if us < base else "BAD"


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--baseline", default=str(pathlib.Path(__file__).resolve().parent / "baselines" / "vD_server_metrics.json"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--bot")
    ap.add_argument("--save-baseline", action="store_true", help="store these games' metrics as the baseline")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, "*.replay")))
    if not files:
        raise SystemExit(f"no .replay files in {a.dir}")
    with Pool(a.jobs) as p:
        res = p.map(_one, [(f, a.bot) for f in files], chunksize=1)
    bad = [r for r in res if "error" in r]
    games = [r for r in res if "error" not in r]
    us, them = side_metrics(games, "us"), side_metrics(games, "them")
    if a.save_baseline:
        pathlib.Path(a.baseline).write_text(json.dumps(us, indent=1))
        print("saved baseline:", a.baseline)
    base = json.loads(pathlib.Path(a.baseline).read_text()) if os.path.exists(a.baseline) else {}

    w = sum(g["won"] for g in games)
    dr = sum(g["result"]["winner"] is None for g in games)
    l = len(games) - w - dr
    drift = (sum(g["desync"] for g in games), sum(g["checks"] for g in games))
    sides = collections.Counter(g["us"] for g in games)
    per_map = collections.defaultdict(lambda: [0, 0, 0])
    for g in games:
        per_map[g["map"]][0 if g["won"] else (1 if g["result"]["winner"] is None else 2)] += 1
    opp = sorted({re.sub(r"_(WIN|LOSS|DRAW)_us[AB]$", "", pathlib.Path(g["file"]).stem).split("_vs_")[-1] for g in games})

    print(f"\nScorecard for {a.dir}")
    print(f"games {len(games)}  (skipped {len(bad)})   result W{w} D{dr} L{l}  = {100 * w / max(len(games), 1):.0f}% wins")
    print(f"played as A: {sides['A']}  as B: {sides['B']}   opponent(s): {', '.join(opp)[:120]}")
    print(f"replay tracking drift: {drift[0]} of {drift[1]} checks " + ("(OK)" if drift[0] == 0 else "(BAD: numbers below unreliable)"))
    print(f"round-500 games: {us['round500_games']}, lost while ahead on total length: {us['round500_lost_while_ahead_total']}"
          f"  (vD: 11 of 59)")
    print()
    head = f"{'phase':5s} {'metric':38s} {'us':>8s} {'them':>8s} {'vD base':>8s}  {'target':22s} status"
    print(head)
    print("-" * len(head))
    counts = collections.Counter()
    lines = []
    for key, label, phase, ttext, direction, target in ROWS:
        u, t, b = us.get(key), them.get(key), base.get(key)
        s = status(key, u, t, b, direction, target)
        counts[s] += 1
        print(f"{phase:5s} {label:38s} {fmt(u):>8s} {fmt(t):>8s} {fmt(b):>8s}  {ttext:22s} {s}")
        lines.append(f"{phase} {key}={fmt(u)} them={fmt(t)} base={fmt(b)} {s}")
    print()
    print("per map (W-D-L): " + ", ".join(f"{m} {x}-{y}-{z}" for m, (x, y, z) in sorted(per_map.items())))
    print(f"\nstatus: OK {counts['OK']}  CHECK {counts['CHECK']}  BAD {counts['BAD']}")
    print("Small samples swing a lot: a single CHECK/BAD on fewer than ~20 games is a hint, not a verdict.")
    print("\n==== paste from here ====")
    print(f"dir={a.dir} games={len(games)} W{w} D{dr} L{l} drift={drift[0]}/{drift[1]} sides=A{sides['A']}/B{sides['B']} "
          f"r500={us['round500_games']} r500_lost_ahead={us['round500_lost_while_ahead_total']}")
    for ln in lines:
        print(ln)
    print("maps " + " ".join(f"{m.replace(' ', '_')}:{x}-{y}-{z}" for m, (x, y, z) in sorted(per_map.items())))
    print("==== paste to here ====")


if __name__ == "__main__":
    main()
