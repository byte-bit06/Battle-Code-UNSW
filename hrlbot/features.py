"""The manager's observation: a short vector of situation facts, not raw tiles.

Built from options.Facts (no extra search), so it costs almost nothing and
the manager sees exactly what the options' initiation sets see. The last
N_OPTIONS entries are the initiation mask itself.

The ORDER is part of the trained model: append new features at the end of
BASE_NAMES and retrain; never reorder.
"""

import config

BASE_NAMES = [
    "length", "units", "round", "is_longest", "n_safe", "danger",
    "n_enemies", "enemy_dist", "enemy_len_ratio", "enemy_fully_seen", "allies",
    "pearls_near", "nearest_pearl", "cluster", "reports_near", "predicted_soon",
    "portal_near", "explored", "symmetry_locked", "late_game", "hunt_target",
    "ram_available", "long_enough_to_split",
]


def build(t, mask):
    f = t.facts()
    snap, mem = t.snap, t.mem
    L = snap.my_len
    ne = f.nearest_enemy
    out = [
        min(L / 20.0, 3.0),
        min(t.unit_count / 16.0, 2.0),
        snap.round / 500.0,
        1.0 if mem.is_longest(snap) else 0.0,
        len(t.safe) / 4.0,
        1.0 if t.danger() else 0.0,
        min(len(f.enemies) / 3.0, 2.0),
        min(ne[0] / 12.0, 1.0) if ne else 1.0,
        min(ne[1].visible_len / L, 3.0) if ne else 0.0,
        1.0 if ne and ne[1].pos in snap.release else 0.0,
        min(f.allies / 3.0, 2.0),
        min(f.pearls_near / 8.0, 3.0),
        min(f.nearest_pearl / 14.0, 1.0),
        min(f.cluster / 6.0, 2.0),
        min(f.reports_near / 3.0, 1.0),
        min(f.predicted_soon / 8.0, 3.0),
        (1.0 - f.portal / config.PORTAL_RADIUS) if f.portal is not None else 0.0,
        f.explored,
        1.0 if mem.sym.locked() is not None else 0.0,
        1.0 if snap.round >= config.STALL_ROUND else 0.0,
        1.0 if f.hunt_target is not None else 0.0,
        1.0 if f.ram_dir is not None else 0.0,
        1.0 if L >= 8 else 0.0,
    ]
    out.extend(1.0 if m else 0.0 for m in mask)
    return out


def size(n_options):
    return len(BASE_NAMES) + n_options
