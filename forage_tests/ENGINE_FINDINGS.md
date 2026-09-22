# Engine findings (verified with `probe_bot/` and `unswbc` 0.3.6)

All results come from real local matches (`unswbc run`), not from reading the docs.

## 1. Time limit = CPU points, not wall-clock milliseconds
- The judge runs Python inside a metered WebAssembly sandbox. Each turn gets
  **100,000,000 CPU points** (`MAX_TURN_POINTS` in the toolkit's `sandbox.py`).
- Inside the sandbox `time.perf_counter()` is a **virtual clock: 1 ns = 1 point**.
  So `config.TIME_BUDGET_S = 0.050` means "stop searching after 50M points".
- Measured costs:
  - helper parsing + MOVE + ENDTURN: about 4–6M points per turn;
  - every printed line (log, indicator, sonar) is a write syscall: about 2.5M points plus 4k per byte;
  - one BFS node expansion: about 25–45k points (a full 64×64 BFS exceeds the whole budget);
  - a process's **first turn** also pays about 40M points to import and compile our modules.
    Every split child is a new process, so it pays this too.
- Exceeding the budget kills the dragon ("exceeded CPU limit"), even if a MOVE was already printed.
- Native Python is about 30–50× faster, so plain `unswbc run` hides timeouts.
  Always check with `unswbc run --sandbox -v` and `forage_tests/sandbox_points.py`.

## 2. Pearl spawn timing (corrects the Forage plan's T=1 strike)
- A tile showing countdown 1 that is empty had a pearl the next turn in **392 of 392** observations.
- Stepping **onto** a countdown-1 tile: the dragon grew in **0 of 9** trials. Our own head
  blocks the spawn.
- Being **adjacent** at countdown 1 and stepping on the next turn: the dragon grew every time.
- Rule used by the bot: a countdown `T` seen now spawns at the start of round `now+T`.
  Be adjacent (tile empty) after move `T`, and eat on move `T+1`.
  This is `config.SPAWN_EAT_OFFSET = 1`.
- Parity consequence: every move flips (x+y) parity, so from distance 1 an odd `T` can
  never end adjacent (without portals or odd-width wrap). `timed_approach` returns None then.

## 3. Portals and wrap-around
- Predicted head positions from `geometry.Geo.step` matched the engine on **8,136**
  ordinary moves and **8 of 8** portal crossings.
- Portal rule: you exit on the far side of the partner edge, still travelling the same direction.

## 4. Splitting
- A splitting parent **does not move** that turn. Its head stays put and it loses its
  rear `child` segments. The child spawns at the old tail.
- Current policy (the Forage branch's choice): split **only** when every direction is
  certain death. Standing still survives the turn. Growth splitting is off
  (`ENABLE_SPLIT = False`) until single dragons forage and survive well.
- Trade-off seen in testing: with no growth splitting, the team has fewer dragons and
  is easier to eliminate. The old splitting bot beats it on some maps by elimination.
- Traps are common. In one 500-round game the 8 starting dragons hit 25 "no legal move"
  situations, mostly a mix of kelp, teammates and their own body. That is the safety
  layer's job (Defence).
- A portal whose exit we can't see is still a legal move. It's used as a gamble before
  an emergency split.

## 5. Map files
- Map files label symmetry `y` (x → W−1−x, our `V`), `x` (y → H−1−y, our `H`)
  and `xy` (180° rotation, our `R`).
- Every bundled map's TILE gaps are consistent with our mirror formulas
  (`test_symmetry.py::test_bundled_maps_match_our_formulas`).
