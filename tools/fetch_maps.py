"""Download every map in play on the ladder into maps/ladder/ (existing files are kept).

usage: python tools/fetch_maps.py [--dir maps/ladder] [--overwrite]
Map files are named after the map, e.g. maps/ladder/Autarky.map. Several ladder maps differ
from the bundled ones of the same name (Schooltime, Default, Trophy), so they live apart.
"""
import argparse
import sys
import pathlib
import re

from bcapi import get_json


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # team names are unicode
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(pathlib.Path(__file__).resolve().parent.parent / "maps" / "ladder"))
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.dir)
    out.mkdir(parents=True, exist_ok=True)
    added = kept = 0
    for m in get_json("maps"):
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", m["name"]).strip("_")
        path = out / f"{name}.map"
        if path.exists() and not a.overwrite:
            kept += 1
            continue
        path.write_text(m["mapText"].replace("\r\n", "\n"), newline="\n")
        added += 1
        print(f"  {path.name:28s} {m.get('sizeLabel', '')}")
    print(f"maps in {out}: added {added}, kept {kept}")


if __name__ == "__main__":
    main()
