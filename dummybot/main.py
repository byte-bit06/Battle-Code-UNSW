import helper as unswbc
from helper import Direction

ct: unswbc.Controller = None

def init(controller):
    global ct
    ct = controller

def execute_turn():
    ct.make_move(Direction.NORTH)
