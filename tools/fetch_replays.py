"""Download the server replays of every game one submission played.

usage: python tools/fetch_replays.py SUBMISSION_ID [--out replays/server_<id>]
       python tools/fetch_replays.py --list          (show submissions)

Battles do not name the submission that played them, so a submission's battles are the ones
between its upload and the next successful upload. The total is checked against the
submission's own win/draw/loss record. Files are named
<gameId>_<map>_vs_<opponent>_<WIN|LOSS|DRAW>_us<A|B>.replay plus an index.json.
"""
import argparse
import json
import sys
import pathlib
import re
import urllib.error

from bcapi import get_bytes, get_json


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # team names are unicode
    ap = argparse.ArgumentParser()
    ap.add_argument("submission", nargs="?", type=int)
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    team_id = get_json("me")["team"]["id"]
    subs = sorted(get_json("submissions"), key=lambda s: s["uploadedAt"])
    if a.list or a.submission is None:
        for s in subs:
            print(f"{s['id']:7d} {s['uploadedAt'][:19]} {s['status']:8s} {s['language']:6s} "
                  f"W{s['wins']}/D{s['draws']}/L{s['losses']}  {s['name']}")
        return
    sub = next(s for s in subs if s["id"] == a.submission)
    later = [s for s in subs if s["uploadedAt"] > sub["uploadedAt"] and s["status"] != "failed"]
    end = later[0]["uploadedAt"] if later else "9999"
    battles = [b for b in get_json("battles?limit=200") if sub["uploadedAt"] <= b["at"] < end]
    out = pathlib.Path(a.out or pathlib.Path(__file__).resolve().parent.parent / "replays" / f"server_{sub['id']}")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for b in sorted(battles, key=lambda b: b["at"]):
        d = get_json(f"battles/{b['id']}")
        m = d["match"]
        us = "a" if m["teamAId"] == team_id else "b"
        opp = d["teamBName"] if us == "a" else d["teamAName"]
        for g in d["games"]:
            res = "DRAW" if g["winner"] not in ("a", "b") else ("WIN" if g["winner"] == us else "LOSS")
            slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{g['mapName']}_vs_{opp}").strip("_")
            name = f"{g['id']}_{slug}_{res}_us{us.upper()}.replay"
            status = "no replay"
            if g.get("hasReplay"):
                path = out / name
                if path.exists():
                    status = "already here"
                else:
                    try:
                        path.write_bytes(get_bytes(f"battles/{g['id']}/replay"))
                        status = "saved"
                    except urllib.error.HTTPError as e:
                        status = f"HTTP {e.code}"
            rows.append({"battle": b["id"], "game": g["id"], "map": g["mapName"], "opponent": opp,
                         "opponentElo": b["opponentElo"], "ranked": b["ranked"], "us": us.upper(),
                         "result": res, "file": name, "status": status, "at": b["at"]})
            print(f"{g['id']} {g['mapName']:20s} vs {opp:22s} us={us.upper()} {res:4s} {status}")
    (out / "index.json").write_text(json.dumps(rows, indent=1))
    w = sum(r["result"] == "WIN" for r in rows); l = sum(r["result"] == "LOSS" for r in rows)
    dr = sum(r["result"] == "DRAW" for r in rows)
    expected = (sub["wins"], sub["draws"], sub["losses"])
    print(f"{len(rows)} games ({w}W {dr}D {l}L) in {out}")
    if (w, dr, l) != expected:
        print(f"WARNING: submission record is W{expected[0]}/D{expected[1]}/L{expected[2]}; the time window "
              f"may include another version's games, or some are missing (only the last 200 battles are listed)")


if __name__ == "__main__":
    main()
