# Local arena: play against our bot with a full-board view

`humanbot/` runs *inside* the official engine, so it can only ever see its
dragon's 7x7 window. It also opens one window per dragon, freezes between turns,
and is killed if you take longer than 10 seconds. `arena/` is a standalone game
instead: it re-implements the rules in Python, draws the whole board like the
official replay viewer, and runs **our real bot code** (`mybot/`) for every
agent dragon.

## Setup (once)
```
pip install pygame          # if it fails on Python 3.14:  pip install pygame-ce
```

## Play (from the repo root)
```
python arena/play.py                          # you = first team-A dragon, rest are agents
python arena/play.py --map arena --duel       # 1 v 1 on a small map
python arena/play.py --map big_empty          # the 64x64 map
python arena/play.py --team B                 # play team B (moves after team A each round)
python arena/play.py --turn-based             # the game waits for your move every turn
python arena/play.py --watch --map big_empty  # agent vs agent, just watch
python arena/play.py --speed 3 --seed 42      # slower rounds, repeatable game
```

## Controls
| Key | Action |
|---|---|
| WASD / arrows | Steer. In real time, the latest key is used when your turn comes. |
| Shift + direction | Queue a sprint step. Two or more queued steps become a sprint (x steps cost x-1 length). |
| Enter | Turn-based mode: submit the queued sprint. |
| Q / E | Split off a child of length 2 / split in half. |
| Space / N | Pause / advance one round while paused. |
| + / - | Change the speed (rounds per second). |
| M | Switch between real-time and turn-based. |
| G | Neck guard: ignore a key that would reverse into your own neck. It's on by default; turn it off for pure rules. |
| F | Fog: show only what your dragon can see, which is the real game's view. |
| C | Highlight tiles whose pearl spawns within 5 rounds. |
| T | Draw each agent's current target. |
| Mouse hover | Tile info: countdown, pearl, dragon id, length and the agent's plan. |
| R / Esc | Restart with a new seed / quit. |

## Rules implemented (sim.py)
- **Map:** wrap-around; kelp and portals on edges. Portals exit on the far side of the
  partner edge, still travelling the same direction.
- **Turns:** 500 rounds. Dragons act in ascending id order. A child created by a split
  acts later in the same round.
- **Pearls:**
  - countdowns tick at the start of each round;
  - a tile spawns only if it's empty;
  - mirror tiles share a countdown;
  - new countdowns are random within each tile's hidden `[min_gap, max_gap]`.
- **Collisions** are checked before anything moves:
  - kelp, any body segment (including your own tail) or any head kills you;
  - moving into a head kills both dragons.
- **Eating** makes the dragon grow, because the tail doesn't advance that step.
- **Sprinting:** x steps cost x-1 segments, with collisions and eating checked at every step.
  Over-sprinting kills.
- **Splitting:**
  - the parent doesn't move;
  - the child is the parent's reversed rear part, facing away from the parent;
  - both parts must be at least 2 long, and a team can have at most 64 dragons;
  - an illegal split kills the dragon.
- **Death** drops a pearl on every second segment from the head, so ⌈L/2⌉ pearls.
- **Sonar:** a ray from the head in the facing direction, delivered to the first dragon
  it hits and read at the start of that dragon's next turn.
- **Winning:** eliminate the other team. After 500 rounds the tiebreaks are the longest
  living dragon, then total length.

**Checked against the real engine:**
- map edges: 22,724 checked, 0 mismatches;
- dragon ids and teams;
- portal exits for every tile and direction on 5 maps;
- countdown ranges;
- similar game statistics: 47 vs 49 deaths on `default`, with our bot on both sides.

`python -m pytest -q arena` runs the 13 rule tests.
The official engine (`unswbc run`) remains the source of truth, and it's what the ladder uses.

## Notes
- **The agent has no CPU limit here.** The simulator gives it real time rather than the
  judge's 100M points, so it behaves like the submitted bot but doesn't feel the time limit.
- **Replays of real engine games:** open the `.replay` files that `unswbc run` writes, in
  VS Code (`unswbc vscode`) or at https://game.battlecode.au/visualiser.
