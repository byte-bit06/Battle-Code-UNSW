# Mr Aura tools (Phase 0)

Test and analysis tooling for the C++ bot. The submitted vD source lives frozen in
`../aura_vD/` (identical to server submission 16309). Never edit it: it is the baseline.

## One-time setup

```bash
pip install -U unswbc               # 1.2.9 or newer: 0.3.6 rejects PROTOCOL 3 sonar
unswbc auth set bc_YOURKEY          # team key, needed for the API tools
python tools/setup_compiler.py      # only if no C++ compiler is installed (adds Zig to tools/.zig/)
python tools/fetch_maps.py          # ladder maps -> maps/ladder/
```

## Everyday loop

```bash
# 1. local A/B test: new bot vs vD on every ladder map, both sides
python tools/harness.py my_new_bot aura_vD --runs 3 --report

# 2. after uploading, pull that submission's server games and grade them
python tools/fetch_replays.py --list
python tools/fetch_replays.py SUBMISSION_ID
python tools/report.py replays/server_SUBMISSION_ID --label vE1 --json tools/baselines/vE1_server.json

# 3. compare against tools/baselines/vD_server.txt
```

`tools/mkvar.py SRC DST key=value ...` copies a bot with different `Params` defaults, for
testing a setting without touching the source.

## Files

| File | What it does |
|------|--------------|
| `bcapi.py` | Read-only contest API helper; uses the key stored by `unswbc auth`, never prints it |
| `fetch_maps.py` | Downloads the ladder maps (with real pearl timings) into `maps/ladder/` |
| `fetch_replays.py` | Downloads every server replay of one submission, named `..._WIN_usA.replay` |
| `replay_decode.py` | Decodes `.replay` files (packed Cap'n Proto; server copies are gzipped) |
| `replay_analyse.py` | Rebuilds every dragon's body each step (checked against the engine; 0 drift) and extracts deaths, splits, pearls, coverage, loops, tiebreaks |
| `report.py` | The report card: every metric from the vD review, split by wins and losses |
| `harness.py` | Local matches in parallel, private bot copies, replays named for `report.py` |
| `mkvar.py` | Bot copy with changed `Params` defaults |
| `setup_compiler.py` | Zig-based C++ compiler for `unswbc` on machines without one |
| `baselines/` | Report cards to compare against (vD server, vD local mirror) |

## Rules for a valid test

- **Engine version.** Use unswbc 1.x. Version 0.3.6 silently drops every `SONAR` and
  `PROTOCOL 3` line, so the radio is off in local games.
- **Budget.** `--budget` speeds games up, but `leanMargin` must scale with it (`harness.py`
  does this, and refuses if it can't). A small budget with the default margin makes every
  turn a one-step turn, and the results mean nothing.
- **Noise.** 16 games carry about ±3 wins of noise. Use `--runs 3` or more over all ladder
  maps before believing a difference.
- **Ladder maps.** Schooltime, Default and Trophy on the ladder differ from the bundled maps
  of the same name. Test on `maps/ladder/`.
- **Server is final.** Ladder opponents are not vD. Grade every upload with `report.py`.

## Report card fields

- `ended`: elimination vs round limit.
- `dragons_ratio_rN`: our dragons ÷ theirs at round N (median).
- `pearls_rN_*`, `splits_rN_*`: by round N.
- `cover_*`, `spawn_cover_*`: share of the map, and of pearl-spawn tiles, under a head in rounds 0–149.
- `self_inflicted_share`: wall + self + body deaths ÷ all our deaths.
- `self_inflicted_with_free_neighbour`: of those, deaths with a free tile beside the head.
- `late_feeding_suicides_per_game`: step-into-own-body with a free neighbour, round ≥ 350.
- `crashes_into_own_body_per_game`: crashes into a teammate's body.
- `queen_*`: survival, death round and cause, max length, splits.
- `orbit_pct_*`: share of moves that are the 4th different turn in a row (2×2 orbits).
- `round_limit_games`, `lost_while_ahead_on_total`: tiebreak outcomes.
