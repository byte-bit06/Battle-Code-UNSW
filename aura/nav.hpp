#pragma once

#include "board.hpp"

namespace bc {

// Time-aware search on the torus. blk[c] is the earliest move number at which the
// head may enter tile c (0/1 = free now, INF = never within the horizon). Own
// segment i of a body of length L frees after L - i moves, so it gets L - i + 1:
// the engine checks the destination before the tail moves ("tail included").
struct Nav {
    std::vector<int> dist;
    std::vector<int> queue;

    // Distances from start (0 at start). Tiles never reached stay INF.
    void bfs(Board const& b, int start, std::vector<int> const& blk, int horizon) {
        dist.assign(b.NC, INF);
        queue.clear();
        dist[start] = 0;
        queue.push_back(start);
        for (size_t qi = 0; qi < queue.size(); qi++) {
            int c = queue[qi];
            int nd = dist[c] + 1;
            if (nd > horizon) continue;
            for (int d = 0; d < 4; d++) {
                int n = b.nb[c * 4 + d];
                if (n < 0 || dist[n] != INF || blk[n] > nd) continue;
                dist[n] = nd;
                queue.push_back(n);
            }
        }
    }

    // How many tiles the head can reach, stopping once `limit` is hit.
    int flood(Board const& b, int start, std::vector<int> const& blk, int limit) {
        dist.assign(b.NC, INF);
        queue.clear();
        dist[start] = 0;
        queue.push_back(start);
        for (size_t qi = 0; qi < queue.size(); qi++) {
            if (static_cast<int>(queue.size()) >= limit) break;
            int c = queue[qi];
            int nd = dist[c] + 1;
            for (int d = 0; d < 4; d++) {
                int n = b.nb[c * 4 + d];
                if (n < 0 || dist[n] != INF || blk[n] > nd) continue;
                dist[n] = nd;
                queue.push_back(n);
            }
        }
        return static_cast<int>(queue.size()) - 1;  // not counting the head's own tile
    }
};

// Dead-end depth (plan Phase 5): walk on from `start` (entered from `from` on move 1) while
// there is exactly one way on. Returns how many tiles deep the dead end is if the walk ends
// with no way on, or 0 if it reaches a fork (or goes on past `cap`). Time-aware: a tile only
// counts as open if `blk` frees it by the move we would arrive there.
inline int deadEndDepth(Board const& b, int from, int start, std::vector<int> const& blk, int cap) {
    int prev = from, cur = start;
    for (int depth = 0; depth < cap; depth++) {
        int onward = 0, next = -1;
        for (int d = 0; d < 4; d++) {
            int n = b.nb[cur * 4 + d];
            if (n < 0 || n == prev || blk[n] > depth + 2) continue;
            onward++;
            next = n;
        }
        if (onward == 0) return depth + 1;
        if (onward >= 2) return 0;
        prev = cur;
        cur = next;
    }
    return 0;
}

// blk for a body (head first, possibly only a known prefix) of true length L,
// on top of a base grid of other dragons.
inline void markBody(std::vector<int>& blk, std::vector<int> const& body, int L) {
    int n = std::min(static_cast<int>(body.size()), L);
    for (int i = 0; i < n; i++)
        if (body[i] >= 0) blk[body[i]] = std::max(blk[body[i]], L - i + 1);  // -1: crossed a blind portal
}

}  // namespace bc
