import json


def json_converter(obj):
    if isinstance(obj, str):
        try:
            return int(obj)
        except ValueError:
            return obj
    elif isinstance(obj, list):
        return [json_converter(item) for item in obj]
    elif isinstance(obj, dict):
        return {json_converter(key): json_converter(value) for key, value in obj.items()}
    else:
        return obj
    
def format_number_with_sign(number: int):
    return f"+{number}" if number >= 0 else f"{number}"

def elo_formula(player_elo, player_score, opponent_elo, opponent_score):
    score_difference = min(400, player_elo - opponent_elo)
    p_coeff = 1 / (1 + 10 ** (-score_difference / 400))

    if player_score > opponent_score:
        W_coeff = 1
    elif player_score < opponent_score:
        W_coeff = 0
    else:
        W_coeff = 0.5

    return round(20 * (W_coeff - p_coeff))

def convert_rank(rank: int):
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    return f"{rank}e"


def open_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file,  object_hook=json_converter)