import helper as unswbc
from core import get_role, get_enemy_queen_id, get_safe_directions, get_fallback_move

ct: unswbc.Controller
game: unswbc.Game

DEBUG = False  # stdout costs CPU points: keep False for submissions

ROLE = None
ENEMY_QUEEN_ID = None


def execute_turn() -> None:
    """Stage 0: no strategy yet, only the shared safe-move fallback.
    Algorithm A (queen_guard) and B (queen_hunter) branch on ROLE here."""
    safe_dirs = get_safe_directions(ct, game)
    direction = get_fallback_move(ct, game, safe_dirs)
    if DEBUG:
        ct.output_log(ROLE, ct.get_position(), ct.get_dir().value, "safe", [d.value for d in safe_dirs], "->", direction.value)
    ct.make_move(direction)


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
