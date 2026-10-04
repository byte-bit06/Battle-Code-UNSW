"""Read-only helper for the contest API (https://game.battlecode.au/docs/api).

Uses the key stored by `unswbc auth set` (never printed). Signed redirects (replay and zip
downloads) are followed without sending the key to the storage host.
"""
import json
import urllib.request

from unswbc import api, auth


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_OPENER = urllib.request.build_opener(_NoAuthOnRedirect)


def open_path(path: str):
    """GET /api/v1/<path>; returns the open response."""
    key = auth.key()
    if not key:
        raise SystemExit("no API key: run `unswbc auth set bc_...` first")
    req = urllib.request.Request(api.url(path))
    req.add_unredirected_header("Authorization", f"Bearer {key}")
    req.add_header("User-Agent", "mr-aura-tools")
    req.add_header("Origin", api.server())
    return _OPENER.open(req, timeout=120)


def get_json(path: str):
    with open_path(path) as r:
        return json.loads(r.read())


def get_bytes(path: str) -> bytes:
    with open_path(path) as r:
        return r.read()
