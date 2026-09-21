Structure
Rounds and Turns
Each game lasts at most 500 rounds. Within each round, every currently living dragon will perform some number of actions. One of these time steps is known as a turn.

Turns are carried out in ascending order of dragon ID. This means on a given dragon's turn, all dragons with lesser IDs have already acted, and all dragons with greater IDs have not. For more details about the game loop, see Execution Order.

Scoring
Each game has three possible outcomes: team A wins, team B wins, or a draw.

Your team is eliminated when all of your dragons perish. Upon the elimination of any team, the game automatically ends, regardless of the current round number. If exactly one team is eliminated, the other wins. If both teams are eliminated in the same round, the game is a draw. Otherwise, after 500 rounds, the winner is decided by the following tiebreaks in order:

The team with the longest living dragon.
The team with the greatest total length across all of its dragons.
Draw (no winning team decided).

Game Map
Dimensions
Games will be played on maps which are two-dimensional rectangular grids. Both width and height will be between 10 and 64 cells inclusive.

The top left corner will be denoted with coordinates (0, 0), with the x-coordinate increasing towards the right and the y-coordinate increasing down. North is oriented upwards.

Dragons can query the dimensions of the map as follows:

Python
C
C++
Copy Code
width, height = game.get_map_size()
Symmetry
To ensure fairness between teams, each map is guaranteed to be symmetric. This will either be via vertical mirroring, horizontal mirroring, or a 180 degree rotation.

Dragons are not able to easily query the symmetry of the map; that one's up to you!

Topology
The map edges 'wrap around'; specifically, a dragon that moves outside the bounds of the map will find itself on the other side.

On any sort of visual representation of a map, this is denoted by dashed lines running down the east and south borders. Nothing renders on these borders (instead, see their equivalent west and north borders respectively).




R1
A dragon can keep moving right past the east border.
Composition
Maps are composed of tiles and edges. Again, note that edges along the east and north map border are equivalent to their west and north counterparts (as dictated by the wrap-around).

See Pearls for information about certain tiles, and Kelp and Portals for information about nonempty edge types.

Previous
Structure
Next

Pearls
Pearls are the sole resource available, and are used to increase the length of dragons.

Pearl Spawning
Each tile has a countdown which is visible to all dragons which can inspect the tile (see Vision). This countdown represents the number of rounds until said tile next attempts to spawn a pearl. Thus, each round the countdown decrements by 1. Countdowns are decremented at the start of each round, before any dragon moves (see Execution order). When the countdown reaches zero, the tile attempts to spawn a pearl. Regardless of the outcome of this attempt, the countdown resets.

An attempt to spawn a pearl succeeds only when the tile is empty (i.e. no dragon segments nor pearls occupy it).

Resetting the countdown involves drawing uniformly at random from [min_gap, max_gap]. These values are tile-specific properties set on the map, but are not publicly visible to dragons. A tile with max_gap 0 never spawns pearls and always reports a countdown of -1.




R2
The marked tile's countdown reaches zero while it is empty, and so a pearl spawns.
Python
C
C++
Copy Code
soonest = None
for tile in ct.get_tiles():
    if tile.get_pearl_time() < 0:
        continue  # never spawns
    if soonest is None or tile.get_pearl_time() < soonest.get_pearl_time():
        soonest = tile

if soonest is not None:
    where = soonest.get_position()
    ct.set_indicator_string(f"pearl at {where.x},{where.y} in {soonest.get_pearl_time()}")
Symmetric Pearls
On a symmetric map, each tile shares a countdown with its mirror image, so pearls will attempt to spawn symmetrically. Of course, if one of the tiles is blocked when the countdown reaches 0, a pearl will only spawn on the other tile.

Death
When a dragon dies, it will drop half its length in pearls. See Death for more.

Previous
Game Map
Kelp and Portals
Kelp and portals exist on the edges between tiles, not the tiles themselves. This includes the edges along the map border.




R1
This poor dragon travels through a portal, straight into kelp.
Kelp
Kelp is the first type of special edge. Their job is to function as barriers; in particular, a dragon cannot pass from one tile to another across a kelp edge. If it tries, it dies (hit wall) and drops pearls like any other dead dragon.

Kelp is a plant. There are no other special properties of kelp.

Python
C
C++
Copy Code
def is_safe(direction: unswbc.Direction) -> bool:
    here = ct.get_position()
    tile = ct.get_tile(here)
    if tile is None:
        return False

    edge = tile.get_edge(direction)
    if edge.get_edge_type() == unswbc.EdgeType.KELP:
        return False

    ahead = ct.get_tile(here.add_dir(direction))
    return ahead is None or ahead.get_dragon() is None
Portals
Portals are the second type of special edge, and they allow for quick traversal of the map, conditional on your bravery. Each portal has an ID, which is an almost-unique non-negative integer. Exactly one other portal shares the same ID: these two portals are connected.

There are a couple constraints on connected portals. A pair of connected portals are guaranteed to have the same orientation (i.e. both lying along a vertical edge or a horizontal edge). Furthermore, both portals either lie on the map's line of symmetry, or both lie off it. This ensures that each portal maps to exactly one other portal without ambiguity.

Portals are double-sided, so you can enter from either side. Entering a portal from the left causes the head of your dragon to emerge from the right, and vice versa. The corresponding behaviour for vertically oriented portals is left as an exercise for you.

Dragons cannot see through to the other side of portals (see Vision), so it usually won't know what's on the other side.

Sonar travels through portals.

Python
C
C++
Copy Code
edge = tile.get_edge(direction)
if edge.get_edge_type() == unswbc.EdgeType.PORTAL:
    ct.output_log(f"portal {edge.get_portal_id()} to the {direction.value}")
Previous
Pearls
Vision
Every dragon can only see the 7 by 7 square of tiles centred on its head; that is, all 49 tiles with a Chebyshev distance no greater than 3. This vision square wraps around the map as well due to its topology.

Again, note that vision does not extend to the far side of a portal, which is visible only if it is within three tiles of the head by ordinary distance.




R1
A visualisation of a dragon's vision square as it moves. Note the interactions with portals and map borders.
Vision Information
For each tile in view, the dragon receives its (absolute) coordinates, its contents (pearls and dragon parts), its pearl countdown (see Pearls) and its four edges (see Kelp and Portals).

Python
C
C++
Copy Code
tile = ct.get_tile(pos)             # None when pos is outside the window

tile.get_position()                 # board coordinates, already wrapped
tile.get_pearl_time()               # rounds until a pearl spawns here; -1 if never
tile.has_pearl()                    # True if a pearl is on it now

edge = tile.get_edge(unswbc.Direction.NORTH)
edge.get_edge_type()                # EdgeType.EMPTY, EdgeType.KELP or EdgeType.PORTAL
edge.get_portal_id()                # id shared with the partner edge; -1 if not a portal

part = tile.get_dragon()            # None if no dragon is on it
if part is not None:
    part.get_team()                 # Team.A or Team.B
    part.get_id()                   # which dragon
    part.is_head()                  # True for the head
    part.get_dir()                  # head: its heading; body: the way to the head
A turn that steps onto a neighbouring pearl when it can see one, and onto a tile with no dragon on it otherwise:

Python
C
C++
Copy Code
def execute_turn() -> None:
    here = ct.get_position()
    fallback = unswbc.Direction.NORTH

    for direction in unswbc.Direction.get_direction_list():
        tile = ct.get_tile(here.add_dir(direction))
        if tile is None:
            continue
        if tile.has_pearl():
            ct.make_move(direction)
            return
        if tile.get_dragon() is None:
            fallback = direction

    ct.make_move(fallback)
Previous
Kelp and Portals

Movement
Movement is considered a type of action that a dragon can perform on a turn. Note that each dragon must output at least one action per turn (only the last one is actually performed; see Death for a list of death conditions). The only other type of action which can be performed is splitting.

Movement, like all other unit actions, is performed only once the turn is complete.

Standard Movement



R0
Dragons move eastwards.
Each dragon can move one tile in any cardinal direction (north, east, south, west) each turn. This causes the head to move in said direction, with the rest of the body following along.

Dragons can even move backwards, though doing so causes its head to squeeze into its own neck, a move which often proves fatal.

A dragon's facing direction is the direction of its head from its first body (non-head) segment. The facing direction of its body segments is defined similarly (direction to the next segment towards the head).

Python
C
C++
Raw
Copy Code
ct.make_move(unswbc.Direction.EAST)
Eating Pearls



R1
A dragon eats a pearl and grows longer by a unit.
When a dragon moves its head onto a pearl, the pearl is automatically eaten and the tail does not advance that turn. In other words, the dragon grows a body segment.

Eating pearls is the only way to gain length.

Collisions



R0
Everyone dies via various means except the orange dragon.
A dragon dies if its head moves into any obstacles. This includes kelp, any segment of another dragon, or any segment of itself.

Note that this death condition is checked before any actual movement. This means a dragon will die moving into own tail, even if the tail would have moved out of the way in the same turn.

If the destination contains another dragon's head, both dragons die, regardless of their team.

Python
C
C++
Copy Code
ahead = ct.get_tile(here.add_dir(direction))
part = ahead.get_dragon() if ahead is not None else None
if part is not None:
    if part.is_head():
        continue  # both of us would die
    continue      # only I would die
A dragon that dies drops pearls along its body. See Death for more information.

Sprinting



R2
Dragon decides to sprint north + north + east.
Dragons may decide to move several times in one turn in varying directions.

Although all moves happen within a single turn, collision checking (and pearl eating) is performed at every step. This means that in theory, a dragon might die performing NNE, but live with ENN, even though they target the same destination.

Every additional move costs a unit segment of the sprinting dragon. More rigorously, moving x steps in a turn removes x - 1 segments.

Python
C
C++
Raw
Copy Code
ct.make_moves([
    unswbc.Direction.NORTH,
    unswbc.Direction.NORTH,
    unswbc.Direction.EAST,
])
Death by Sprint



R1
Dragon implodes due to oversprinting.
A move with more steps than the dragon can pay for is not truncated. The dragon will perform the steps that can be paid for, and then will pay for the next step with its own life.

Splitting
Splitting is another action that dragons can perform. A dragon can only perform one action per turn.




R2
A length 6 dragon splits. The parent continues east. The child leaves west, head first, from the old tail.
A dragon may split itself to create a new dragon on its team. Note that the minimum length for any dragon is 2. The child consists of the parent's rear segments in reverse order, so the parent's old tail becomes the child's head and the child faces away from the parent.

The child receives the next unused dragon id, and takes its first turn later in the same round. The child is controlled by a brand new instance of your program, and has no memory of the parent.

Constraints
A split is legal only if all of the following hold:

The child has length at least 2. SPLIT 1 is never legal.
The parent has length at least 2 after the split. A dragon of length 6 may split 2, 3 or 4.
The team has fewer than 64 living dragons.
Requesting an illegal split kills the parent with no valid action.

Python
C
C++
Raw
Copy Code
if ct.can_split(2):
    ct.do_split(2)
else:
    ct.make_move(unswbc.Direction.NORTH)
Previous

Sonar
Sending



R1
Two teammates. Each turn the ray leaves the sender and stops at the first body it meets.
Once per turn a dragon may send one unsigned 32-bit integer. After the dragon's action has been applied, if the dragon is still alive, the signal travels in a straight line from its head in the direction it now faces. This signal, wraps around the board and passes through portals, stopping at the first kelp or dragon part it hits. If it hits a dragon, the message is delivered to that dragon, which may be the sender itself. If it reaches no dragon within WIDTH + HEIGHT tiles, it is lost.

Python
C
C++
Raw
Copy Code
ct.send_sonar(1806)

for message in ct.get_sonar_messages():
    ct.output_log(f"heard {message}")
Receiving



R0
The first message reaches our friend, but then an enemy gets in the way and intercepts all our later messages.
Signals are read at the start of the recipient's next turn. A dragon with a higher id than the sender therefore receives the signal later in the same round, and a dragon with a lower id receives it in the following round. Several signals may arrive in one turn, in the order they were sent. A signal is lost if the sender died during its move, since no signal is cast, or if it reached nothing. The replay shows the ray in either case. A signal may be received by a dragon on either team. No information about the sender or team is carried.

Previous
Splitting
Death
A dragon dies when its head collides with something, or when its program fails to produce a valid action on its turn.

Causes of Death
Reason	Cause
Hit Wall	Moved into kelp.
Hit Self	Moved into its own body, including its tail.
Hit Other Body	Moved into a segment of another dragon from any team.
Head to Head	Moved into another dragon's head, causing both dragons to die.
No Valid Action	Requested a sprint it could not pay for, requested an illegal split, produced a malformed command, or outputted no action.
Mandatory Action
The engine treats a turn with no valid action as suicide. Any dragon whose program crashes or outputs nothing (or garbage) will be killed. Dragons which fail to end their turn before the time limit but have outputted at least one valid action will experience a different fate (see Timeouts).

Pearl Dropping
Upon death, dragons exhibit a startling phenomenon: starting from their head, every second body segment crystallises into pearls. A dragon of length L therefore drops ⌈L/2⌉ pearls.




R1
A dragon dies and drops pearls at every second segment.
Previous