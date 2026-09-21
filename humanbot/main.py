import helper as unswbc
from helper import Direction, EdgeType
import sys
import time
import os
import traceback

# unswbc strips environment variables in the sandbox, which crashes PyGame when it tries to read PATH
if 'PATH' not in os.environ:
    os.environ['PATH'] = ''

# Hide pygame welcome message so it doesn't corrupt stdout protocol!
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

try:
    import pygame
except ImportError:
    with open("crash_log.txt", "w") as f:
        f.write("pygame is not installed.\n")
    sys.exit(1)

ct: unswbc.Controller = None
game: unswbc.Game = None

CELL_SIZE = 50
GRID_SIZE = 7

screen = None

def init_gui():
    global screen
    pygame.init()
    screen = pygame.display.set_mode((CELL_SIZE * GRID_SIZE, CELL_SIZE * GRID_SIZE))
    pygame.display.set_caption("HumanBot - BattleCode")

def draw_vision():
    if screen is None:
        return
        
    screen.fill((44, 62, 80)) # Background
    
    here = ct.get_position()
    
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            x = (dx + 3) * CELL_SIZE
            y = (dy + 3) * CELL_SIZE
            
            pos = here
            if dx > 0:
                for _ in range(dx): pos = pos.add_dir(Direction.EAST)
            elif dx < 0:
                for _ in range(-dx): pos = pos.add_dir(Direction.WEST)
            
            if dy > 0:
                for _ in range(dy): pos = pos.add_dir(Direction.SOUTH)
            elif dy < 0:
                for _ in range(-dy): pos = pos.add_dir(Direction.NORTH)
                
            tile = ct.get_tile(pos)
            
            # Colors
            if tile is None:
                bg_color = (26, 37, 47) # Out of bounds
            else:
                bg_color = (41, 128, 185) # Water
                
            pygame.draw.rect(screen, bg_color, (x, y, CELL_SIZE, CELL_SIZE))
            pygame.draw.rect(screen, (26, 188, 156), (x, y, CELL_SIZE, CELL_SIZE), 1) # Outline
            
            if tile is None:
                continue
                
            # Draw Kelp / Portals on edges
            edge_n = tile.get_edge(Direction.NORTH).get_edge_type()
            edge_s = tile.get_edge(Direction.SOUTH).get_edge_type()
            edge_e = tile.get_edge(Direction.EAST).get_edge_type()
            edge_w = tile.get_edge(Direction.WEST).get_edge_type()
            
            if edge_n == EdgeType.KELP:
                pygame.draw.line(screen, (39, 174, 96), (x, y), (x + CELL_SIZE, y), 4)
            elif edge_n == EdgeType.PORTAL:
                pygame.draw.line(screen, (155, 89, 182), (x, y), (x + CELL_SIZE, y), 4)
                
            if edge_s == EdgeType.KELP:
                pygame.draw.line(screen, (39, 174, 96), (x, y + CELL_SIZE), (x + CELL_SIZE, y + CELL_SIZE), 4)
            elif edge_s == EdgeType.PORTAL:
                pygame.draw.line(screen, (155, 89, 182), (x, y + CELL_SIZE), (x + CELL_SIZE, y + CELL_SIZE), 4)
                
            if edge_e == EdgeType.KELP:
                pygame.draw.line(screen, (39, 174, 96), (x + CELL_SIZE, y), (x + CELL_SIZE, y + CELL_SIZE), 4)
            elif edge_e == EdgeType.PORTAL:
                pygame.draw.line(screen, (155, 89, 182), (x + CELL_SIZE, y), (x + CELL_SIZE, y + CELL_SIZE), 4)
                
            if edge_w == EdgeType.KELP:
                pygame.draw.line(screen, (39, 174, 96), (x, y), (x, y + CELL_SIZE), 4)
            elif edge_w == EdgeType.PORTAL:
                pygame.draw.line(screen, (155, 89, 182), (x, y), (x, y + CELL_SIZE), 4)
            
            if tile.has_pearl():
                pygame.draw.circle(screen, (241, 196, 15), (x + CELL_SIZE//2, y + CELL_SIZE//2), CELL_SIZE//5)
                pygame.draw.circle(screen, (243, 156, 18), (x + CELL_SIZE//2, y + CELL_SIZE//2), CELL_SIZE//5, 2)
                
            part = tile.get_dragon()
            if part is not None:
                is_me = (part.get_team() == ct.get_team())
                is_head = part.is_head()
                
                if is_me:
                    color = (46, 204, 113) if is_head else (39, 174, 96)
                else:
                    color = (231, 76, 60) if is_head else (192, 57, 43)
                    
                pad = int(CELL_SIZE * 0.15)
                pygame.draw.rect(screen, color, (x + pad, y + pad, CELL_SIZE - 2*pad, CELL_SIZE - 2*pad))
                
                if is_head:
                    pygame.draw.circle(screen, (255, 255, 255), (x + int(CELL_SIZE*0.3), y + int(CELL_SIZE*0.3)), 3)
                    pygame.draw.circle(screen, (255, 255, 255), (x + int(CELL_SIZE*0.7), y + int(CELL_SIZE*0.3)), 3)
                    
                    if dx == 0 and dy == 0:
                        pygame.draw.rect(screen, (241, 196, 15), (x + pad, y + pad, CELL_SIZE - 2*pad, CELL_SIZE - 2*pad), 2)
                        
    pygame.display.flip()

def execute_turn() -> None:
    try:
        if screen is None:
            init_gui()
            
        draw_vision()
        
        chosen_dir = None
        pygame.event.clear()
        
        while chosen_dir is None:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    ct.make_move(Direction.NORTH)
                    return
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_w:
                        chosen_dir = Direction.NORTH
                    elif event.key == pygame.K_s:
                        chosen_dir = Direction.SOUTH
                    elif event.key == pygame.K_a:
                        chosen_dir = Direction.WEST
                    elif event.key == pygame.K_d:
                        chosen_dir = Direction.EAST
                        
            time.sleep(0.02)
            
        ct.make_move(chosen_dir)
    except Exception as e:
        with open("crash_log.txt", "a") as f:
            f.write(f"Exception in execute_turn: {traceback.format_exc()}\n")
        ct.make_move(Direction.NORTH)

def main() -> None:
    global ct, game
    try:
        ct, game = unswbc.init()

        while unswbc.update(ct, game):
            execute_turn()
            unswbc.end_turn()
    except Exception as e:
        with open("crash_log.txt", "a") as f:
            f.write(f"Exception in main: {traceback.format_exc()}\n")

if __name__ == "__main__":
    main()
