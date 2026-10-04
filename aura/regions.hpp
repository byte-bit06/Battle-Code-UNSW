#pragma once

#include "board.hpp"

namespace bc {

// Regions for territory play (plan Phase 3a/3b).
//
// The board is cut into size x size blocks, and every block is split again into its connected
// parts (moves that stay inside the block, so a kelp wall through a block makes two regions).
// A region is therefore one connected area: on corridor maps each corridor piece is its own
// region, and the way from one region to another goes through the gaps and portals between
// them (the gateways), which the path fields below follow.
struct Regions {
    int size = 8;
    int count = 0;
    int builtFor = -1;                     // Board::version the regions were built for
    std::vector<int> of;                   // tile -> region id
    std::vector<std::vector<int>> tiles;   // region id -> its tiles

    void build(Board const& b, int blockSize) {
        size = std::max(2, blockSize);
        of.assign(b.NC, -1);
        tiles.clear();
        count = 0;
        std::vector<int> queue;
        for (int c = 0; c < b.NC; c++) {
            if (of[c] >= 0) continue;
            int bx = b.X(c) / size, by = b.Y(c) / size;
            int id = count++;
            tiles.emplace_back();
            queue.assign(1, c);
            of[c] = id;
            for (size_t qi = 0; qi < queue.size(); qi++) {
                int t = queue[qi];
                tiles[id].push_back(t);
                for (int d = 0; d < 4; d++) {
                    int n = b.nb[t * 4 + d];
                    if (n < 0 || of[n] >= 0) continue;
                    if (b.X(n) / size != bx || b.Y(n) / size != by) continue;  // stays in the block
                    // a plain step only: a portal joins regions, it does not merge them
                    if (b.side(t, d).kind == 2) continue;
                    of[n] = id;
                    queue.push_back(n);
                }
            }
        }
        builtFor = b.version;
    }
};

// Path distance over terrain only (kelp blocks, known portals link), ignoring dragons:
// dragons move, terrain does not, and a long-range plan only needs the shape of the map.
// Multi-source: every tile in `sources` starts at 0.
inline void terrainField(Board const& b, std::vector<int> const& sources, std::vector<int>& dist,
                         std::vector<int>& queue) {
    dist.assign(b.NC, INF);
    queue.clear();
    for (int s : sources)
        if (s >= 0 && dist[s] == INF) dist[s] = 0, queue.push_back(s);
    for (size_t qi = 0; qi < queue.size(); qi++) {
        int c = queue[qi];
        for (int d = 0; d < 4; d++) {
            int n = b.nb[c * 4 + d];
            if (n < 0 || dist[n] != INF) continue;
            dist[n] = dist[c] + 1;
            queue.push_back(n);
        }
    }
}

}  // namespace bc
