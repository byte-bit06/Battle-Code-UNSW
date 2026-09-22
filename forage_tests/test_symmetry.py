"""Stage 4: symmetry inference."""
import glob
import os

import memory
from fakes import make

ME = [(1, 1), (1, 2), (1, 3)]


def test_vertical_only_evidence():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    # same countdown at (2,4) and its V-mirror (17,4); different at the H/R mirrors
    make(W, H, ME, visible=[(2, 4), (1, 1), (1, 2), (1, 3)], countdowns={(2, 4): 30}, round_num=10, mem=mem)
    make(W, H, ME, visible=[(17, 4), (2, 7), (17, 7)],
         countdowns={(17, 4): 30, (2, 7): 11, (17, 7): 11}, round_num=10, mem=mem)
    assert mem.sym.alive == {"V": True, "H": False, "R": False}
    assert mem.sym.locked() == "V"


def test_countdown_projection_over_time():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    make(W, H, ME, visible=[(2, 4)], countdowns={(2, 4): 30}, round_num=10, mem=mem)
    # 5 rounds later the V-mirror shows 25: consistent, so V survives
    make(W, H, ME, visible=[(17, 4)], countdowns={(17, 4): 25}, round_num=15, mem=mem)
    assert mem.sym.alive["V"]


def test_single_contradiction_only_kills_that_hypothesis():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    make(W, H, ME, visible=[(2, 4)], countdowns={(2, 4): 30}, round_num=10, mem=mem)
    make(W, H, ME, visible=[(17, 4)], countdowns={(17, 4): 9}, round_num=10, mem=mem)
    assert mem.sym.alive == {"V": False, "H": True, "R": True}


def test_never_spawn_mismatch():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    make(W, H, ME, visible=[(2, 4)], countdowns={(2, 4): -1}, round_num=3, mem=mem)
    make(W, H, ME, visible=[(2, 7)], countdowns={(2, 7): 40}, round_num=3, mem=mem)
    assert not mem.sym.alive["H"]


def test_full_contradiction_fails_safe():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    make(W, H, ME, visible=[(2, 4)], countdowns={(2, 4): 30}, round_num=10, mem=mem)
    make(W, H, ME, visible=[(17, 4), (2, 7), (17, 7)],
         countdowns={(17, 4): 1, (2, 7): 2, (17, 7): 3}, round_num=10, mem=mem)
    assert mem.sym.contradiction and mem.sym.locked() is None


def test_mirror_fills_unseen_side_after_lock():
    W, H = 20, 12
    mem = memory.WorldMemory(W, H)
    mem.sym.alive = {"V": True, "H": False, "R": False}
    make(W, H, ME, visible=[(2, 4), (1, 1), (1, 2), (1, 3)], countdowns={(2, 4): 30},
         kelp=[(2, 4, 1)], round_num=10, mem=mem)
    g = mem.geo
    assert mem.predicted_countdown(g.idx(17, 4), 10) == 30
    assert g.step(g.idx(17, 4), 3) == -1         # mirrored kelp: east edge -> west edge


def _parse_map(path):
    size = sym = None
    gaps = {}
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "MAP":
            size = (int(p[1]), int(p[2]))
        elif p[0] == "SYMMETRY":
            sym = p[1]
        elif p[0] == "TILE":
            gaps[(int(p[1]), int(p[2]))] = (int(p[3]), int(p[4]))
    return size, sym, gaps


def test_bundled_maps_match_our_formulas():
    """Map files label symmetry y / x / xy. Check our V / H / R mirror formulas
    map every TILE (x, y, min_gap, max_gap) onto an identical tile."""
    maps = glob.glob(os.path.join(os.path.dirname(__file__), "..", "maps", "*.map"))
    label = {"y": "V", "x": "H", "xy": "R"}
    checked = 0
    for path in maps:
        (W, H), sym, gaps = _parse_map(path)
        if sym not in label:
            continue
        hyp = label[sym]
        for (x, y), g in gaps.items():
            mx, my = {"V": (W - 1 - x, y), "H": (x, H - 1 - y), "R": (W - 1 - x, H - 1 - y)}[hyp]
            assert gaps.get((mx, my)) == g, (path, (x, y))
        checked += 1
    assert checked > 0
