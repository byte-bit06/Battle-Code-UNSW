import helper as unswbc
from helper import Direction, EdgeType, Position
import random

from engine import ToroidalMath, PortalRegistry, AStarPathfinder, calculate_free_space

ct: unswbc.Controller = None
game: unswbc.Game = None
portals = PortalRegistry()
pathfinder: AStarPathfinder = None

# Local Memory of visited coordinates
visited_coords = set()
known_kelp_edges = set()

from collections import deque
body_history = deque()

def update_body_memory(ct, body_history: deque):
    """
    Call this immediately at the start of the turn.
    """
    head_pos = ct.get_position()
    current_len = ct.get_length()
    
    # Add new head position
    body_history.appendleft(head_pos)
    
    # Trim the tail to match our actual length
    while len(body_history) > current_len:
        body_history.pop()

def scan_vision_and_sync():
    """Scans the 7x7 vision, updates memory, and parses/sends Sonar messages."""
    here = ct.get_position()
    
    # 1. Parse incoming Sonar messages to sync Portals
    for msg in ct.get_sonar_messages():
        portal_id, pos = portals.decode_sonar_message(msg)
        portals.log_portal(portal_id, pos)
        
    # 2. Scan Vision for unvisited tiles, kelp, and new portals
    for tile in ct.get_tiles():
        pos = tile.get_position()
        visited_coords.add((pos.x, pos.y))
        
        # Check edges for portals and kelp
        for d in Direction.get_direction_list():
            edge = tile.get_edge(d)
            if edge.get_edge_type() == EdgeType.PORTAL:
                portal_id = edge.get_portal_id()
                # If it's a newly discovered portal, ping the swarm
                if portals.log_portal(portal_id, pos):
                    msg = portals.encode_sonar_message(portal_id, pos)
                    ct.send_sonar(msg)
            elif edge.get_edge_type() == EdgeType.KELP:
                known_kelp_edges.add(((pos.x, pos.y), d.value))

def draw_visual_memory():
    """Draws dots to represent the bot's local memory (Section 2.5)."""
    # Draw Green dots on all visited coordinates
    for (x, y) in visited_coords:
        ct.draw_indicator_dot(Position(x, y), 0, 255, 0)
        
    # Draw Blue dots on discovered portals
    for portal_id, positions in portals.registry.items():
        for pos in positions:
            ct.draw_indicator_dot(pos, 0, 0, 255)

def is_safe(direction: Direction) -> bool:
    """Strict Safe Movement Validator + Flood Fill (Stage 2.5)."""
    here = ct.get_position()
    tile = ct.get_tile(here)
    
    # 1. Check immediate obstacles
    if tile.get_edge(direction).get_edge_type() == EdgeType.KELP:
        return False
        
    ahead = ct.get_tile(here.add_dir(direction))
    if ahead is None:
        return False
        
    if ahead.get_dragon() is not None:
        return False
        
    # 2. Flood Fill BFS (Trap Avoidance)
    # The starting tile for BFS is where we emerge after stepping
    start_pos = here.add_dir(direction)
    # Handle portal jump logic for the BFS start
    if tile.get_edge(direction).get_edge_type() == EdgeType.PORTAL:
        pid = tile.get_edge(direction).get_portal_id()
        exit_pos = portals.get_linked_exit(pid, here)
        if exit_pos is not None:
            start_pos = exit_pos.add_dir(direction)
            
    my_length = ct.get_length()
    free_space = calculate_free_space(ct, game, start_pos, known_kelp_edges, portals, limit=my_length)
    
    return free_space >= my_length
    
def dump_memory_to_file():
    """Dumps a comprehensive audit of the bot's memory to a unique text file."""
    # Write to a bot-specific file to prevent bots from overwriting each other
    filename = f"memory_audit_bot_{ct.get_id()}.txt"
    try:
        with open(filename, "w") as f:
            f.write(f"=== BOT {ct.get_id()} (Team {ct.get_team().name}) MEMORY AUDIT ===\n")
            f.write(f"Round: {game.get_round_num()}\n")
            f.write(f"Current Position: ({ct.get_position().x}, {ct.get_position().y})\n")
            f.write(f"Current Length: {ct.get_length()}\n")
            
            width, height = game.get_map_size()
            total_tiles = width * height
            percent = (len(visited_coords) / total_tiles) * 100
            f.write(f"Map Exploration: {len(visited_coords)} / {total_tiles} tiles explored ({percent:.1f}%).\n")
            
            f.write("\n--- DISCOVERED PORTALS ---\n")
            if not portals.registry:
                f.write("None\n")
            for pid, positions in portals.registry.items():
                f.write(f"Portal ID {pid}: {[f'({p.x}, {p.y})' for p in positions]}\n")
                
            f.write("\n--- VISITED COORDINATES (Grouped by Row) ---\n")
            sorted_coords = sorted(list(visited_coords))
            
            from collections import defaultdict
            coords_by_y = defaultdict(list)
            for x, y in sorted_coords:
                coords_by_y[y].append(x)
                
            for y in sorted(coords_by_y.keys()):
                f.write(f"Row {y:02d} -> X: {coords_by_y[y]}\n")
                
    except Exception:
        pass

import time

class TimeoutInterrupt(Exception):
    pass

def check_timer(start_time, limit):
    if time.perf_counter() - start_time > limit:
        raise TimeoutInterrupt()

from engine import get_visible_enemy_length, build_reservation_table, get_enemy_threats, get_best_action

def get_immediate_safe_move() -> Direction:
    """Level 1 Failsafe: Returns a guaranteed safe 1-step move."""
    here = ct.get_position()
    my_length = ct.get_length()
    
    best_dir = Direction.NORTH
    max_space = -1
    
    head_dragon = ct.get_tile(here).get_dragon() if ct.get_tile(here) else None
    opp_dir = None
    if head_dragon:
        curr_dir = head_dragon.get_dir()
        if curr_dir == Direction.NORTH: opp_dir = Direction.SOUTH
        elif curr_dir == Direction.SOUTH: opp_dir = Direction.NORTH
        elif curr_dir == Direction.EAST: opp_dir = Direction.WEST
        elif curr_dir == Direction.WEST: opp_dir = Direction.EAST
        
    for d in Direction.get_direction_list():
        if d == opp_dir:
            continue
            
        # Hard Legality Check
        if ct.get_tile(here).get_edge(d).get_edge_type() == EdgeType.KELP:
            continue
            
        ahead = ct.get_tile(here.add_dir(d))
        if ahead is None or ahead.get_dragon() is not None:
            continue
            
        # Avoid stepping into tiles threatened by smaller enemy heads
        is_safe_from_heads = True
        for enemy_d in Direction.get_direction_list():
            adj_to_ahead = ct.get_tile(ahead.get_position().add_dir(enemy_d))
            if adj_to_ahead is not None:
                part = adj_to_ahead.get_dragon()
                if part is not None and part.is_head() and part.get_team() != ct.get_team():
                    e_len, fully_visible = get_visible_enemy_length(ct, part.get_position())
                    
                    # Binary Certainty Logic
                    true_e_len = e_len if fully_visible else e_len + 3
                    
                    if my_length > true_e_len:
                        is_safe_from_heads = False
                        break
                        
        if not is_safe_from_heads:
            continue
            
        start_pos = here.add_dir(d)
        space = calculate_free_space(ct, game, start_pos, known_kelp_edges, portals, limit=my_length)
        if space > max_space:
            max_space = space
            best_dir = d
            
    return best_dir

def execute_turn() -> None:
    START_TIME = time.perf_counter()
    TIME_LIMIT = 0.040 # 40ms strict limit
    
    here = ct.get_position()
    
    # Update map memory and sync portals via Sonar
    update_body_memory(ct, body_history)
    scan_vision_and_sync()
    draw_visual_memory()
    dump_memory_to_file()
    
    # 1. Level 1 Failsafe
    fallback_move = get_immediate_safe_move()
    
    try:
        check_timer(START_TIME, TIME_LIMIT)
        
        # Phase 2: Reservation Table
        occupied_until = build_reservation_table(ct, body_history)
        
        # Phase 3: Threat Envelopes (Lazy Evaluation)
        enemy_threats = get_enemy_threats(ct)
        
        check_timer(START_TIME, TIME_LIMIT)
        
        # Calculate target for Phase 4 (Foraging or Survival Coil)
        target_pos = None
        state_name = ""
        width, height = game.get_map_size()
        visible_pearls = [tile.get_position() for tile in ct.get_tiles() if tile.has_pearl()]
        if visible_pearls:
            state_name = "Foraging"
            target_pos = min(visible_pearls, key=lambda p: ToroidalMath.distance(here, p, width, height))
        else:
            state_name = "Survival Coil"
            target_pos = body_history[-1] if body_history else here
            
        # Define local check_timer closure
        def run_check_timer():
            check_timer(START_TIME, TIME_LIMIT)
            
        # Phase 4: Lexicographic FSM
        best_dir = get_best_action(ct, game, portals, occupied_until, enemy_threats, known_kelp_edges, target_pos, check_timer=run_check_timer)
        
        if best_dir is None:
            best_dir = fallback_move
            state_name = "Defense (Fallback)"
            
        check_timer(START_TIME, TIME_LIMIT)
        ct.output_log(f"[{state_name}] Moving {best_dir.value}")
        ct.make_move(best_dir)
        
    except TimeoutInterrupt:
        ct.output_log("[TIMEOUT PANIC] Yielding Level 1 Failsafe")
        ct.make_move(fallback_move)

def main() -> None:
    global ct, game, pathfinder
    ct, game = unswbc.init()
    pathfinder = AStarPathfinder(ct, game, portals)

    while unswbc.update(ct, game):
        execute_turn()
        unswbc.end_turn()

if __name__ == "__main__":
    main()
