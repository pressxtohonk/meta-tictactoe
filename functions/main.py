"""
Serverless backend for a meta tic tac toe app

Expected schema for Real time database: 
{
    // read only
    "users": {
        "uid_1": {
            "name": "goose", 
            "games": {"game_1": true},
            "moves": {"game_1": 1}, // except this, players can update this
        },
        "uid_2": {
            "name": "duck", 
            "games": {"game_1": true},
            "moves": {},
        }
    }
    // read only
    "games": {
        "game_1": {
            "player1": "goose",
            "player2": "duck",
            "grid": [0], // list allows time travel and turn checking using parity
        }
        "game_2": {
            "player1": null,
            "player2": "duck",
            "grid": [0],
        }
    }
}

"""
import dataclasses
from typing import Callable

from firebase_functions import db_fn
from firebase_admin import initialize_app, db
app = initialize_app()


PLAYER1_MOVES = 0b0
PLAYER2_MOVES = 0b0


@dataclasses.dataclass
class Game:
    """Expected data format for a game in RTDB"""
    player1: str
    player2: str
    history: list[int]
    
    replace = dataclasses.replace
    asdict = dataclasses.asdict
    
    @property 
    def odd_turn(self) -> bool:
        return len(self.history) % 2 == 0

def do_move(player: str, move: int) -> Callable[[dict], dict]:
    def update_game(data: dict) -> dict:
        game = Game(**data)
        
        # Validate move
        assert player == (game.player1 if game.odd_turn else game.player2), f"Not {player}'s turn"
        assert move & (PLAYER1_MOVES if game.odd_turn else PLAYER2_MOVES),  f"Not a move ({move=})"
        assert not move & game.history[-1],                                 f"Move already played ({move=})"
        
        # Execute move
        next_grid = move | game.history[-1] 
        next_game = game.replace(history=[*game.history, next_grid])

        return next_game.asdict()
    return update_game

@db_fn.on_value_updated(reference='users/{user}/moves')
def process_user_submitted_moves(event: db_fn.Event[db_fn.Change]): 
    new_games = set(event.data.after).difference(event.data.before)
    new_games = list(new_games) # Deterministic ordering
    
    snapshot = db.reference(f'/users/{event.params["user"]}').get()
    player = dict(snapshot)['name']
    moves = (event.data.after[game] for game in new_games)

    for game, move in zip(new_games, moves):
        update_game = do_move(player=player, move=move)
        game_ref = db.reference(f'games/{game}')
        try:
            game_ref.transaction(update_game)
        except db.TransactionAbortedError as error:
            print(f'Failed to execute move ({player=}, {game=}, {move=}): {error}')

