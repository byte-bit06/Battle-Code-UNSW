"""Instinct_Engine: defence under coordinated attack (see instinct_engine.md).

state.py       one turn's board as the other modules want it (glue)
tempo.py       turn-order classes, ram exposure
corridors.py   escape connectivity (corridor count)
space.py       timed self-space, stepping our body along a route
policy.py      lexicographic key, trade policy, defensive split
ladder.py      reflex ladder, plan memory

This is the HRL bot's copy, trimmed to what hrlbot calls: control.py and the
analysis-only helpers stay in mybot/instinct/, where the tools and
instinct_tests use them. Every function here maps a board state to a value.
"""
