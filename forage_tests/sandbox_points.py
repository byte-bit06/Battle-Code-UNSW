"""Summarise CPU-point usage from a judge-sandbox run.

    unswbc run --sandbox -v --no-replay maps/default.map mybot oldbot > run.txt 2>&1
    python forage_tests/sandbox_points.py run.txt [A|B]

The judge gives each turn 100,000,000 points; exceeding it kills the dragon.
A process's first turn also pays module-import cost (~40M points).
"""
import re
import sys


def main(path, team="A"):
    seen, normal, first, deaths = set(), [], [], []
    pat = re.compile(r"round (\d+): bot (\d+) \(team " + team + r"\) points (\d+)")
    for line in open(path, errors="replace"):
        m = pat.match(line)
        if m:
            bot, pts = int(m.group(2)), int(m.group(3))
            (normal if bot in seen else first).append(pts)
            seen.add(bot)
        elif f"(team {team})" in line and ("exceeded CPU" in line or "no valid action" in line):
            deaths.append(line.strip())
    for name, xs in (("normal turns", normal), ("first turns", first)):
        if not xs:
            continue
        xs.sort()
        n = len(xs)
        print(f"{name:13s} n={n:5d}  p50={xs[n // 2] / 1e6:5.1f}M  p95={xs[int(n * .95)] / 1e6:5.1f}M  "
              f"p99={xs[min(n - 1, int(n * .99))] / 1e6:5.1f}M  max={xs[-1] / 1e6:5.1f}M  (limit 100M)")
    print(f"CPU-limit / no-valid-action deaths: {len(deaths)}")
    for d in deaths[:10]:
        print("  ", d)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "A")
