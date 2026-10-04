# Battlecode Abyss Framework

An open C++ bot framework for [UNSW Battlecode 2026 "Abyss"](https://battlecode.au/unsw),
shared to help new teams get started fast. [中文说明见下方](#中文说明)

## Why we are sharing this

We are **Cat's paradise**, a team taking part in UNSW Battlecode 2026. Before any real strategy work can start,
every bot needs the same plumbing: parsing the protocol, mapping a torus full of kelp and
portals, tracking your own body, learning where pearls spawn, path-finding, and staying inside
the CPU budget. That took us days. We are sharing the framework of one of our earlier bots so
that new teams can skip that part, get a working bot onto the ladder quickly, climb from there,
and spend their time on their own ideas.

- **Not our current bot.** This is the code of an earlier submission of ours, released as a framework.
- **Untuned.** Every tuned parameter has been reset to a plain hand-set starting value
  (`Params` in `common.hpp`).
- **Bot only.** No tools, data or experiment results are included.

## What is inside

A complete bot in C++17 using only the standard library (no toolkit helper needed). In our
tests it beat the starter bot in all 22 games (11 maps, both sides) and never timed out: it
searches for up to 75M of the 100M CPU points each turn and stays below 80M.

| File | What it does |
| --- | --- |
| `main.cpp` | Turn loop: read, update the world, decide, write everything in one go |
| `io.hpp` | Protocol parser and a single-write output buffer (every write costs CPU points) |
| `board.hpp` | Torus board: kelp walls, portal pairs, neighbour table, distances |
| `world.hpp` | What one dragon knows, all learnt from vision: terrain, portals, pearl beds and their countdowns, refill gaps, its own body, other dragons |
| `nav.hpp` | Time-aware BFS and flood fill: your own tail frees tiles as you move |
| `policy.hpp` | Decisions: pearl values, safety (room, pockets, enemy heads, blind portals), roles (growers and swarm), squads, head-on and sprint trades, splitting, end-game feeding, and an anytime lookahead that deepens while the CPU budget lasts |
| `common.hpp` | Every tunable number (`Params`) and the per-turn CPU budget |

## Quick start

1. Install the toolkit (`uv tool install unswbc`) and follow the official quickstart until
   `unswbc run` works.
2. In your unswbc workspace (the folder that holds `maps/`), clone this repository as a bot folder:
   ```bash
   git clone https://github.com/SongyuQi-Francisco/battlecode-abyss-framework.git abyss
   ```
3. Play it against the starter bot (`unswbc init cpp starter` creates one):
   ```bash
   unswbc run maps/arena.map abyss starter
   ```
   Add `--sandbox` to meter CPU exactly like the judge. Replays open in the VS Code viewer
   (`unswbc vscode`) or at https://game.battlecode.au.
4. Make it your own, then submit: `unswbc submit abyss -n <version> -d "<what changed>"`.

Tips:

- Per-turn debug lines: add `#define BC_DEBUG` at the top of `common.hpp`. Keep it off for
  submissions, logging costs CPU.
- `BC_TURN_BUDGET` in `common.hpp` sets how long the lookahead may search each turn (0.075 s of
  the judge's virtual clock = 75M of the 100M points).
- `unswbc run --sandbox` reuses a cached build unless a `.cpp` file changed. After editing only
  headers, delete `~/.cache/unswbc/wasmbots/<bot>-*.wasm` (or touch `main.cpp`).

## Where to take it

- `Params` are untuned starting values: tuning them is the easiest first gain.
- Everything else (scoring, roles, the search) is yours to change or rewrite.

## Fair play

The competition terms say submissions must be your team's own work. Use this as a reference to
learn from and build on, and ask the organisers if you are unsure what is allowed. The code is
provided as is: no support, and this repository may not be updated.

---

## 中文说明

**为什么开源：** 我们是参加 UNSW Battlecode 2026 "Abyss" 的队伍 **Cat's paradise**。任何 bot 在开始写策略之前，
都要先搭好同一套基础设施：解析通信协议、在布满海藻墙和传送门的环形地图上建图、追踪自己的身体、
学习珍珠刷新点、寻路、控制每回合的 CPU 预算。这些花了我们好几天。我们把早期一版 bot 的代码框架
开源出来，希望帮助刚加入比赛的新队伍跳过这一步，尽快让一个能跑的 bot 上天梯、把分数提上去，
把时间花在自己的想法上。

- **不是我们现在的 bot：** 这是我们早期一次提交的代码，作为框架公开。
- **未经调参：** 所有调优过的参数都已重置为手工设定的初始值（`common.hpp` 里的 `Params`）。
- **只有 bot 代码：** 不包含任何工具、数据或实验结果。

**内容：** 一个完整的 C++17 bot，只用标准库（不需要工具包的 helper）。我们测试中它对 starter bot
22 局全胜（11 张图、双方各一次），从未超时：每回合搜索最多用 100M CPU 点中的 75M，峰值低于 80M。各文件作用见上方表格：
`io.hpp` 协议解析；`board.hpp` 环形棋盘、海藻墙、传送门；`world.hpp` 由视野学习到的世界模型；
`nav.hpp` 考虑身体随时间让出格子的 BFS；`policy.hpp` 决策（珍珠价值、安全、角色分工、小队、
换头与冲刺换头、分裂、终局喂食、按 CPU 预算逐层加深的前瞻搜索）；`common.hpp` 全部可调参数。

**快速上手：**

1. 安装工具包（`uv tool install unswbc`），按官方 quickstart 配置到 `unswbc run` 可用。
2. 在 unswbc 工作目录（有 `maps/` 的文件夹）里把本仓库克隆成一个 bot 文件夹：
   `git clone https://github.com/SongyuQi-Francisco/battlecode-abyss-framework.git abyss`
3. 和 starter 对战：`unswbc run maps/arena.map abyss starter`（加 `--sandbox` 按 judge 的方式计 CPU）。
4. 改成你们自己的版本后提交：`unswbc submit abyss -n <版本> -d "<改动说明>"`。

**小提示：** 在 `common.hpp` 顶部加 `#define BC_DEBUG` 可输出每回合调试日志（提交前关掉，日志耗 CPU）；
`BC_TURN_BUDGET` 控制每回合前瞻搜索的时间；`--sandbox` 只在 `.cpp` 变化时重新编译，只改了头文件时
请删除 `~/.cache/unswbc/wasmbots/<bot>-*.wasm`（或 touch 一下 `main.cpp`）。

**下一步：** `Params` 都是未调参的初始值，调参是最容易的第一步提升；评分、角色、搜索等一切都可以改写。

**公平竞赛：** 比赛条款要求提交的必须是本队自己的作品。请把本仓库当作学习和二次开发的参考；
不确定是否允许时请先询问主办方。代码按原样提供，不提供支持，也可能不再更新。

---

## License

MIT License

Copyright (c) 2026 Cat's paradise

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
