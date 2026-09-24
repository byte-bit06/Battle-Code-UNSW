# Instinct_Engine — Defence Under Coordinated Attack

**Branch:** `Instinct_Engine` (supersedes `Defence_Engine`)
**Goal:** Survive two or more enemy dragons attacking together. Beating one chaser is a pathfinding problem; beating three is a *tempo and connectivity* problem, and the existing Defence doc does not model either.

Instinct has absolute priority. Forage, Scout and Flood only run when Instinct reports slack.

---

## 1. What Carries Over, What Changes

| Defence doc item | Verdict | Change |
|---|---|---|
| Timeout wrapper + Level 1 fallback | Keep | Add **plan memory** (§4.9) so a timeout follows last turn's escape plan instead of a fresh myopic step |
| Worst-case tail assumption (∞ for unseen heads) | Upgrade | Too pessimistic when surrounded — it can make a live dragon conclude it is already dead. Replace with **two-tier safety** (§4.4) |
| Lazy Tarjan below 1.5×L volume | Keep, retrigger | Also trigger on **corridor count ≤ 2** (§4.3), not volume alone; volume stays high right up until a pincer closes |
| Per-enemy sprint envelopes, gated at Chebyshev ≤ 8 | Upgrade | Envelopes must be **unioned over time**, not read one enemy at a time (§4.2). Gate on travel time, not Chebyshev — wrap and portals break raw distance |
| Lexicographic scorer | Rebuild | New key order in §5; current order has no term for encirclement or ram exposure |
| Ram the largest adjacent head when doomed | Refine | Trade value depends on **who we are** (§4.6). Our longest dragon must not trade |

---

## 2. Threat Model

A coordinated attack has three features a single chaser does not:

1. **Escape routes close simultaneously.** No single enemy envelope looks lethal; their union does.
2. **Sacrifice is cheap for them.** A head-to-head kills both dragons regardless of length, so a length-2 enemy child can delete our length-40 dragon and hand them the round-500 tiebreak. Any enemy head is a lethal weapon.
3. **The third attacker is invisible.** Vision is 7×7, so an attack can be one dragon short of complete in everything we can see.

Instinct's job is to keep the *number of independent escape corridors* above 1 at all times, and to detect the closing pattern early — while escape is still free — because a late escape costs sprint length, and every segment spent shrinks tomorrow's options.

---

## 3. Module Layout

```
instinct/
  control.py     # SHARED with Flood: time-expanded board control D[d][v]
  tempo.py       # turn-order classes, ram exposure
  corridors.py   # escape connectivity, chambers, Tarjan on the real graph
  space.py       # timed self-space, forced-growth model
  ladder.py      # reflex ladder, plan memory, anytime deepening
  policy.py      # lexicographic scorer, trade policy, defensive split
```

`control.py` is deliberately shared with Flood: attacking is the same computation run on a target instead of on ourselves.

---

## 4. The Additions

### 4.1 Time-Expanded Board Control (shared)

`D[d][v]` = earliest subturn dragon `d` can legally occupy tile `v`, where a subturn is `(round, turn_order, sprint_step)`. Multi-source BFS from every known head, expanded in ascending ID order, over the real movement graph: wrap, portals (SURVEYED only for us, LINKED for enemies — they may know what we don't), kelp impassable, and body tiles released at their predicted vacate time.

Derived per tile: `margin(v) = D[enemy_first][v] − D[me][v]`. Contested (`margin == 0`) is **neutral and dangerous, never ours** — a shared arrival is a mutual kill.

### 4.2 Joint Envelopes, Not Per-Enemy Envelopes

Per-enemy envelopes answer "can this one dragon reach me". The question that matters is "is there a tile I can still be on at time t that *no* enemy can reach by t". So:

```python
reach_me[t]  = timed flood from my head, t = 0..H
threat[t]    = union over enemies of their reachable set at t   # includes sprints they can afford
free[t]      = reach_me[t] - threat[t]
```

`escape_depth` = largest `t` where `free[t]` is non-empty and connected back to my head. If `escape_depth < H`, we are in a closing net even if every individual enemy looks distant. Track `escape_depth` turn over turn: **two consecutive drops is the trigger to break out**, well before the count reaches zero.

### 4.3 Corridor Count (the pincer detector)

Volume is a lagging signal. Connectivity is a leading one.

```python
def corridor_count(graph, head, open_region, k_max=3):
    # cheap min-cut estimate: repeatedly shortest-path to open space, delete
    # the interior tiles of that path, retry. Stop at k_max.
    for k in range(k_max):
        p = shortest_path(graph, head, open_region)
        if p is None: return k
        graph = graph.without(p.interior_tiles())
    return k_max
```

- `corridor_count == 0` → already sealed; sprint or trade.
- `== 1` → one cut tile stands between us and the open board. Record it. If any enemy's `D` to that tile is ≤ ours, leave **now**.
- `≥ 2` → healthy; Tarjan can stay switched off.

This is the single highest-value addition in this document. Encirclement by three dragons shows up here several turns before it shows up in flood-fill volume.

### 4.4 Two-Tier Safety (replacing blanket ∞)

Blanket ∞ for every body whose head is out of vision is correct for a *guarantee* but useless for ranking — surrounded, every option scores ∞-bad and the dragon picks arbitrarily.

- **Tier A (hard filter):** worst case. Unknown-length bodies never vacate, unseen sprints are affordable, phantom heads exist (§4.7). Only Tier A can mark a move *guaranteed safe*.
- **Tier B (ranking):** best estimate. Enemy length estimated as `max(visible_segments, last_known_length, 2)`, tails released on that estimate, sprints weighted by how much length the enemy would actually pay.

Policy: if any Tier A move exists, take the best of those. If none exists, rank by Tier B rather than giving up — this is exactly the moment a coordinated attack is trying to produce.

### 4.5 Forced Growth (pearls as traps)

Moving onto a pearl eats it automatically — there is no way to decline — and the tail does not advance that turn. In open space this is a gift. Inside a chamber it is an attack: every pearl on our escape path delays every later tail release by one step. A shrinking-space route must be simulated against the **grown** body, and a chamber whose pearl count plus our length exceeds its tile count is not survivable.

Corollary: an enemy that dies near us drops ⌈L/2⌉ pearls on every second segment of its corpse. That is a wall of forced growth laid across the board. In tight quarters, a fresh corpse is terrain to path *around*, not through.

### 4.6 Ram Exposure and Who May Trade

Any enemy head that can reach our head's tile before we move again kills us, and length is irrelevant. Every other dragon acts between our turns, so:

> **Never end a turn with our head reachable by an enemy head, unless we want the trade.**

Reachable means within their affordable sprint (`s ≤ L_e − 1`) on the movement graph, not within Chebyshev 1.

Trade policy by role:

| Our dragon | Rule |
|---|---|
| Team's longest (tiebreak holder) | Never trade. Ram exposure is a hard Tier A violation; keep a 2-step buffer over the worst enemy sprint |
| Mid-size | Trade only if `L_enemy ≥ L_us + 4`, or the enemy is their longest dragon |
| Length 2–3 | Trade freely; we drop 1 pearl, they drop ⌈L/2⌉, and a teammate should be closer to the drop than they are |

### 4.7 Phantom Heads and Portal Mouths

Two threat sources the current plan ignores:

- **Vision-edge phantoms.** For each direction with recent enemy activity (seen, or reported by sonar), inject a virtual enemy head at the vision boundary with median observed length. Tier A only. Without this, the third attacker always arrives free.
- **Portal mouths.** A LINKED portal within reach is an enemy spawn point: treat its exit tile as a head source at `D = 1`, decayed by how long since anyone observed the far side. Fed by Scout_Engine.

### 4.8 The Defensive Split

Splitting is a legal escape almost nobody models. It requires `L ≥ 4` (child ≥ 2, parent ≥ 2 after), the team under 64 living dragons, and it **forfeits the move that turn** — so it is only safe when no enemy head can reach us this round.

Why it works when boxed in: the parent keeps the head and drops to length `L − k`, so it needs far less circulation space, and the child materialises at the old tail facing outward, plugging the corridor behind us. Two short dragons survive chambers one long dragon cannot.

Conditions, all required: `corridor_count ≤ 1`, our timed space `< L`, no enemy head reaches us this round, and both `A_head ≥ L − k` and `A_tail ≥ k` for the chosen `k`. An illegal split kills the parent, so validate `can_split(k)` before calling.

### 4.9 Reflex Ladder, Plan Memory, Anytime Deepening

```
L0  reflex      precomputed before any search: safest legal 1-step (kelp, bodies, neck, adjacent heads)
L1  shallow     1-step + Tier A filter + corridor count            ~fast
L2  standard    escape_depth to H=6, chamber scoring
L3  deep        H=10, enemy minimax on the masked local fight
```

Each level overwrites `best_action` only after fully completing, so the answer is always usable — this is iterative deepening, not a fixed horizon. Two additions:

- **Plan memory:** keep the escape route chosen last turn. On timeout, follow its next step (re-validated at L0) instead of a fresh myopic move. Panicking coherently beats panicking randomly.
- **Budget from measurement:** the rules say a turn that exceeds the limit *with* a valid action already submitted meets a different fate than death, but the Timeouts page was not in `rules.md`. Until measured, submit L0 immediately, then keep improving and re-submit.

### 4.10 Anti-Fratricide

A head-to-head kills both dragons **regardless of team**. A team that clusters defensively kills itself. Because turns run in ascending ID, the later mover has full information:

> **The higher-ID dragon yields.** Never move into a tile a lower-ID teammate occupies or could still occupy this round; assume teammates with a lower ID will not avoid us.

No messaging needed — it is derivable from IDs alone, which every dragon can read from vision.

---

## 5. Revised Lexicographic Key

```python
return (
    tier_a_safe,             # bool: survives worst case for 1 round
    -ram_exposure,           # count of enemy heads that can reach us (§4.6)
    min(corridor_count, 3),  # keep at least two ways out
    escape_depth,            # §4.2, the joint-envelope horizon
    -sprint_cost,            # s - 1 length, still heavily punished
    timed_space,             # space with vacate schedule, not raw flood fill
    R_tail,                  # max(0, L - 15) * 50
    pearl_utility,
)
```

`ram_exposure` and `corridor_count` sit above volume deliberately: a wide-open tile with two enemy heads covering it is worse than a narrow one with none.

---

## 6. Turn Wiring

```python
def execute_turn():
    t0 = time.perf_counter()
    state = read_state(ct)
    submit(L0_reflex(state))                  # always have a valid action on file

    try:
        control = build_control(state)        # §4.1, shared with Flood
        tempo   = classify_enemies(state)     # lower ID = committed this round, higher = reacts after us
        for level in (L1, L2, L3):
            if over_budget(t0): break
            best = level(state, control, tempo)
            submit(best)
        memory.plan = best.route
    except TimeoutInterrupt:
        submit(memory.plan.next_step() or L0_reflex(state))

    if instinct_slack(best):                  # only then may other engines act
        flood.advise(state, control)
```

---

## 7. Scenario Test Suite

Build these as fixed boards; they are the acceptance bar.

| Scenario | Pass condition |
|---|---|
| **2v1 pincer** in open field | `corridor_count` drops to 2 at least 3 turns before contact; dragon leaves through the wider side without sprinting |
| **3v1 chamber seal** | Break out before the last corridor closes, or split (§4.8) and keep both halves alive 20+ turns |
| **Sacrificial ram** — length-2 enemy charges our length-30 dragon | Zero ram exposure maintained; never trades |
| **Pearl chamber** — enemy seals us in with 4 pearls | Route simulated against grown body; does not path onto pearls it cannot afford |
| **Fresh corpse wall** | Treats the ⌈L/2⌉ drop as forced-growth terrain, does not tunnel through it under pressure |
| **Invisible third attacker** | Phantom heads keep an escape reserved on the blind side; survives the reveal |
| **Teammate convergence** — 3 allies flee into one pocket | Zero friendly head-to-heads across 1,000 turns |
| **Timeout storm** — budget cut to 25% | Zero deaths from no-valid-action; plan memory keeps the escape coherent |

Metric to track across versions: **mean rounds survived under scripted 2-, 3- and 4-attacker scenarios**, plus deaths broken down by cause (wall / self / other body / head-to-head / no action).

---

## 8. Rule Check (`rules.md`)

| Relied on | Status |
|---|---|
| Turns ascend by dragon ID; lesser IDs have already acted | ✅ Stated — basis of §4.10 and tempo classes |
| Head-to-head kills both dragons regardless of length or team | ✅ Stated — basis of §4.6 and anti-fratricide |
| Collisions checked before movement; moving into own tail is fatal even if it would vacate | ✅ Stated |
| Sprint of `x` steps costs `x − 1`; collisions checked at every step; overspend is fatal | ✅ Stated — affordable sprint `s ≤ L − 1` |
| Eating a pearl is automatic and the tail does not advance | ✅ Stated — basis of §4.5 |
| Death drops ⌈L/2⌉ pearls on every second segment from the head | ✅ Stated |
| Split: child ≥ 2, parent ≥ 2 after, team < 64; illegal split kills the parent; split replaces the move | ✅ Stated |
| Child appears at the old tail facing outward, new higher ID, acts later the same round, no memory | ✅ Stated |
| Vision 7×7 Chebyshev ≤ 3, wraps, does not see through portals | ✅ Stated — basis of phantom heads |
| Map wraps; kelp and portals sit on edges; portals keep direction | ✅ Stated |
| No valid action = death | ✅ Stated — L0 submitted first, always |
| What exactly happens on timeout **with** a valid action already submitted | ⚠️ `rules.md` points to a Timeouts page not included. Measure it |
| Whether `make_moves` may be called more than once per turn (last one counts) | ⚠️ Implied by "only the last one is actually performed" — confirm the re-submit pattern in §6 |
| Enemy length when the head is out of vision | ⚠️ Not knowable; hence the two tiers in §4.4 |

Nothing here needs a rule that `rules.md` does not grant. The two ⚠️ API items should be settled with one throwaway test match before L1 is built.
