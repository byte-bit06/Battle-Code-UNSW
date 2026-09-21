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
                
            # Check for Portals in Memory
            exit_pos = portals.get_linked_exit_from_pos(curr, d, ct)
            if exit_pos is not None:
                next_pos = exit_pos.add_dir(d)
            else:
                next_pos = curr.add_dir(d)
                
            if (next_pos.x, next_pos.y) in visited:
                continue
                
            # Check for dragons (only if currently in 7x7 vision)
            next_tile = ct.get_tile(next_pos)
            if next_tile is not None and next_tile.get_dragon() is not None:
                continue
                
            visited.add((next_pos.x, next_pos.y))
            queue.append(next_pos)
            
    return count

