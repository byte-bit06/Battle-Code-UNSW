"""Play against our bot (or watch it) with a full-board view.

    python arena/play.py                      # you (team A) vs our agent on default.map
    python arena/play.py --map arena --duel   # 1 v 1, one dragon each
    python arena/play.py --team B             # play as team B (moves after A each round)
    python arena/play.py --watch              # agent vs agent, no human
    python arena/play.py --turn-based         # game waits for your move each turn

Controls
  WASD / arrows   steer (real-time: the latest key is used when your turn comes)
  Shift + dir     queue a sprint step (2+ queued = sprint; costs length-1... see rules)
  Enter           turn-based: submit a queued sprint
  Q / E           split: child of 2 / split in half (rules: both parts >= 2 long)
  Space  pause    N  single round while paused       + / -  speed
  M  real-time <-> turn-based     G  neck-guard assist on/off
  F  fog (only what your dragon sees)   C  pearl countdowns   T  agent targets
  H  help overlay    R  restart (new seed)    Esc  quit
"""
import argparse
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import pygame
except ImportError:
    sys.exit("pygame is not installed:  pip install pygame   (or pip install pygame-ce)")

import agents                      # noqa: E402
import sim as S                    # noqa: E402

MAPS = os.path.join(os.path.dirname(HERE), "maps")

BG = (15, 20, 36)
CHECK_A = (46, 61, 104)
CHECK_B = (41, 55, 95)
PEARL = (232, 234, 242)
PEARL_EDGE = (160, 166, 190)
TEAM = {"A": (95, 168, 152), "B": (208, 108, 64)}
TEAM_DARK = {"A": (62, 120, 108), "B": (150, 72, 40)}
KELP = (74, 170, 92)
PORTAL = (170, 110, 220)
YOU = (255, 226, 120)
TEXT = (226, 230, 240)
DIM = (140, 150, 175)
PANEL = (22, 28, 48)
SIDEBAR = 350
FRAME_BUDGET = 0.012               # seconds of simulation work per frame (keeps 60 fps)


def resolve_map(name):
    if os.path.isfile(name):
        return name
    p = os.path.join(MAPS, name if name.endswith(".map") else name + ".map")
    if not os.path.isfile(p):
        sys.exit(f"map not found: {name}  (available: {', '.join(sorted(f[:-4] for f in os.listdir(MAPS)))})")
    return p


class Game:
    def __init__(self, args):
        self.args = args
        pygame.init()
        pygame.display.set_caption("UNSW Battlecode - local arena")
        info = pygame.display.Info()
        self.max_board = max(360, min(info.current_h - 80, info.current_w - SIDEBAR - 40, 900))
        self.font = pygame.font.SysFont("consolas,menlo,dejavusansmono,monospace", 15)
        self.small = pygame.font.SysFont("consolas,menlo,dejavusansmono,monospace", 12)
        self.big = pygame.font.SysFont("consolas,menlo,dejavusansmono,monospace", 28, bold=True)
        self.clock = pygame.time.Clock()
        self.speed = args.speed
        self.turn_based = args.turn_based
        self.show_fog = False
        self.show_cd = False
        self.show_targets = False
        self.show_help = False
        self.neck_guard = True
        self.restart(args.seed)

    # ------------------------------------------------------------ setup --
    def restart(self, seed=None):
        a = self.args
        self.seed = seed if seed is not None else random.randrange(10 ** 6)
        self.sim = S.Sim(resolve_map(a.map), seed=self.seed, duel=a.duel)
        self.human = None
        self.human_dragon = None
        mine = self.sim.alive_ids(a.team)
        for d in self.sim.dragons.values():
            if not a.watch and mine and d.id == mine[0]:
                self.human = agents.HumanController()
                d.controller = self.human
                self.human_dragon = d
            else:
                d.controller = agents.AgentController(self.sim)
        s = self.sim
        self.cell = max(4, self.max_board // max(s.W, s.H))
        self.bw, self.bh = self.cell * s.W, self.cell * s.H
        self.screen = pygame.display.set_mode((self.bw + SIDEBAR, max(self.bh, 640)))
        self.background = self._render_background()
        self.gen = None
        self.next_round_at = time.perf_counter() + 0.6
        self.paused = False
        self.step_once = False
        self.waiting_human = False
        self.last_round_ms = 0.0

    def _render_background(self):
        s, c = self.sim, self.cell
        surf = pygame.Surface((self.bw, self.bh))
        for y in range(s.H):
            for x in range(s.W):
                surf.fill(CHECK_A if (x + y) % 2 == 0 else CHECK_B, (x * c, y * c, c, c))
        w = max(2, c // 5)
        for (x, y), (t, pid) in s.map.north.items():
            col = KELP if t == 1 else PORTAL
            pygame.draw.line(surf, col, (x * c, y * c), (x * c + c, y * c), w)
            if y == 0:
                pygame.draw.line(surf, col, (x * c, self.bh - 1), (x * c + c, self.bh - 1), w)
        for (x, y), (t, pid) in s.map.west.items():
            col = KELP if t == 1 else PORTAL
            pygame.draw.line(surf, col, (x * c, y * c), (x * c, y * c + c), w)
            if x == 0:
                pygame.draw.line(surf, col, (self.bw - 1, y * c), (self.bw - 1, y * c + c), w)
        return surf

    # -------------------------------------------------------- simulation --
    def round_gen(self):
        s = self.sim
        t0 = time.perf_counter()
        s.start_round()
        for d in s.turn_order():
            if d.controller is self.human and self.turn_based:
                self.waiting_human = True
                while not self.human.ready:
                    yield
                self.waiting_human = False
            agents.take_turn(s, d)
            yield
        s.end_round()
        self.last_round_ms = (time.perf_counter() - t0) * 1000

    def advance(self):
        now = time.perf_counter()
        if self.sim.over:
            return
        if self.gen is None:
            if self.paused and not self.step_once:
                return
            waiting_for_human = self.turn_based and self.human_dragon is not None and self.human_dragon.alive
            if not waiting_for_human and not self.step_once and now < self.next_round_at:
                return
            self.step_once = False
            self.gen = self.round_gen()
            self.round_started = now
        end = now + FRAME_BUDGET
        while time.perf_counter() < end:
            try:
                next(self.gen)
            except StopIteration:
                self.gen = None
                self.next_round_at = self.round_started + 1.0 / self.speed
                break
            if self.waiting_human and not self.human.ready:
                break

    # ------------------------------------------------------------- input --
    def on_key(self, ev):
        k = ev.key
        shift = ev.mod & pygame.KMOD_SHIFT
        dirs = {pygame.K_w: 0, pygame.K_UP: 0, pygame.K_d: 1, pygame.K_RIGHT: 1,
                pygame.K_s: 2, pygame.K_DOWN: 2, pygame.K_a: 3, pygame.K_LEFT: 3}
        h, hd = self.human, self.human_dragon
        if k in dirs and h is not None and hd is not None and hd.alive:
            d = dirs[k]
            if shift:
                if len(h.sprint) < hd.length - 1:
                    h.sprint.append(d)
                return
            if self.neck_guard and hd.length > 1 and self.sim.step(hd.head, d) == hd.cells[1]:
                return                                  # would bite our own neck
            h.direction = d
            h.sprint = []
            if self.turn_based:
                h.ready = True
            return
        if k in (pygame.K_RETURN, pygame.K_KP_ENTER) and h is not None and self.turn_based:
            h.ready = True
        elif k == pygame.K_q and h is not None and hd is not None and hd.alive:
            h.split_request = 2
            h.ready = self.turn_based or h.ready
        elif k == pygame.K_e and h is not None and hd is not None and hd.alive:
            h.split_request = hd.length // 2
            h.ready = self.turn_based or h.ready
        elif k == pygame.K_SPACE:
            self.paused = not self.paused
        elif k == pygame.K_n:
            self.step_once = True
        elif k in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.speed = min(60.0, self.speed * 1.5)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.speed = max(0.5, self.speed / 1.5)
        elif k == pygame.K_m:
            self.turn_based = not self.turn_based
        elif k == pygame.K_g:
            self.neck_guard = not self.neck_guard
        elif k == pygame.K_f:
            self.show_fog = not self.show_fog
        elif k == pygame.K_c:
            self.show_cd = not self.show_cd
        elif k == pygame.K_t:
            self.show_targets = not self.show_targets
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        elif k == pygame.K_r:
            self.restart()

    # ------------------------------------------------------------ drawing --
    def center(self, t):
        c = self.cell
        return (t[0] * c + c // 2, t[1] * c + c // 2)

    def draw_board(self):
        scr, s, c = self.screen, self.sim, self.cell
        scr.blit(self.background, (0, 0))
        if self.show_cd:
            overlay = pygame.Surface((c, c), pygame.SRCALPHA)
            for tile in s.group_of:
                v = s.countdown(tile)
                if 1 <= v <= 5 and tile not in s.pearls:
                    overlay.fill((255, 214, 90, 150 - v * 25))
                    scr.blit(overlay, (tile[0] * c, tile[1] * c))
        r = max(2, int(c * 0.22))
        for p in s.pearls:
            cx, cy = self.center(p)
            pygame.draw.circle(scr, PEARL_EDGE, (cx, cy + 1), r)
            pygame.draw.circle(scr, PEARL, (cx, cy), r)
        for d in sorted(s.dragons.values(), key=lambda d: d.id):
            if d.alive:
                self.draw_dragon(d)
        if self.show_targets:
            for d in s.dragons.values():
                t = getattr(d.controller, "target", None)
                if d.alive and t is not None:
                    tx, ty = (t % s.W, t // s.W) if isinstance(t, int) else t
                    pygame.draw.line(scr, (255, 255, 255), self.center(d.head), self.center((tx, ty)), 1)
                    pygame.draw.circle(scr, (255, 255, 255), self.center((tx, ty)), max(3, c // 3), 1)
        if self.show_fog and self.human_dragon is not None and self.human_dragon.alive:
            fog = pygame.Surface((self.bw, self.bh), pygame.SRCALPHA)
            fog.fill((5, 8, 18, 170))
            for t in s.vision_tiles(self.human_dragon):
                fog.fill((0, 0, 0, 0), (t[0] * c, t[1] * c, c, c))
            scr.blit(fog, (0, 0))

    def draw_dragon(self, d):
        scr, c = self.screen, self.cell
        col, dark = TEAM[d.team], TEAM_DARK[d.team]
        pts = [self.center(t) for t in d.cells]
        width = max(3, int(c * 0.62))
        for i in range(len(d.cells) - 1):
            a, b = d.cells[i], d.cells[i + 1]
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1:          # skip wrap/portal jumps
                pygame.draw.line(scr, col, pts[i], pts[i + 1], width)
        n = len(pts)
        for i in range(n - 1, 0, -1):
            rad = max(2, int(c * (0.30 + 0.06 * (1 - i / n))))
            pygame.draw.circle(scr, col, pts[i], rad)
            if c >= 10 and i % 2 == 0:                             # scale pattern
                pygame.draw.circle(scr, dark, pts[i], max(1, rad // 3))
        hx, hy = pts[0]
        pygame.draw.circle(scr, col, (hx, hy), max(3, int(c * 0.46)))
        if d is self.human_dragon:
            pygame.draw.circle(scr, YOU, (hx, hy), max(4, int(c * 0.52)), 2)
        if c >= 8:
            dx, dy = S.DX[d.dirs[0]], S.DY[d.dirs[0]]
            px, py = -dy, dx
            for side in (-1, 1):
                ex = hx + int(dx * c * 0.18 + px * side * c * 0.2)
                ey = hy + int(dy * c * 0.18 + py * side * c * 0.2)
                pygame.draw.circle(scr, (250, 250, 250), (ex, ey), max(1, c // 8))
                pygame.draw.circle(scr, (20, 20, 20), (ex + int(dx * c * 0.05), ey + int(dy * c * 0.05)),
                                   max(1, c // 16))

    def text(self, s, x, y, col=TEXT, font=None):
        surf = (font or self.font).render(s, True, col)
        self.screen.blit(surf, (x, y))
        return y + surf.get_height() + 3

    def draw_sidebar(self):
        s, scr = self.sim, self.screen
        x0 = self.bw
        scr.fill(PANEL, (x0, 0, SIDEBAR, scr.get_height()))
        x = x0 + 16
        y = self.text("UNSW BATTLECODE", x, 12, YOU, self.big)
        y = self.text(f"{s.map.name or self.args.map}  {s.W}x{s.H}  seed {self.seed}", x, y + 2, DIM, self.small)
        y = self.text(f"Round {s.round}/{S.MAX_ROUNDS}", x, y + 8)
        mode = "turn-based" if self.turn_based else f"real-time {self.speed:.1f} rounds/s"
        y = self.text(f"Mode  {mode}", x, y)
        state = "PAUSED" if self.paused else ("YOUR TURN" if self.waiting_human else "running")
        y = self.text(f"State {state}   ({self.last_round_ms:.0f} ms/round)", x, y,
                      YOU if self.waiting_human else TEXT)
        y += 8
        for team in ("A", "B"):
            ids = s.alive_ids(team)
            lens = [s.dragons[i].length for i in ids]
            label = "you + agents" if self.human and self.args.team == team else "agent"
            pygame.draw.rect(scr, TEAM[team], (x, y + 3, 12, 12))
            y = self.text(f"  Team {team} ({label})", x, y)
            y = self.text(f"    alive {len(ids):2d}  longest {max(lens) if lens else 0:3d}  total {sum(lens):4d}",
                          x, y, DIM)
        y += 8
        hd = self.human_dragon
        if hd is not None:
            if hd.alive:
                y = self.text(f"You: dragon {hd.id}  length {hd.length}", x, y, YOU)
                arrows = "NESW"
                q = "".join(arrows[d] for d in self.human.sprint)
                y = self.text(f"  heading {arrows[hd.dirs[0]]}   sprint queue [{q}]", x, y, DIM)
                y = self.text(f"  neck guard {'on' if self.neck_guard else 'off'} (G)", x, y, DIM)
            else:
                y = self.text(f"You died (round {hd.death_round}): {hd.death_cause}", x, y, (240, 120, 110))
                y = self.text("  spectating - R to restart", x, y, DIM)
        y += 8
        y = self.text("Events", x, y, DIM)
        for r, e in s.events[-9:]:
            y = self.text(f"{r:3d} {e[:40]}", x, y, TEXT, self.small)
        y = max(y + 8, scr.get_height() - 150)
        for line in ("WASD/arrows steer   Shift+dir sprint",
                     "Q/E split   Space pause   N step",
                     "+/- speed   M turn-based   G guard",
                     "F fog   C countdowns   T targets",
                     "H help   R restart   Esc quit"):
            y = self.text(line, x, y, DIM, self.small)
        mx, my = pygame.mouse.get_pos()
        if mx < self.bw and my < self.bh:
            t = (mx // self.cell, my // self.cell)
            o = s.occ.get(t)
            info = f"({t[0]},{t[1]}) countdown {s.countdown(t)}"
            if t in s.pearls:
                info += "  pearl"
            if o is not None:
                info += f"  dragon {o.id} len {o.length}"
                dbg = getattr(o.controller, "debug", "")
                if dbg:
                    info += f"  [{dbg}]"
            self.text(info[:48], x, scr.get_height() - 22, YOU, self.small)

    def draw_overlays(self):
        scr = self.screen
        if self.sim.over:
            self.banner(self.sim.result, "R to play again   Esc to quit")
        elif self.show_help:
            self.banner("How to play", "Eat pearls to grow. Hitting kelp, any body or a head kills you.")
        elif self.waiting_human:
            pygame.draw.rect(scr, YOU, (0, 0, self.bw, self.bh), 3)

    def banner(self, title, sub):
        w, h = self.bw, 110
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((10, 12, 24, 215))
        self.screen.blit(box, (0, self.bh // 2 - h // 2))
        t = self.big.render(title, True, YOU)
        self.screen.blit(t, (w // 2 - t.get_width() // 2, self.bh // 2 - 38))
        t = self.font.render(sub, True, TEXT)
        self.screen.blit(t, (w // 2 - t.get_width() // 2, self.bh // 2 + 8))

    # --------------------------------------------------------------- loop --
    def run(self, max_frames=None, screenshot=None):
        frames = 0
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                    pygame.quit()
                    return
                if ev.type == pygame.KEYDOWN:
                    self.on_key(ev)
            self.advance()
            self.screen.fill(BG)
            self.draw_board()
            self.draw_sidebar()
            self.draw_overlays()
            pygame.display.flip()
            self.clock.tick(60)
            frames += 1
            if max_frames is not None and frames >= max_frames:
                if screenshot:
                    pygame.image.save(self.screen, screenshot)
                pygame.quit()
                return


def main():
    ap = argparse.ArgumentParser(description="Play against (or watch) our Battlecode agent")
    ap.add_argument("--map", default="default", help="map name in maps/ or a path")
    ap.add_argument("--team", default="A", choices=["A", "B"], help="the team you play")
    ap.add_argument("--watch", action="store_true", help="agent vs agent, no human")
    ap.add_argument("--duel", action="store_true", help="only one dragon per team")
    ap.add_argument("--turn-based", action="store_true", help="wait for your move every turn")
    ap.add_argument("--speed", type=float, default=5.0, help="rounds per second in real-time mode")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--frames", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--screenshot", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()
    Game(args).run(args.frames, args.screenshot)


if __name__ == "__main__":
    main()
