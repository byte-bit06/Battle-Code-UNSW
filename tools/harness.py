"""Local matches between two bots on many maps, both sides, in parallel; replays for report.py.

usage: python tools/harness.py US_BOT THEM_BOT [--maps DIR_OR_LIST] [--runs 1] [--jobs 12]
                               [--budget SECONDS] [--out replays/local_<us>_vs_<them>] [--report]

Rules (learnt the hard way):
- Every game gets private copies of both bots, so parallel builds never collide.
- --budget shrinks a C++ bot's per-turn search clock for faster games. leanMargin is scaled
  with it: if it is not, every turn is a one-step "lean" turn and the test is invalid.
  Without --budget the bots run exactly as submitted.
- Replays are named <map>_r<run>_vs_<them>_<WIN|LOSS|DRAW>_us<A|B>.replay for report.py.
- Needs unswbc >= 1.x (0.3.6 rejects PROTOCOL 3 sonar, so the radio would be off).
"""
import argparse
import collections
import concurrent.futures as cf
import glob
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RESULT = re.compile(r"^(team ([AB]) wins after (\d+) rounds|draw after (\d+) rounds)", re.M)


def env_with_compiler() -> dict:
    env = dict(os.environ)
    if env.get("CXX") or any(shutil.which(c) for c in ("c++", "g++", "clang++", "cl")):
        return env
    zbin = HERE / ".zig" / "bin"
    if (zbin / "zcxx.cmd").exists() or (zbin / "zcxx").exists():
        env["PATH"] = str(zbin) + os.pathsep + env["PATH"]
        env["CXX"] = "zcxx.cmd" if sys.platform == "win32" else "zcxx"
    return env


def prepare(src: pathlib.Path, dst: pathlib.Path, budget) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".unswbc-build", "__pycache__", "*.exe", "*.pdb"))
    common = dst / "common.hpp"
    if budget is None or not common.exists():
        return
    text = common.read_text()
    text = text.replace("#pragma once", f"#pragma once\n#define BC_TURN_BUDGET {budget}", 1)
    text, n = re.subn(r"(double leanMargin = )[^;]+;", rf"\g<1>{budget * 0.4};", text)
    if n != 1:
        raise SystemExit(f"{src}: cannot scale leanMargin; refusing to run an invalid test")
    common.write_text(text)


def play(us, them, mp, side, run, budget, out, env):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bc_", dir=ROOT / ".games"))
    try:
        prepare(us, tmp / "us", budget)
        prepare(them, tmp / "them", budget)
        (tmp / "maps").mkdir()
        shutil.copy(mp, tmp / "maps" / mp.name)
        a, b = ("us", "them") if side == "A" else ("them", "us")
        replay = tmp / "game.replay"
        p = subprocess.run(["unswbc", "run", f"maps/{mp.name}", a, b, "-o", str(replay)], cwd=tmp, env=env,
                           capture_output=True, text=True, errors="replace", timeout=7200)
        found = RESULT.findall(p.stdout + p.stderr)
        if not found:
            return {"map": mp.stem, "side": side, "run": run, "result": "ERROR", "detail": (p.stdout + p.stderr)[-500:]}
        line, winner, r1, r2 = found[-1]
        res = "DRAW" if not winner else ("WIN" if winner == side else "LOSS")
        name = f"{mp.stem}_r{run}_vs_{them.name}_{res}_us{side}.replay"
        if replay.exists():
            shutil.move(str(replay), out / name)
        return {"map": mp.stem, "side": side, "run": run, "result": res, "rounds": int(r1 or r2)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("us"); ap.add_argument("them")
    ap.add_argument("--maps", default=str(ROOT / "maps" / "ladder"))
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--budget", type=float)
    ap.add_argument("--out")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    us, them = pathlib.Path(a.us).resolve(), pathlib.Path(a.them).resolve()
    if os.path.isdir(a.maps):
        maps = sorted(pathlib.Path(p) for p in glob.glob(os.path.join(a.maps, "*.map")))
    else:
        maps = [pathlib.Path(m if m.endswith(".map") else str(ROOT / "maps" / "ladder" / f"{m}.map")) for m in a.maps.split(",")]
    out = pathlib.Path(a.out or ROOT / "replays" / f"local_{us.name}_vs_{them.name}")
    out.mkdir(parents=True, exist_ok=True)
    (ROOT / ".games").mkdir(exist_ok=True)
    env = env_with_compiler()
    jobs = [(mp, side, run) for run in range(a.runs) for mp in maps for side in "AB"]
    results = []
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(play, us, them, mp, side, run, a.budget, out, env) for mp, side, run in jobs]
        for f in cf.as_completed(futs):
            r = f.result()
            results.append(r)
            print(f"  {r['map']:20s} us={r['side']} run {r['run']}: {r['result']}", flush=True)
    by = collections.defaultdict(collections.Counter)
    for r in results:
        by[r["map"]][r["result"]] += 1
    print(f"\n== {us.name} vs {them.name}" + (f" (budget {a.budget}s)" if a.budget else " (real budget)"))
    for m, c in sorted(by.items()):
        print(f"   {m:20s} W{c['WIN']} D{c['DRAW']} L{c['LOSS']}" + (f" ERRORS {c['ERROR']}" if c["ERROR"] else ""))
    tot = collections.Counter(r["result"] for r in results)
    print(f"   overall: W{tot['WIN']} D{tot['DRAW']} L{tot['LOSS']} of {len(results)}"
          + (f" (ERRORS {tot['ERROR']})" if tot["ERROR"] else ""))
    for r in results:
        if r["result"] == "ERROR":
            print("   error detail:", r["map"], r["side"], r["detail"][-300:])
    if a.report:
        subprocess.run([sys.executable, str(HERE / "report.py"), str(out), "--label", f"{us.name} vs {them.name}"])


if __name__ == "__main__":
    main()
