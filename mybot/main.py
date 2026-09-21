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

def get_furthest_unvisited() -> Position:
    """Finds the furthest unvisited coordinate for the Exploration State."""
    width, height = game.get_map_size()
    here = ct.get_position()
    
    furthest_dist = -1
    furthest_pos = here
    
    # We sample a grid of points to find an unvisited one
    for y in range(height):
        for x in range(width):
            if (x, y) not in visited_coords:
                dist = ToroidalMath.distance(here, Position(x, y), width, height)
                if dist > furthest_dist:
                    furthest_dist = dist
                    furthest_pos = Position(x, y)
                    
    return furthest_pos

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

def execute_turn() -> None:
    here = ct.get_position()
    
    # Update map memory and sync portals via Sonar
    scan_vision_and_sync()
    
    # Draw developer visual debugging
    draw_visual_memory()
    
    # Dump memory to file for the user to read
    dump_memory_to_file()
    
    # Find all pearls in vision
    visible_pearls = []
    for tile in ct.get_tiles():
        if tile.has_pearl():
            visible_pearls.append(tile.get_position())
            
    chosen_dir = None
    target_pos = None
    state_name = ""
    
    if visible_pearls:
        # FORAGING STATE (Basic implementation for testing Stage 1 Engine)
        state_name = "Foraging"
        width, height = game.get_map_size()
        target_pos = min(visible_pearls, key=lambda p: ToroidalMath.distance(here, p, width, height))
        chosen_dir = pathfinder.find_path(here, target_pos, visited_coords)
    else:
        # EXPLORATION STATE (Section 2.4)
        state_name = "Exploration"
        target_pos = get_furthest_unvisited()
        chosen_dir = pathfinder.find_path(here, target_pos, visited_coords)
        
    # Visual Debugger: Draw Red line to target
    if target_pos is not None:
        ct.draw_indicator_line(here, target_pos, 255, 0, 0)
        
    # Fallback if pathfinding fails or returns unsafe move
    if chosen_dir is None or not is_safe(chosen_dir):
        state_name = "Defense (Fallback)"
        safe_dirs = [d for d in Direction.get_direction_list() if is_safe(d)]
        if safe_dirs:
            chosen_dir = random.choice(safe_dirs)
        else:
            # Fatal trap: All paths lead to an area smaller than our length.
            # Pick the path that buys us the most time (max free space).
            best_dir = Direction.NORTH
            max_space = -1
            
            for d in Direction.get_direction_list():
                # Don't step into kelp or dragon immediately
                if ct.get_tile(here).get_edge(d).get_edge_type() == EdgeType.KELP:
                    continue
                ahead = ct.get_tile(here.add_dir(d))
                if ahead is None or ahead.get_dragon() is not None:
                    continue
                    
                start_pos = here.add_dir(d)
                if ct.get_tile(here).get_edge(d).get_edge_type() == EdgeType.PORTAL:
                    pid = ct.get_tile(here).get_edge(d).get_portal_id()
                    exit_pos = portals.get_linked_exit(pid, here)
                    if exit_pos is not None:
                        start_pos = exit_pos.add_dir(d)
                        
                space = calculate_free_space(ct, game, start_pos, known_kelp_edges, portals, limit=9999)
                if space > max_space:
                    max_space = space
                    best_dir = d
            
            chosen_dir = best_dir
            
    ct.output_log(f"[{state_name}] Moving {chosen_dir.value}")
    ct.make_move(chosen_dir)

def main() -> None:
    global ct, game, pathfinder
    ct, game = unswbc.init()
    pathfinder = AStarPathfinder(ct, game, portals)

    while unswbc.update(ct, game):
        execute_turn()
        unswbc.end_turn()

if __name__ == "__main__":
    main()
