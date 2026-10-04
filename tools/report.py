"""Report card for a set of replays: every metric from the vD review, wins vs losses.

usage: python tools/report.py REPLAY_DIR [--bot NAME] [--json OUT] [--jobs 16] [--label vD]

Our side per replay: the "_usA" / "_usB" suffix in the file name (fetch_replays.py and
harness.py name files that way), otherwise --bot (the bot name inside the replay; on the
server that is the submission id).
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
from replay_analyse import analyse  # noqa: E402

SELF = ("hit wall", "hit self", "hit other body")


def _one(job):
    path, bot = job
    m = re.search(r"_us([AB])\b", pathlib.Path(path).stem)
    try:
        g = analyse(path, us=m.group(1) if m else None, our_bot=None if m else bot)
        g.pop("series_full", None)
        return g
    except Exception as e:  # keep going: one bad file should not stop the report
        return {"file": path, "error": repr(e)}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 3) if xs else None


def ratio(a, b):
    return a / b if b else (float("inf") if a else 1.0)


def at(g, rnd, side):
    rows = [r for r in g["series"] if r["round"] <= rnd]
    return rows[-1][side] if rows else None


def card(games):
    """All metrics as a dict (also printed by main)."""
    W = [g for g in games if g["won"]]
    L = [g for g in games if not g["won"]]
    out = {"n_games": len(games), "n_wins": len(W), "n_losses": len(L)}
    groups = {"all": games, "wins": W, "losses": L}
    for name, gs in groups.items():
        if not gs:
            continue
        row = {}
        row["ended"] = dict(collections.Counter(g["result"]["end"] for g in gs))
        for rnd in (50, 100, 200):
            row[f"dragons_ratio_r{rnd}"] = med([ratio(at(g, rnd, g["us"])["n"], at(g, rnd, g["them"])["n"])
                                                for g in gs if at(g, rnd, g["us"])])
        row["pearls_ratio_game"] = med([ratio(g["eaten"].get(g["us"], 0), g["eaten"].get(g["them"], 0)) for g in gs])
        for cut in (25, 50, 100):
            row[f"pearls_r{cut}_us"] = med([g["eaten_at"][cut].get(g["us"], 0) for g in gs])
            row[f"pearls_r{cut}_them"] = med([g["eaten_at"][cut].get(g["them"], 0) for g in gs])
            row[f"splits_r{cut}_us"] = med([sum(s["team"] == g["us"] and s["round"] < cut for s in g["splits"]) for g in gs])
            row[f"splits_r{cut}_them"] = med([sum(s["team"] == g["them"] and s["round"] < cut for s in g["splits"]) for g in gs])
        row["cover_us"] = med([g["cover"][g["us"]] for g in gs])
        row["cover_them"] = med([g["cover"][g["them"]] for g in gs])
        row["spawn_cover_us"] = med([g["spawn_cover"][g["us"]] for g in gs])
        row["spawn_cover_them"] = med([g["spawn_cover"][g["them"]] for g in gs])
        deaths = collections.Counter(); avoid = 0; feed_suicides = 0; into_own = 0
        for g in gs:
            for d in g["deaths"]:
                if d["team"] != g["us"]:
                    continue
                deaths[d["reason"]] += 1
                if d["reason"] in SELF and d.get("free_nb", 0) > 0:
                    avoid += 1
                if d["reason"] == "hit self" and d.get("free_nb", 0) > 0 and d["round"] >= 350:
                    feed_suicides += 1
                if d["reason"] == "hit other body" and d["into"] and d["into"]["team"] == g["us"]:
                    into_own += 1
        tot = sum(deaths.values())
        row["deaths"] = dict(deaths)
        row["self_inflicted_share"] = round(sum(deaths[r] for r in SELF) / max(tot, 1), 3)
        row["self_inflicted_with_free_neighbour"] = avoid
        row["late_feeding_suicides_per_game"] = round(feed_suicides / len(gs), 1)
        row["crashes_into_own_body_per_game"] = round(into_own / len(gs), 1)
        qd = [d for g in gs for d in g["deaths"] if d["team"] == g["us"] and d["is_queen"]]
        row["queen_died_games"] = len(qd)
        row["queen_death_round"] = med([d["round"] for d in qd])
        row["queen_death_causes"] = dict(collections.Counter(
            d["reason"] + ("" if not d["into"] else (" ->own" if d["into"]["team"] == d["team"] else " ->enemy")) for d in qd))
        row["queen_max_len"] = med([max(r[g["us"]]["queen"] for r in g["series"]) for g in gs])
        row["queen_splits"] = sum(1 for g in gs for s in g["splits"] if s["team"] == g["us"] and s["parent_is_queen"])
        row["orbit_pct_us"] = med([100 * g["loops"][g["us"]][2] / max(g["loops"][g["us"]][0], 1) for g in gs if g["us"] in g["loops"]])
        row["orbit_pct_them"] = med([100 * g["loops"][g["them"]][2] / max(g["loops"][g["them"]][0], 1) for g in gs if g["them"] in g["loops"]])
        out[name] = row
    # round-500 tiebreaks
    tb = []
    for g in games:
        if g["result"]["end"] != "round limit":
            continue
        us, th = g["us"], g["them"]
        q = g["series"][-1]
        tb.append({"map": g["map"], "won": g["won"], "queen": [q[us]["queen"], q[th]["queen"]],
                   "longest": [g["result"][us]["longest"], g["result"][th]["longest"]],
                   "dragons": [g["result"][us]["dragons"], g["result"][th]["dragons"]],
                   "total": [g["result"][us]["total"], g["result"][th]["total"]]})
    out["round_limit_games"] = tb
    out["lost_while_ahead_on_total"] = sum(1 for t in tb if not t["won"] and t["total"][0] > t["total"][1])
    per_map = collections.defaultdict(lambda: [0, 0])
    for g in games:
        per_map[g["map"]][0 if g["won"] else 1] += 1
    out["per_map"] = {m: f"{w}-{l}" for m, (w, l) in sorted(per_map.items())}
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # team names are unicode
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--bot")
    ap.add_argument("--json")
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, "*.replay")))
    with Pool(a.jobs) as p:
        res = p.map(_one, [(f, a.bot) for f in files], chunksize=1)
    bad = [r for r in res if "error" in r]
    games = [r for r in res if "error" not in r]
    for b in bad:
        print("skipped", b["file"], b["error"])
    c = card(games)
    c["label"] = a.label
    c["drift"] = [sum(g["desync"] for g in games), sum(g["checks"] for g in games)]
    print(f"== report card {a.label}: {c['n_wins']}W {c['n_losses']}L from {len(games)} games "
          f"(body-tracking drift {c['drift'][0]} of {c['drift'][1]})")
    for name in ("all", "wins", "losses"):
        if name in c:
            print(f"-- {name}")
            for k, v in c[name].items():
                print(f"   {k:38s} {v}")
    print(f"-- round-500 games: {len(c['round_limit_games'])}; lost while ahead on total length: {c['lost_while_ahead_on_total']}")
    print("-- per map:", c["per_map"])
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(c, indent=1))


if __name__ == "__main__":
    main()
