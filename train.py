import os
import json
import time
import subprocess
import torch
import torch.nn as nn
import torch.optim as optim
import random
import numpy as np

import sys
sys.path.append('rlbot')
from model import DQN

# Hyperparameters
BATCH_SIZE = 128
GAMMA = 0.99
LR = 1e-4
TARGET_UPDATE = 10
EPSILON_START = 1.0
EPSILON_END = 0.05
EPSILON_DECAY = 50 # Generations

device = torch.device("cpu")

policy_net = DQN().to(device)
target_net = DQN().to(device)
target_net.load_state_dict(policy_net.state_dict())
target_net.eval()

optimizer = optim.Adam(policy_net.parameters(), lr=LR)
criterion = nn.SmoothL1Loss()

MODEL_PATH = "rlbot/model.pth"
EXPERIENCE_LOG = "rl_experiences.jsonl"
EPSILON_FILE = "epsilon.txt"

# If previous model exists, load it
if os.path.exists(MODEL_PATH):
    try:
        policy_net.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))
        target_net.load_state_dict(policy_net.state_dict())
    except:
        pass

replay_buffer = []
MAX_BUFFER = 50000

def train_batch():
    if len(replay_buffer) < BATCH_SIZE:
        return 0.0
        
    batch = random.sample(replay_buffer, BATCH_SIZE)
    
    states = torch.tensor([x["state"] for x in batch], dtype=torch.float32)
    actions = torch.tensor([x["action"] for x in batch], dtype=torch.long).unsqueeze(1)
    rewards = torch.tensor([x["reward"] for x in batch], dtype=torch.float32)
    next_states = torch.tensor([x["next_state"] for x in batch], dtype=torch.float32)
    dones = torch.tensor([x["done"] for x in batch], dtype=torch.float32)
    
    state_action_values = policy_net(states).gather(1, actions).squeeze(1)
    
    with torch.no_grad():
        next_state_values = target_net(next_states).max(1)[0]
    
    expected_state_action_values = rewards + (GAMMA * next_state_values * (1 - dones))
    
    loss = criterion(state_action_values, expected_state_action_values)
    
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    
    return loss.item()

def run_generation(generation, epsilon):
    with open(EPSILON_FILE, "w") as f:
        f.write(str(epsilon))
        
    print(f"\n--- Generation {generation} (Epsilon: {epsilon:.3f}) ---")
    
    if os.path.exists(EXPERIENCE_LOG):
        os.remove(EXPERIENCE_LOG)
        
    print("Running match...")
    start_time = time.time()
    
    # We use subprocess to run the match
    process = subprocess.Popen(
        ["unswbc", "run", "maps/arena.map", "rlbot", "rlbot"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    stdout, stderr = process.communicate()
    
    print(f"Match finished in {time.time() - start_time:.1f}s.")
    
    match_experiences = []
    if os.path.exists(EXPERIENCE_LOG):
        with open(EXPERIENCE_LOG, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        match_experiences.append(json.loads(line))
                    except:
                        pass
                        
    # Parse deaths
    death_ids = set()
    for line in stdout.split("\n"):
        if "died:" in line or "ran out of time" in line:
            parts = line.split("bot ")
            if len(parts) > 1:
                id_part = parts[1].split()[0]
                try:
                    death_ids.add(int(id_part))
                except:
                    pass
                    
    # Reward shaping for terminal states
    last_transitions = {}
    for exp in match_experiences:
        last_transitions[exp["id"]] = exp
        
    for exp in match_experiences:
        if exp["id"] in death_ids and exp is last_transitions[exp["id"]]:
            exp["reward"] = -10.0 # Death penalty
            exp["done"] = True
            
    global replay_buffer
    replay_buffer.extend(match_experiences)
    if len(replay_buffer) > MAX_BUFFER:
        replay_buffer = replay_buffer[-MAX_BUFFER:]
        
    print(f"Collected {len(match_experiences)} transitions. Buffer size: {len(replay_buffer)}")
    
    print("Training model...")
    total_loss = 0
    train_steps = min(50, len(replay_buffer) // BATCH_SIZE + 1)
    if train_steps > 0:
        for _ in range(train_steps):
            total_loss += train_batch()
            
        print(f"Average Loss: {total_loss / train_steps:.4f}")
    
    # Ensure directory exists
    os.makedirs("rlbot", exist_ok=True)
    torch.save(policy_net.state_dict(), MODEL_PATH)

def main():
    generation = 1
    while True:
        if generation < EPSILON_DECAY:
            epsilon = EPSILON_START - (generation / EPSILON_DECAY) * (EPSILON_START - EPSILON_END)
        else:
            epsilon = EPSILON_END
            
        run_generation(generation, epsilon)
        
        if generation % TARGET_UPDATE == 0:
            target_net.load_state_dict(policy_net.state_dict())
            print("Target Network Updated.")
            
        generation += 1

if __name__ == "__main__":
    main()
