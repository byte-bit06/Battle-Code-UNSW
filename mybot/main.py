import helper as unswbc
from core import QUEEN, get_role, get_enemy_queen_id, get_safe_directions
from queen_guard import queen_turn, worker_turn

ct: unswbc.Controller
game: unswbc.Game

DEBUG = False  # stdout costs CPU points: keep False for submissions

ROLE = None
ENEMY_QUEEN_ID = None
QUEEN_STATE = {"has_split": False}  # the queen's only memory between turns


def execute_turn() -> None:
    """Algorithm A turn structure (plan Part 5). Until Algorithm B exists,
    the hunter runs worker logic."""
    if ROLE == QUEEN:
        action = queen_turn(ct, game, QUEEN_STATE)
    else:
        action = worker_turn(ct, game)
    if DEBUG:
        kind, value = action
        ct.output_log(ROLE, ct.get_position(), ct.get_dir().value, "len", ct.get_length(),
                      "->", kind, value.value if kind == "move" else value,
                      "safe", "".join(d.value for d in get_safe_directions(ct, game)))


def main() -> None:
    global ct, game, ROLE, ENEMY_QUEEN_ID
    ct, game = unswbc.init()
    ROLE = get_role(ct.get_id(), ct.get_team())
    ENEMY_QUEEN_ID = get_enemy_queen_id(ct.get_team())

    while unswbc.update(ct, game):
        execute_turn()
        unswbc.end_turn()


if __name__ == "__main__":
    main()
