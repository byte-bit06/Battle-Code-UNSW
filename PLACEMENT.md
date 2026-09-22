# Forage Engine v2: where each file goes

Copy into your existing `Battle-Code-UNSW` folder (on the `Forage_Engine` branch) and choose **Replace** when asked.

```
Battle-Code-UNSW/
├── mybot/
│   ├── main.py        REPLACE   sonar wired in; splits ONLY when no legal move exists
│   ├── config.py      REPLACE   new settings (sonar, teammates, tiebreak, feature switches)
│   ├── forage.py      REPLACE   claims, enemy heading, careful mode, long-range, adaptive search
│   ├── memory.py      REPLACE   teammate reports, death detection, exploration blocks
│   ├── symmetry.py    REPLACE   accepts symmetry reports from teammates
│   ├── snapshot.py    REPLACE   release times for fully visible enemy tails
│   ├── routing.py     REPLACE   routes can pass enemy tail cells once they have moved
│   ├── safety.py      REPLACE   portal-to-unseen-tile counts as a last-resort legal move
│   ├── comms.py       NEW       32-bit sonar protocol
│   ├── geometry.py    (unchanged, included for completeness)
│   ├── helper.py      KEEP      (never edit)
│   └── bot.toml       KEEP
├── forage_tests/      REPLACE the folder contents (67 tests + docs)
│   ├── test_comms.py, test_teammates_enemies.py      NEW
│   ├── COMMUNICATION.md                              NEW: how dragons share information
│   ├── ENGINE_FINDINGS.md                            UPDATED
│   ├── latest_results_vs_previous.txt                NEW
│   └── latest_results_vs_oldbot.txt                  NEW
├── tools/             NEW FOLDER
│   └── evaluate.py    automated match testing (all maps, both team orders)
├── probe_bot/main.py  (unchanged; copy mybot's modules next to it if you use it)
└── .gitignore
```

## Commands (repo root)
```
python -m pytest -q forage_tests                 # 67 tests
python tools/evaluate.py mybot oldbot            # every map, both orders
python tools/evaluate.py mybot mybot --set C_D=3 # try a weight change against the current bot
unswbc run --sandbox -v --no-replay maps/default.map mybot mybot > run.txt 2>&1
python forage_tests/sandbox_points.py run.txt    # judge CPU usage (limit 100M per turn)
```

## Commit
```
git add .
git commit -m "Forage Engine v2: emergency-only split, sonar, teammate/enemy modelling"
git push
```
