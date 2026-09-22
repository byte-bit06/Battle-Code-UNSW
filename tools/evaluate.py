"""Automated match testing: play two bots on every map, in both team orders.

Usage (from the repo root):
    python tools/evaluate.py mybot oldbot
    python tools/evaluate.py mybot oldbot --maps default trophy
    python tools/evaluate.py mybot mybot --set C_D=3 --set C_R=60     # tune a weight

--set makes a temporary copy of the FIRST bot with those config.py values
changed (e.g. C_D=3), so you can compare a tweak against the unchanged bot.
Prints wins, how each game ended, and deaths per side. Native speed only; use
`unswbc run --sandbox` + forage_tests/sandbox_points.py for CPU checks.
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile


def make_variant(bot, sets):
    tmp = tempfile.mkdtemp(prefix="variant_")
    dst = os.path.join(tmp, os.path.basename(bot.rstrip("/\\")) + "_variant")
    shutil.copytree(bot, dst, ignore=shutil.ignore_patterns("__pycache__"))
    cfg = os.path.join(dst, "config.py")
    text = open(cfg).read()
    for item in sets:
        name, value = item.split("=", 1)
        text, n = re.subn(rf"^{name}\s*=\s*[^#\n]*", f"{name} = {value} ", text, flags=re.M)
        if n == 0:
            sys.exit(f"config.py has no setting called {name}")
    open(cfg, "w").write(text)
    return dst


def play(map_path, a, b):
    out = subprocess.run(["unswbc", "run", "--no-replay", map_path, a, b],
                         capture_output=True, text=True).stdout
    res = re.search(r"team ([AB]) wins after (\d+) rounds \(([^)]*)\)", out)
    draw = re.search(r"draw", out, re.I)
    deaths = {"A": len(re.findall(r"\(team A\) died", out)), "B": len(re.findall(r"\(team B\) died", out))}
    if res:
        return res.group(1), int(res.group(2)), res.group(3), deaths
    return ("draw" if draw else "?"), 0, "", deaths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("other")
    ap.add_argument("--maps", nargs="*")
    ap.add_argument("--set", action="append", default=[], help="NAME=VALUE for the first bot's config.py")
    args = ap.parse_args()
    bot = make_variant(args.bot, args.set) if args.set else args.bot
    maps = [os.path.join("maps", m if m.endswith(".map") else m + ".map") for m in args.maps] \
        if args.maps else sorted(glob.glob(os.path.join("maps", "*.map")))
    wins = losses = draws = 0
    for m in maps:
        for order in ("A", "B"):
            a, b = (bot, args.other) if order == "A" else (args.other, bot)
            winner, rounds, how, deaths = play(m, a, b)
            me, them = order, ("B" if order == "A" else "A")
            if winner == me:
                wins += 1
                tag = "WIN "
            elif winner == them:
                losses += 1
                tag = "LOSS"
            else:
                draws += 1
                tag = "DRAW"
            print(f"{tag}  {os.path.basename(m):22s} as {me}  r{rounds:3d}  {how:16s} "
                  f"deaths ours {deaths[me]:3d} theirs {deaths[them]:3d}", flush=True)
    print(f"\n{args.bot}{' ' + ' '.join(args.set) if args.set else ''} vs {args.other}: "
          f"{wins} wins, {losses} losses, {draws} draws")


if __name__ == "__main__":
    main()
