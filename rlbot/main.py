import helper as unswbc
from helper import Direction, EdgeType
import torch
import random
import os
import json
import numpy as np
import traceback
import sys

# unswbc isolates environment, so fake PATH if missing to prevent PyGame/PyTorch crashes
if 'PATH' not in os.environ:
    os.environ['PATH'] = ''

import model

ct: unswbc.Controller = None
game: unswbc.Game = None

device = torch.device("cpu")
policy_net = model.DQN().to(device)

# Model paths are relative to the root workspace because unswbc runs from root
MODEL_PATH = "rlbot/model.pth"
EXPERIENCE_LOG = "rl_experiences.jsonl"

# Load weights if available
if os.path.exists(MODEL_PATH):
    try:
        policy_net.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))
    except Exception as e:
        pass
policy_net.eval()

last_state_tensor = None
last_action_idx = None
last_length = 0

DIRECTIONS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

# Default Epsilon
epsilon = 0.1
if os.path.exists("epsilon.txt"):
    try:
        with open("epsilon.txt", "r") as f:
            epsilon = float(f.read().strip())
    except:
        pass

def get_state_tensor():
    """Extracts 14-channel 7x7 vision tensor."""
    state = np.zeros((14, 7, 7), dtype=np.float32)
    here = ct.get_position()
    my_team = ct.get_team()
    
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            x_idx = dx + 3
            y_idx = dy + 3
            
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
            if tile is None:
                continue
                
            if tile.has_pearl():
                state[2, y_idx, x_idx] = 1.0
            
            p_time = tile.get_pearl_time()
            if p_time > 0:
                state[3, y_idx, x_idx] = 1.0 / p_time 
                
            for d in Direction.get_direction_list():
                e_type = tile.get_edge(d).get_edge_type()
                if e_type == EdgeType.KELP:
                    state[0, y_idx, x_idx] = 1.0
                elif e_type == EdgeType.PORTAL:
                    state[1, y_idx, x_idx] = 1.0
                    
            part = tile.get_dragon()
            if part is not None:
                is_me = (part.get_team() == my_team)
                is_head = part.is_head()
                
                if part.get_id() == ct.get_id():
                    if is_head: state[4, y_idx, x_idx] = 1.0
                    else: state[5, y_idx, x_idx] = 1.0
                elif is_me:
                    if is_head: state[6, y_idx, x_idx] = 1.0
                    else: state[7, y_idx, x_idx] = 1.0
                else:
                    if is_head: state[8, y_idx, x_idx] = 1.0
                    else: state[9, y_idx, x_idx] = 1.0
                    
                dir_val = part.get_dir().value()
                if dir_val == 'N': state[10, y_idx, x_idx] = 1.0
                elif dir_val == 'E': state[11, y_idx, x_idx] = 1.0
                elif dir_val == 'S': state[12, y_idx, x_idx] = 1.0
                elif dir_val == 'W': state[13, y_idx, x_idx] = 1.0
                
    return state.tolist() 

def log_experience(state, action, reward, next_state):
    try:
        with open(EXPERIENCE_LOG, "a") as f:
            f.write(json.dumps({
                "id": ct.get_id(),
                "state": state,
                "action": action,
                "reward": reward,
                "next_state": next_state,
                "done": False 
            }) + "\n")
    except:
        pass

def execute_turn() -> None:
    global last_state_tensor, last_action_idx, last_length
    
    current_state = get_state_tensor()
    current_length = ct.get_length()
    
    if last_state_tensor is not None:
        reward = 0.1 # Survival reward
        if current_length > last_length:
            reward += 10.0 # Pearl reward!
            
        log_experience(last_state_tensor, last_action_idx, reward, current_state)
        
    if random.random() < epsilon:
        action_idx = random.randint(0, 3)
    else:
        with torch.no_grad():
            state_t = torch.tensor([current_state], dtype=torch.float32).to(device)
            q_values = policy_net(state_t)
            action_idx = q_values.argmax(dim=1).item()
            
    chosen_dir = DIRECTIONS[action_idx]
    
    last_state_tensor = current_state
    last_action_idx = action_idx
    last_length = current_length
    
    ct.make_move(chosen_dir)


def main() -> None:
    global ct, game
    try:
        ct, game = unswbc.init()

        while unswbc.update(ct, game):
            execute_turn()
            unswbc.end_turn()
    except Exception as e:
        with open("crash_log.txt", "a") as f:
            f.write(traceback.format_exc())

if __name__ == "__main__":
    main()
