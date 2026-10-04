"""Rebuild every dragon's body from a replay and extract game statistics.

usage: python tools/replay_analyse.py REPLAY (A|B|BOTNAME)

Bodies are simulated from MOVE events using the map's edges (wrap, kelp, portals) and
checked against the engine's DragonUpdate head/tail after every turn.
"""
import collections
from replay_decode import decode

D = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


class Map:
    def __init__(self, text):
        self.dragons, self.kelp, self.portal_edges = [], 0, collections.defaultdict(list)
        self.h, self.v = {}, {}   # (x, y) -> ('kelp',) or ('portal', pid)
        self.beds = 0
        for line in text.splitlines():
            t = line.split()
            if not t:
                continue
            if t[0] == "MAP":
                self.W, self.H = int(t[1]), int(t[2])
            elif t[0] == "MAP_NAME":
                self.name = line.split(None, 1)[1].strip()
            elif t[0] == "TILE" and int(t[4]) > 0:
                self.beds += 1
            elif t[0] == "EDGE":
                idx, kind, pid = int(t[1]), int(t[2]), int(t[3])
                r = self.W + 1
                i, a = divmod(idx, r)
                if i % 2 == 0:
                    key, tbl, orient = (a, i // 2), self.h, "h"
                else:
                    key, tbl, orient = (a, (i - 1) // 2), self.v, "v"
                key = (key[0] % self.W, key[1] % self.H)
                if kind == 1:
                    tbl[key] = ("kelp",); self.kelp += 1
                elif kind == 2:
                    tbl[key] = ("portal", pid); self.portal_edges[pid].append((orient, key))
            elif t[0] in ("DRAGON", "SNAKE"):
                team, n = int(t[1]), int(t[2])
                cells = [(int(t[3 + 2 * k]), int(t[4 + 2 * k])) for k in range(n)]
                self.dragons.append(("AB"[team], cells))
        self.partner = {}
        for pid, ends in self.portal_edges.items():
            if len(ends) == 2:
                self.partner[ends[0]] = ends[1]; self.partner[ends[1]] = ends[0]

    def edge(self, x, y, d):
        W, H = self.W, self.H
        if d == "N":
            return "h", (x % W, y % H)
        if d == "S":
            return "h", (x % W, (y + 1) % H)
        if d == "W":
            return "v", (x % W, y % H)
        return "v", ((x + 1) % W, y % H)

    def step(self, cell, d):
        """Tile after one step, or None for kelp."""
        orient, key = self.edge(cell[0], cell[1], d)
        e = (self.h if orient == "h" else self.v).get(key)
        if e and e[0] == "kelp":
            return None
        if e and e[0] == "portal" and (orient, key) in self.partner:
            po, (px, py) = self.partner[(orient, key)]
            if po == "h":
                return (px % self.W, (py - 1) % self.H) if d == "N" else (px % self.W, py % self.H)
            return ((px - 1) % self.W, py % self.H) if d == "W" else (px % self.W, py % self.H)
        dx, dy = D[d]
        return ((cell[0] + dx) % self.W, (cell[1] + dy) % self.H)


def cheb(a, b, W, H):
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(min(dx, W - dx), min(dy, H - dy))


def analyse(path, us=None, our_bot=None):
    """Statistics for one replay. Our side is `us` ("A"/"B"), or the side whose bot name is
    `our_bot` (server replays name bots by submission id, e.g. "16309")."""
    r = decode(path)
    mp = Map(r["map"])
    if us is None:
        if our_bot is None or our_bot not in (r["botA"], r["botB"]):
            raise ValueError(f"cannot tell our side: bots are {r['botA']!r} and {r['botB']!r}")
        us = "A" if r["botA"] == our_bot else "B"
    them = "B" if us == "A" else "A"
    queen = {"A": 0, "B": 1}
    team, body = {}, {}
    for i, (tm, cells) in enumerate(mp.dragons):
        team[i] = tm; body[i] = collections.deque(cells)
    alive = set(body)
    pearls = set()
    rnd = 0
    series = []                               # per round: counts and lengths
    deaths, splits = [], []
    eaten = collections.Counter()
    desync = checks = 0
    pending = {}                              # id -> info about its last move (for deaths)
    steps = {}                                # id -> directions of its MOVE not yet applied
    seen = {"A": set(), "B": set()}           # tiles under a head of that team, rounds 0-149
    spawn_tiles = set()
    eaten_at = {}                             # round cut -> copy of eaten counter
    cur_turn = None

    occ = {}                                  # cell -> dragon id (bodies never overlap)
    for i, b in body.items():
        for c in b:
            occ[c] = i

    def occupant(cell):
        i = occ.get(cell)
        if i is None or i not in alive:
            return None, False
        return i, body[i][0] == cell

    def set_body(i, cells):
        for c in body.get(i, ()):
            if occ.get(c) == i:
                del occ[c]
        body[i] = collections.deque(cells)
        for c in body[i]:
            occ[c] = i

    recent = collections.defaultdict(lambda: collections.deque(maxlen=12))
    loopstat = collections.defaultdict(lambda: [0, 0, 0])   # team -> [moves, revisits, orbit moves]
    last_dirs = collections.defaultdict(lambda: collections.deque(maxlen=4))

    def snapshot():
        row = {"round": rnd}
        for tm in "AB":
            ids = [i for i in alive if team[i] == tm]
            lens = [len(body[i]) for i in ids]
            row[tm] = {"n": len(ids), "total": sum(lens), "max": max(lens, default=0),
                       "queen": len(body[queen[tm]]) if queen[tm] in alive else 0}
        series.append(row)

    for ev in r["events"]:
        k = ev[0]
        if k == "round":
            if rnd or series:
                snapshot()
            rnd = ev[1]
            for cut in (25, 50, 100):
                if rnd == cut:
                    eaten_at[cut] = dict(eaten)
        elif k == "turn":
            cur_turn = ev[1]
        elif k == "tile":
            if not ev[2] and cur_turn in steps and steps[cur_turn] and cur_turn in alive:
                nxt = mp.step(body[cur_turn][0], steps[cur_turn][0])
                if nxt == ev[1]:
                    eaten[team[cur_turn]] += 1      # the pearl on the tile we are stepping onto
            (pearls.add if ev[2] else pearls.discard)(ev[1])
            if ev[2]:
                spawn_tiles.add(ev[1])
        elif k == "move":
            i, dirs = ev[1], ev[2]
            steps[i] = collections.deque(dirs)
            pending[i] = {"round": rnd, "id": i, "dirs": dirs, "len": len(body[i]), "from": body[i][0]}
        elif k == "update":
            i, facing, head, tail = ev[1], ev[2], ev[3], ev[4]
            if i not in body:
                continue
            b = body[i]
            if steps.get(i):                       # one engine update per step taken
                nxt = mp.step(b[0], steps[i].popleft())
                if nxt is not None:
                    b.appendleft(nxt); occ[nxt] = i
            checks += 1
            if rnd < 150 and team.get(i) in seen:
                seen[team[i]].add(head)
            if b and b[0] == head and tail in b:
                while b[-1] != tail:
                    c = b.pop()
                    if occ.get(c) == i:
                        del occ[c]
            else:
                desync += 1
                set_body(i, [head] + ([tail] if tail != head else []))
            st = loopstat[team[i]]
            st[0] += 1
            if head in recent[i]:
                st[1] += 1
            recent[i].append(head)
            mv = pending.get(i, {}).get("dirs", "")
            if len(mv) == 1:
                last_dirs[i].append(mv)
                ld = "".join(last_dirs[i])
                if len(ld) == 4 and len(set(ld)) == 4:   # four different turns in a row: a 2x2 orbit
                    st[2] += 1
        elif k == "split":
            parent, child, tm, facing, pbody, cbody = ev[1:7]
            team[child] = tm
            set_body(parent, pbody); set_body(child, cbody)
            alive.add(child)
            qd = None
            if queen[tm] in alive and parent != queen[tm]:
                qd = cheb(cbody[0], body[queen[tm]][0], mp.W, mp.H)
            splits.append({"round": rnd, "team": tm, "parent": parent, "child": child,
                           "parent_is_queen": parent == queen[tm], "child_len": len(cbody),
                           "child_dist_to_queen": qd})
        elif k == "death":
            i, reason = ev[1], ev[2]
            info = pending.get(i, {})
            victim_of = None
            if steps.get(i) and i in body and body[i]:   # the step that failed
                target = mp.step(body[i][0], steps[i][0])
                who, is_head = occupant(target) if target is not None else (None, False)
                if who is not None and who != i:
                    victim_of = {"id": who, "team": team.get(who), "is_head": is_head,
                                 "len": len(body[who]) if who in body else None,
                                 "is_queen": who == queen.get(team.get(who), -1)}
            free_nb = 0                          # free neighbours of the head at death (kelp / dragons block)
            if i in body and body[i]:
                h0 = body[i][0]
                neck = body[i][1] if len(body[i]) > 1 else None
                for dd in "NESW":
                    c = mp.step(h0, dd)
                    if c is None or c == neck:
                        continue
                    if occupant(c)[0] is None:
                        free_nb += 1
            near_enemy = near_friend = 0
            if i in body and body[i]:
                h = body[i][0]
                for j in alive:
                    if j == i or not body[j]:
                        continue
                    if cheb(body[j][0], h, mp.W, mp.H) <= 3:
                        if team[j] == team[i]:
                            near_friend += 1
                        else:
                            near_enemy += 1
            deaths.append({"round": rnd, "id": i, "team": team[i], "reason": reason,
                           "len": len(body[i]) if i in body else None, "is_queen": i == queen[team[i]],
                           "into": victim_of, "near_enemy": near_enemy, "near_friend": near_friend,
                           "steps": len(info.get("dirs", "")), "free_nb": free_nb, "turn_of": cur_turn,
                           "head": body[i][0] if i in body and body[i] else None})
            alive.discard(i)
            for c in body.get(i, ()):
                if occ.get(c) == i:
                    del occ[c]
    snapshot()
    return {"file": path, "map": mp.name, "W": mp.W, "H": mp.H, "kelp": mp.kelp,
            "portals": len(mp.partner) // 2, "start_dragons": sum(1 for t, _ in mp.dragons if t == "A"),
            "beds": mp.beds, "us": us, "them": them, "result": r["result"],
            "won": r["result"]["winner"] == us, "rounds": rnd, "series": series, "deaths": deaths,
            "splits": splits, "eaten": dict(eaten), "desync": desync, "checks": checks,
            "loops": {t: v for t, v in loopstat.items()},
            "cover": {t: len(seen[t]) / (mp.W * mp.H) for t in "AB"},
            "spawn_cover": {t: len(seen[t] & spawn_tiles) / max(len(spawn_tiles), 1) for t in "AB"},
            "eaten_at": {cut: eaten_at.get(cut, dict(eaten)) for cut in (25, 50, 100)}}


if __name__ == "__main__":
    import sys
    a = analyse(sys.argv[1], us=sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in ("A", "B") else None,
                our_bot=sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] not in ("A", "B") else None)
    print({k: a[k] for k in ("map", "us", "won", "rounds", "eaten", "desync", "checks", "result")})
    print("deaths", collections.Counter((d["team"], d["reason"]) for d in a["deaths"]))
    print("splits", collections.Counter(s["team"] for s in a["splits"]))
    for row in a["series"][::20]:
        print(row)
