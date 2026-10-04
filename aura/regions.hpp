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

// 1-wide corridors (plan Phase 5): chains of tiles with at most two ways on (by terrain:
// kelp and known portals), at least `minLen` long. A corridor's id is its lowest tile index,
// which every dragon that knows the same terrain computes the same way.
struct Corridors {
    int builtFor = -1;
    std::vector<int> of;   // tile -> corridor id (lowest tile index in it), -1 not in a corridor

    void build(Board const& b, int minLen) {
        of.assign(b.NC, -1);
        std::vector<int> deg(b.NC, 0);
        for (int c = 0; c < b.NC; c++)
            for (int d = 0; d < 4; d++) deg[c] += b.nb[c * 4 + d] >= 0;
        std::vector<char> done(b.NC, 0);
        std::vector<int> comp;
        for (int c = 0; c < b.NC; c++) {
            if (done[c] || deg[c] > 2 || deg[c] == 0) continue;
            comp.assign(1, c);
            done[c] = 1;
            for (size_t qi = 0; qi < comp.size(); qi++)
                for (int d = 0; d < 4; d++) {
                    int n = b.nb[comp[qi] * 4 + d];
                    if (n >= 0 && !done[n] && deg[n] <= 2 && deg[n] > 0) done[n] = 1, comp.push_back(n);
                }
            if (static_cast<int>(comp.size()) < minLen) continue;
            int id = *std::min_element(comp.begin(), comp.end());
            for (int t : comp) of[t] = id;
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
