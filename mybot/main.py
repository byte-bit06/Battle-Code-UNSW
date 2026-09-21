import helper as unswbc
from helper import Direction, EdgeType, Position
import random
import heapq
import itertools

ct: unswbc.Controller
game: unswbc.Game

def get_manhattan_distance(p1: Position, p2: Position, width: int, height: int) -> int:
    """Calculates Manhattan distance on a wrap-around grid."""
    dx = abs(p1.x - p2.x)
    dx = min(dx, width - dx)
    dy = abs(p1.y - p2.y)
    dy = min(dy, height - dy)
    return dx + dy

def a_star_search(start_pos: Position, goal_pos: Position) -> Direction | None:
    """Finds the shortest path to goal_pos using A* and returns the first direction to move."""
    width, height = game.get_map_size()
    
    open_set = []
    counter = itertools.count()
    
    # Store: (f_score, tie_breaker, current_pos, path_of_directions)
    heapq.heappush(open_set, (0, next(counter), start_pos, []))
    
    visited = set()
    visited.add((start_pos.x, start_pos.y))
    
    while open_set:
        f_score, _, current_pos, path = heapq.heappop(open_set)
        
        # Reached the goal!
        if current_pos.x == goal_pos.x and current_pos.y == goal_pos.y:
            return path[0] if path else None
            
        for direction in Direction.get_direction_list():
            curr_tile = ct.get_tile(current_pos)
            if curr_tile is None:
                continue
                
            # Cannot cross kelp
            if curr_tile.get_edge(direction).get_edge_type() == EdgeType.KELP:
                continue
                
            next_pos = current_pos.add_dir(direction)
            if (next_pos.x, next_pos.y) in visited:
                continue
                
            next_tile = ct.get_tile(next_pos)
            if next_tile is None:
                continue # Path is outside our 7x7 vision
                
            # Avoid all dragon parts
            if next_tile.get_dragon() is not None:
                continue
                
            visited.add((next_pos.x, next_pos.y))
            
            g_score = len(path) + 1
            h_score = get_manhattan_distance(next_pos, goal_pos, width, height)
            
            new_path = list(path)
            new_path.append(direction)
            
            heapq.heappush(open_set, (g_score + h_score, next(counter), next_pos, new_path))
            
    return None

def is_safe(direction: Direction) -> bool:
    """Fallback check for safe random moves."""
    here = ct.get_position()
    here_tile = ct.get_tile(here)
    
    if here_tile.get_edge(direction).get_edge_type() == EdgeType.KELP:
        return False
        
    ahead = ct.get_tile(here.add_dir(direction))
    if ahead is None or ahead.get_dragon() is not None:
        return False
        
    return True

def execute_turn() -> None:
    here = ct.get_position()
    
    # Try to split if we are long enough
    if ct.get_length() >= 4:
        child_size = ct.get_length() // 2
        if ct.can_split(child_size):
            ct.output_log(f"Splitting! Spawning child of size {child_size}")
            ct.do_split(child_size)
            return
            
    # Find all pearls in our 7x7 vision
    pearls = []
    for tile in ct.get_tiles():
        if tile.has_pearl():
            pearls.append(tile.get_position())
            
    if pearls:
        # Pick the closest pearl using wrap-around manhattan distance
        width, height = game.get_map_size()
        closest_pearl = min(pearls, key=lambda p: get_manhattan_distance(here, p, width, height))
        
        # Use A* to find the best path to it
        best_direction = a_star_search(here, closest_pearl)
        
        if best_direction is not None:
            ct.output_log(f"A* pathfinding to pearl! Moving {best_direction.value}")
            ct.make_move(best_direction)
            return

    # If no pearls are visible, or they are all unreachable, fallback to a safe random move
    directions = Direction.get_direction_list()
    safe_directions = [d for d in directions if is_safe(d)]
    
    if not safe_directions:
        ct.output_log("No safe moves! Desperate move.")
        ct.make_move(Direction.NORTH)
        return
        
    chosen_dir = random.choice(safe_directions)
    ct.output_log(f"Exploring safely in {chosen_dir.value}")
    ct.make_move(chosen_dir)

def main() -> None:
    global ct, game
    ct, game = unswbc.init()

    while unswbc.update(ct, game):
        execute_turn()
        unswbc.end_turn()

if __name__ == "__main__":
    main()
