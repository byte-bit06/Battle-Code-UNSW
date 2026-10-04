#pragma once

#include "common.hpp"

namespace bc {

// One boundary between two tiles. hE[c] is the top edge of tile c, vE[c] its left edge.
struct Edge {
    int8_t kind = 0;      // 0 empty, 1 kelp, 2 portal
    int8_t partnerOrient = -1;  // portal partner: 0 horizontal, 1 vertical, -1 unknown
    int16_t px = -1, py = -1;
    int16_t pid = -1;           // portal id, -1 if not a portal (or not seen yet)
};

struct Board {
    int W = 0, H = 0, NC = 0;
    std::vector<Edge> hE, vE;
    std::vector<int8_t> bed;  // spawns pearls (1), not (0), unknown (-1)
    std::vector<int16_t> gapMin, gapMax;
    std::vector<int> nb;      // nb[c*4+d]: tile after stepping, -1 if blocked/unknown portal
    std::vector<int8_t> portalSide;  // tile has a portal on one of its sides (a landing tile)

    void init(int w, int h) {
        W = w; H = h; NC = w * h;
        hE.assign(NC, Edge{});
        vE.assign(NC, Edge{});
        bed.assign(NC, -1);
        gapMin.assign(NC, 0);
        gapMax.assign(NC, 0);
        rebuild();
    }

    int id(int x, int y) const {
        x %= W; if (x < 0) x += W;
        y %= H; if (y < 0) y += H;
        return y * W + x;
    }
    int X(int c) const { return c % W; }
    int Y(int c) const { return c / W; }

    Edge const& side(int c, int d) const {
        int x = X(c), y = Y(c);
        switch (d) {
        case N: return hE[c];
        case S: return hE[id(x, y + 1)];
        case Dir::W: return vE[c];
        default: return vE[id(x + 1, y)];
        }
    }

    // engine/src/helpers.cc TileAfterStep + TileAfterCrossing.
    int stepRaw(int c, int d) const {
        Edge const& e = side(c, d);
        if (e.kind == 1) return -1;
        if (e.kind == 2) {
            if (e.partnerOrient < 0) return -1;
            if (e.partnerOrient == 0) return id(e.px, d == S ? e.py : e.py - 1);
            return id(d == E ? e.px : e.px - 1, e.py);
        }
        return id(X(c) + DX[d], Y(c) + DY[d]);
    }

    void rebuild() {
        nb.assign(NC * 4, -1);
        portalSide.assign(NC, 0);
        for (int c = 0; c < NC; c++)
            for (int d = 0; d < 4; d++) {
                nb[c * 4 + d] = stepRaw(c, d);
                if (side(c, d).kind == 2) portalSide[c] = 1;
            }
    }

    // Torus Chebyshev distance, cheap "is it near" test.
    int cheb(int a, int b) const {
        int dx = std::abs(X(a) - X(b)), dy = std::abs(Y(a) - Y(b));
        dx = std::min(dx, W - dx);
        dy = std::min(dy, H - dy);
        return std::max(dx, dy);
    }
};

}  // namespace bc
