"""Instinct_Engine: defence under coordinated attack (see instinct_engine.md).

state.py       one turn's board as the other modules want it (glue)
control.py     SHARED with Flood: time-expanded board control D[d][v]
tempo.py       turn-order classes, ram exposure
corridors.py   escape connectivity, cut tiles, chambers
space.py       timed self-space, forced-growth model
policy.py      lexicographic key, trade policy, defensive split
ladder.py      reflex ladder, plan memory

Every function here maps a board state to a value, so the tests drive them
with ASCII fixtures (instinct_tests/boards.py) instead of running a game.
"""
