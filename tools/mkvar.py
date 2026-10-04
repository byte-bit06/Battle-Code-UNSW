"""Copy a C++ bot and change Params defaults, for testing variants without editing the source.

usage: python tools/mkvar.py SRC_BOT DST_BOT key=value [key=value ...]
e.g.   python tools/mkvar.py aura_vD variants/no_feed feedMaxLen=0
"""
import pathlib
import re
import shutil
import sys


def main() -> None:
    src, dst, sets = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".unswbc-build", "*.exe", "*.pdb"))
    p = dst / "common.hpp"
    s = p.read_text()
    for kv in sets:
        k, v = kv.split("=", 1)
        s, n = re.subn(rf"(\b(?:int|double) {re.escape(k)} = )[^;]+;", rf"\g<1>{v};", s)
        if n != 1:
            raise SystemExit(f"no Params field {k!r} in {p}")
    p.write_bytes(s.replace("\r\n", "\n").encode())
    print(dst, sets)


if __name__ == "__main__":
    main()
