import helper as unswbc
from helper import Direction, EdgeType, Position
import heapq

class ToroidalMath:
    @staticmethod
    def distance(p1: Position, p2: Position, width: int, height: int) -> int:
        dx = abs(p1.x - p2.x)
        dx = min(dx, width - dx)
        dy = abs(p1.y - p2.y)
        dy = min(dy, height - dy)
        return dx + dy

class PortalRegistry:
    def __init__(self):
        # portal_id -> list of Positions (max 2)
        self.registry = {}

    def log_portal(self, portal_id: int, pos: Position):
        if portal_id not in self.registry:
            self.registry[portal_id] = []
        
        # Don't add duplicate
        for existing_pos in self.registry[portal_id]:
            if existing_pos.x == pos.x and existing_pos.y == pos.y:
                return False
                
        if len(self.registry[portal_id]) < 2:
            self.registry[portal_id].append(pos)
            return True
        return False
        
    def get_linked_exit(self, portal_id: int, enter_pos: Position) -> Position | None:
        if portal_id in self.registry and len(self.registry[portal_id]) == 2:
            p1, p2 = self.registry[portal_id]
            if p1.x == enter_pos.x and p1.y == enter_pos.y:
                return p2
            if p2.x == enter_pos.x and p2.y == enter_pos.y:
                return p1
        return None
        
    def get_linked_exit_from_pos(self, enter_pos: Position, d: Direction, ct: unswbc.Controller) -> Position | None:
        # Helper to get the exit if stepping in direction `d` from `enter_pos` hits a portal
        tile = ct.get_tile(enter_pos)
        if tile is not None:
            edge = tile.get_edge(d)
            if edge.get_edge_type() == EdgeType.PORTAL:
                pid = edge.get_portal_id()
                return self.get_linked_exit(pid, enter_pos)
        return None
        
    def encode_sonar_message(self, portal_id: int, pos: Position) -> int:
        """
        Encode into 32-bit unsigned int:
        Bits 0-5: Y (6 bits, max 64)
        Bits 6-11: X (6 bits, max 64)
        Bits 12-31: Portal ID (20 bits)
        """
        return (portal_id << 12) | (pos.x << 6) | pos.y
        
    def decode_sonar_message(self, message: int) -> tuple[int, Position]:
        y = message & 0b111111
        x = (message >> 6) & 0b111111
        portal_id = message >> 12
        return portal_id, Position(x, y)

class AStarPathfinder:
    def __init__(self, ct: unswbc.Controller, game: unswbc.Game, portals: PortalRegistry):
        self.ct = ct
        self.game = game
        self.portals = portals
        self.width, self.height = game.get_map_size()

    def find_path(self, start: Position, goal: Position, visited_map: set) -> Direction | None:
        """
        Finds shortest path using Toroidal Manhattan heuristic and known Portals.
        visited_map is the bot's global memory of the map, preventing it from walking 
        into unexplored tiles blindly during strict pathing, but for now we only strictly avoid KELP.
        """
        import itertools
        counter = itertools.count()
        
        # Priority Queue: (f_score, tie_breaker, current_pos, path_of_directions)
        open_set = []
        heapq.heappush(open_set, (0, next(counter), start, []))
        
        closed_set = set()
        closed_set.add((start.x, start.y))
        
        while open_set:
            f_score, _, current_pos, path = heapq.heappop(open_set)
            
            if current_pos.x == goal.x and current_pos.y == goal.y:
                return path[0] if path else None
                
            curr_tile = self.ct.get_tile(current_pos)
            
            for d in Direction.get_direction_list():
                if curr_tile is not None:
                    edge = curr_tile.get_edge(d)
                    if edge.get_edge_type() == EdgeType.KELP:
                        continue
                        
                    # Handle Portals
                    if edge.get_edge_type() == EdgeType.PORTAL:
                        portal_id = edge.get_portal_id()
                        exit_pos = self.portals.get_linked_exit(portal_id, current_pos)
                        if exit_pos is not None:
                            next_pos = exit_pos.add_dir(d)
                        else:
                            continue
                    else:
                        next_pos = current_pos.add_dir(d)
                else:
                    next_pos = current_pos.add_dir(d)
                
                next_tile = self.ct.get_tile(next_pos)
                if next_tile is not None and next_tile.get_dragon() is not None:
                    continue 
                    
                if (next_pos.x, next_pos.y) in closed_set:
                    continue
                    
                closed_set.add((next_pos.x, next_pos.y))
                
                g_score = len(path) + 1
                h_score = ToroidalMath.distance(next_pos, goal, self.width, self.height)
                
                new_path = list(path)
                new_path.append(d)
                
                heapq.heappush(open_set, (g_score + h_score, next(counter), next_pos, new_path))
                
        return None

def calculate_free_space(ct: unswbc.Controller, game: unswbc.Game, start_pos: Position, known_kelp_edges: set, portals: PortalRegistry, limit: int) -> int:
    """
    Flood Fill BFS to count available free tiles up to `limit`.
    Respects persistent Kelp memory and Portals.
    """
    from collections import deque
    queue = deque([start_pos])
    visited = set([(start_pos.x, start_pos.y)])
    count = 0
    
    while queue and count < limit:
        curr = queue.popleft()
        count += 1
        
        for d in Direction.get_direction_list():
            # Check Memory for Kelp
            if ((curr.x, curr.y), d.value) in known_kelp_edges:
                continue
                
            curr_tile = ct.get_tile(curr)
            if curr_tile is not None and curr_tile.get_edge(d).get_edge_type() == EdgeType.KELP:
                continue
                
            # Check for Portals in Memory
            exit_pos = portals.get_linked_exit_from_pos(curr, d, ct)
            if exit_pos is not None:
                next_pos = exit_pos.add_dir(d)
            else:
                next_pos = curr.add_dir(d)
                
            if (next_pos.x, next_pos.y) in visited:
                continue
                
            visited.add((next_pos.x, next_pos.y))
            queue.append(next_pos)
            
    return count

def get_visible_enemy_length(ct: unswbc.Controller, enemy_head_pos: Position) -> tuple[int, bool]:
    """
    Traces an enemy body backward from the head to determine its length.
    Returns (length, fully_visible).
    fully_visible is True if we found the absolute end of the tail inside our 7x7 grid.
    If the tail exits our vision, fully_visible is False.
    """
    length = 1
    curr_pos = enemy_head_pos
    visited = set([(curr_pos.x, curr_pos.y)])
    fully_visible = True
    
    while True:
        found_next = False
        for d in Direction.get_direction_list():
            adj_pos = curr_pos.add_dir(d)
            if (adj_pos.x, adj_pos.y) in visited:
                continue
                
            tile = ct.get_tile(adj_pos)
            if tile is not None:
                part = tile.get_dragon()
                if part is not None and not part.is_head():
                    # Check if this body segment points EXACTLY to our current position
                    # "A body segment faces towards the head"
                    points_to = adj_pos.add_dir(part.get_dir())
                    if points_to.x == curr_pos.x and points_to.y == curr_pos.y:
                        length += 1
                        curr_pos = adj_pos
                        visited.add((curr_pos.x, curr_pos.y))
                        found_next = True
                        break
            else:
                # If a tile adjacent to the body is outside vision, and we haven't confirmed the tail end,
                # it's possible the body continues outside vision.
                pass
                
        if not found_next:
            # We stopped finding body segments. 
            # We need to check if we stopped because the next tile is out of vision.
            # If the current tail piece is adjacent to the edge of our vision, it might continue.
            for d in Direction.get_direction_list():
                if ct.get_tile(curr_pos.add_dir(d)) is None:
                    fully_visible = False
                    break
            break
            
    return length, fully_visible

def get_enemy_release_time(ct: unswbc.Controller, segment_pos: Position) -> int | float:
    """
    Traces an enemy body backward (away from the head) to count segments behind it.
    Returns the exact release time, or float('inf') if the tail exits vision.
    """
    curr_pos = segment_pos
    segments_behind = 0
    visited = set([(curr_pos.x, curr_pos.y)])
    
    while True:
        found_next = False
        for d in Direction.get_direction_list():
            adj_pos = curr_pos.add_dir(d)
            if (adj_pos.x, adj_pos.y) in visited:
                continue
                
            tile = ct.get_tile(adj_pos)
            if tile is not None:
                part = tile.get_dragon()
                if part is not None and not part.is_head():
                    # Does adj_pos face curr_pos? (A body segment faces TOWARDS the head)
                    points_to = adj_pos.add_dir(part.get_dir())
                    if points_to.x == curr_pos.x and points_to.y == curr_pos.y:
                        segments_behind += 1
                        curr_pos = adj_pos
                        visited.add((curr_pos.x, curr_pos.y))
                        found_next = True
                        break
                        
        if not found_next:
            # Check if it exited vision
            for d in Direction.get_direction_list():
                if ct.get_tile(curr_pos.add_dir(d)) is None:
                    return float('inf') # Tail is outside vision
            # Found absolute tail!
            return segments_behind + 1

from collections import deque

def build_reservation_table(ct: unswbc.Controller, body_history: deque) -> dict[tuple[int, int], int]:
    occupied_until = {}
    
    # 1. Populate EXACT release times for our own body using memory
    L = len(body_history)
    for i, pos in enumerate(body_history):
        release_time = L - i
        # Use max() in case the body wraps around or crosses a portal onto itself
        occupied_until[(pos.x, pos.y)] = max(occupied_until.get((pos.x, pos.y), 0), release_time)
        
    # 2. Trace ENEMY segments in 7x7 vision
    for tile in ct.get_tiles():
        pos = tile.get_position()
        part = tile.get_dragon()
        
        if part is not None:
            is_me = (part.get_team() == ct.get_team() and part.get_id() == ct.get_id())
            if not is_me:
                release_time = get_enemy_release_time(ct, pos)
                occupied_until[(pos.x, pos.y)] = max(occupied_until.get((pos.x, pos.y), 0), release_time)
                
    return occupied_until

def get_enemy_threats(ct: unswbc.Controller) -> list[tuple[Position, int]]:
    """
    Phase 3: Gets base threat data for lazy evaluation to save CPU time.
    Returns a list of (head_position, base_sprint_radius).
    """
    threats = []
    for tile in ct.get_tiles():
        part = tile.get_dragon()
        if part is not None and part.is_head() and part.get_team() != ct.get_team():
            e_len, fully_visible = get_visible_enemy_length(ct, part.get_position())
            max_sprint = (e_len - 1) if fully_visible else (e_len + 2)
            threats.append((part.get_position(), max_sprint))
            
    return threats

def check_horizon_survival_dfs(ct: unswbc.Controller, portals: PortalRegistry, start_pos: Position, occupied_until: dict, enemy_threats: list, known_kelp_edges: set, horizon: int, check_timer=None) -> bool:
    """
    Deep DFS to mathematically prove if the bot can survive `horizon` steps into the future.
    It tracks its own future path to ensure it doesn't collide with itself, proving that
    a narrow corridor can actually be escaped.
    """
    # stack: (current_pos, time_step, current_len, path_history_tuple)
    stack = [(start_pos, 1, ct.get_length(), ((start_pos.x, start_pos.y),))]
    evals = 0
    max_evals = 300 # Reduced for extreme performance (still easily covers 100-tile dead ends)
    
    while stack and evals < max_evals:
        curr, time_step, current_len, path_history = stack.pop()
        evals += 1
        if evals % 50 == 0 and check_timer:
            check_timer()
        
        if time_step >= horizon:
            return True
            
        for d in Direction.get_direction_list():
            tile = ct.get_tile(curr)
            if tile is None:
                if ((curr.x, curr.y), d.value) in known_kelp_edges:
                    continue
                next_pos = curr.add_dir(d)
            else:
                edge = tile.get_edge(d)
                if edge.get_edge_type() == EdgeType.KELP:
                    continue
                if edge.get_edge_type() == EdgeType.PORTAL:
                    pid = edge.get_portal_id()
                    exit_pos = portals.get_linked_exit(pid, curr)
                    if exit_pos is not None:
                        next_pos = exit_pos.add_dir(d)
                    else:
                        continue
                else:
                    next_pos = curr.add_dir(d)
                    
            # 1. Check Threat Envelopes (Lazy Evaluation)
            threatened = False
            for e_pos, base_radius in enemy_threats:
                radius = base_radius + (time_step - 1)
                if ToroidalMath.distance(next_pos, e_pos, width, height) <= radius:
                    threatened = True
                    break
            
            if threatened:
                continue
                    
            # 2. Check Past Body (occupied_until)
            if occupied_until.get((next_pos.x, next_pos.y), 0) >= time_step:
                continue
                
            # 3. Check Future Body (path_history)
            blocked_future = False
            check_len = min(current_len, len(path_history))
            for i in range(1, check_len + 1):
                if (next_pos.x, next_pos.y) == path_history[-i]:
                    blocked_future = True
                    break
                    
            if blocked_future:
                continue
                
            # Simulate Pearl Growth
            next_tile = ct.get_tile(next_pos)
            new_len = current_len
            if next_tile is not None and next_tile.has_pearl():
                new_len += 1
                
            new_history = path_history + ((next_pos.x, next_pos.y),)
            stack.append((next_pos, time_step + 1, new_len, new_history))
            
    # If it hits the eval limit without returning False, it has successfully explored
    # a massive open topological area and is considered safe.
    if evals >= max_evals:
        return True
        
    return False

def get_best_action(ct: unswbc.Controller, game: unswbc.Game, portals: PortalRegistry, occupied_until: dict, enemy_threats: list, known_kelp_edges: set, target_pos: Position | None, check_timer=None) -> Direction | None:
    """Phase 4: Lexicographic Action Selector"""
    best_dir = None
    best_score = None
    
    here = ct.get_position()
    my_length = ct.get_length()
    width, height = game.get_map_size()
    
    # Run Space-Time A* to find the target
    astar_dir = None
    if target_pos is not None:
        pathfinder = SpaceTimeAStarPathfinder(ct, game, portals, known_kelp_edges)
        astar_dir = pathfinder.find_path(here, target_pos, occupied_until, max_horizon=8, check_timer=check_timer)
        
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
                
        is_safe = True
        for enemy_d in Direction.get_direction_list():
            adj_to_ahead = ct.get_tile(ahead.get_position().add_dir(enemy_d))
            if adj_to_ahead is not None:
                part = adj_to_ahead.get_dragon()
                if part is not None and part.is_head() and part.get_team() != ct.get_team():
                    e_len, fully_visible = get_visible_enemy_length(ct, part.get_position())
                    true_e_len = e_len if fully_visible else e_len + 3
                    if my_length > true_e_len:
                        is_safe = False
                        break
        
        survives_horizon = check_horizon_survival_dfs(ct, portals, start_pos, occupied_until, enemy_threats, known_kelp_edges, horizon=my_length + 2, check_timer=check_timer)
        
        # Calculate free space (Flood Fill volume) for tie-breaking
        # We use a massive cap to properly evaluate deep kelp mazes and avoid death-traps.
        space_limit = max(100, int(my_length * 2.5))
        space = calculate_free_space(ct, game, start_pos, known_kelp_edges, portals, limit=space_limit)
        
        is_astar_path = (d == astar_dir)
        
        target_utility = 0
        if target_pos is not None:
            dist_before = ToroidalMath.distance(here, target_pos, width, height)
            dist_after = ToroidalMath.distance(start_pos, target_pos, width, height)
            target_utility = dist_before - dist_after
            
        score = (
            is_safe,
            survives_horizon,
            space,
            is_astar_path,
            target_utility
        )
        
        if best_score is None or score > best_score:
            best_score = score
            best_dir = d
            
    return best_dir

class SpaceTimeAStarPathfinder:
    def __init__(self, ct: unswbc.Controller, game: unswbc.Game, portals: PortalRegistry, known_kelp_edges: set):
        self.ct = ct
        self.game = game
        self.portals = portals
        self.known_kelp_edges = known_kelp_edges
        self.width, self.height = game.get_map_size()

    def find_path(self, start: Position, goal: Position, occupied_until: dict[tuple[int, int], int], max_horizon: int = 8, check_timer=None) -> Direction | None:
        """
        Space-Time A* Search. 
        Accounts for exact tail release times and pearl growth.
        """
        import itertools
        import heapq
        counter = itertools.count()
        
        # State: (f_score, tie_breaker, current_pos, time_step, current_length, path)
        open_set = []
        my_length = self.ct.get_length()
        heapq.heappush(open_set, (0, next(counter), start, 0, my_length, []))
        
        # Visited: (x, y, time_step) -> this prevents cyclic loops at the exact same time
        closed_set = set()
        closed_set.add((start.x, start.y, 0))
        evals = 0
        
        while open_set:
            evals += 1
            if evals % 50 == 0 and check_timer:
                check_timer()
                
            f_score, _, current_pos, time_step, current_len, path = heapq.heappop(open_set)
            
            if current_pos.x == goal.x and current_pos.y == goal.y:
                return path[0] if path else None
                
            if time_step >= max_horizon:
                continue
                
            curr_tile = self.ct.get_tile(current_pos)
            
            for d in Direction.get_direction_list():
                if curr_tile is not None:
                    edge = curr_tile.get_edge(d)
                    if edge.get_edge_type() == EdgeType.KELP:
                        continue
                        
                    if edge.get_edge_type() == EdgeType.PORTAL:
                        portal_id = edge.get_portal_id()
                        exit_pos = self.portals.get_linked_exit(portal_id, current_pos)
                        if exit_pos is not None:
                            next_pos = exit_pos.add_dir(d)
                        else:
                            continue
                    else:
                        next_pos = current_pos.add_dir(d)
                else:
                    if ((current_pos.x, current_pos.y), d.value) in self.known_kelp_edges:
                        continue
                    next_pos = current_pos.add_dir(d)
                
                next_time = time_step + 1
                
                # Check Time-Indexed Reservation Table
                release_time = occupied_until.get((next_pos.x, next_pos.y), 0)
                
                # Dynamic Tail Pausing:
                # If we've eaten pearls on this path, our tail release times are delayed.
                # Since enemy bodies are inf, inf + pearls_eaten is still inf.
                pearls_eaten = current_len - my_length
                shifted_release = release_time + pearls_eaten
                
                if shifted_release > next_time:
                    # Tile is still occupied by a body at this time step!
                    continue
                    
                # Did we eat a pearl? If so, our length grows by 1 for future steps on this path.
                next_tile = self.ct.get_tile(next_pos)
                next_len = current_len
                if next_tile is not None and next_tile.has_pearl():
                    next_len += 1
                    
                if (next_pos.x, next_pos.y, next_time) in closed_set:
                    continue
                    
                closed_set.add((next_pos.x, next_pos.y, next_time))
                
                g_score = len(path) + 1
                h_score = ToroidalMath.distance(next_pos, goal, self.width, self.height)
                
                new_path = list(path)
                new_path.append(d)
                
                heapq.heappush(open_set, (g_score + h_score, next(counter), next_pos, next_time, next_len, new_path))
                
        return None

