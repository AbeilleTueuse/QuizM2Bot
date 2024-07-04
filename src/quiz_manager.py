import random as rd
from collections import defaultdict
import json
import os

from unidecode import unidecode
from fuzzywuzzy import fuzz
import pandas as pd

from src.data.read_files import GameNames
from src.utils.utils import (
    json_converter,
    format_number_with_sign,
    elo_formula,
    convert_rank,
)


class ConfigurationManager:
    CHECK_ANSWER_PERIOD = 1
    REGISTRATION_TIME = 30
    CHANGE_LANG_TIME = 30
    CLOSE_ANSWSER_MAX_SECOND = 1

    NUMBER_OF_QUESTION = [5, 10, 20, 40]
    FRIENDYLY = "friendly"
    RANKED = "ranked"
    GAME_CATEGORIES = [FRIENDYLY, RANKED]

    HARDCORE = "hardcore"
    MODE = "mode"
    TIME_BETWEEN_HINT = "time_between_hint"
    MAX_HINT = "max_hint"
    DESCRIPTION = "description"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    VERY_PERMISSIVE = "very permissive"

    CONFIG_PATH = os.path.join("src", "config.json")
    LANGS_BY_SERVERS_PATH = os.path.join("src", "data", "langs_by_servers.json")
    LANGS_DATA_PATH = os.path.join("src", "data", "langs_data.json")

    DEFAULT_LANG = "fr"
    EMOJI = "emoji"

    FUZZ_THRESHOLD = {
        STRICT: 100,
        PERMISSIVE: 97,
        VERY_PERMISSIVE: 94,
    }

    def __init__(self):
        self.answer_formatter = None
        self.max_hint = None
        self.time_between_hint = None
        self.fuzz_threshold = 100
        self.langs_by_servers = self._open(self.LANGS_BY_SERVERS_PATH)
        self.saved_config: dict[str, dict[str, str]] = self._open(self.CONFIG_PATH)
        self.langs_data = self._open(self.LANGS_DATA_PATH)
        self.allowed_langs = [self.DEFAULT_LANG]
        self.allowed_players = []

    def _open(self, path) -> dict[str]:
        with open(path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def set_config(self, config_name: str, guild_id: int):
        config = self.saved_config[config_name]

        self.answer_formatter = self._get_answer_formatter(config)
        self.max_hint = config[self.MAX_HINT]
        self.time_between_hint = config[self.TIME_BETWEEN_HINT]
        guild_id = str(guild_id)

        if guild_id in self.langs_by_servers:
            self.allowed_langs = self.langs_by_servers[guild_id]
        else:
            self.allowed_langs = [self.DEFAULT_LANG]

        self.allowed_players = []

    def _get_answer_formatter(self, config: dict):
        mode = config[self.MODE]
        self.fuzz_threshold = self.FUZZ_THRESHOLD[mode]

        if mode == self.STRICT:
            return self._strict

        elif mode == self.PERMISSIVE:
            return self._permissive

        elif mode == self.VERY_PERMISSIVE:
            return self._very_permissive

    def _strict(self, answer: str):
        return answer

    def _permissive(self, answer: str):
        return unidecode(answer.lower())

    def _very_permissive(self, answer: str):
        answer = answer.replace("-", " ")
        formatted_answer = "".join(
            letter
            for letter in self._permissive(answer)
            if letter.isalnum() or letter == " "
        )
        return " ".join(formatted_answer.split())

    def get_default_langs(self, guild_id: int):
        guild_id = str(guild_id)

        if guild_id in self.langs_by_servers:
            return self.langs_by_servers[guild_id]

        return []

    def update_allowed_langs(self, guild_id: int, new_langs: list[str]):
        self.langs_by_servers[str(guild_id)] = new_langs

        with open(self.LANGS_BY_SERVERS_PATH, "w") as file:
            file.write(json.dumps(self.langs_by_servers, indent=4))

    def get_icon(self, lang: str) -> str:
        return self.langs_data[lang][self.EMOJI]

    def get_descriptions(self):
        return (
            config_parameters[self.DESCRIPTION]
            for config_parameters in self.saved_config.values()
        )


class Leaderboard:
    def __init__(self):
        self.scores = defaultdict(int)

    def initialize(self, players_id: list[int]):
        for player_id in players_id:
            self.scores[player_id] = 0

    def increment_score(self, user_id: str):
        self.scores[user_id] += 1

    def sort(self):
        self.scores = dict(
            sorted(self.scores.items(), key=lambda item: item[1], reverse=True)
        )

    def reset(self):
        self.__init__()

    def __iter__(self):
        return iter(self.scores.items())

    def __len__(self):
        return len(self.scores.keys())

    def get_leaderboard(self):
        sorted_players = sorted(self, key=lambda x: x[1], reverse=True)

        lb = []
        current_rank = 1
        current_score = None

        for index, (player_id, score) in enumerate(sorted_players):
            if score != current_score:
                current_rank = index + 1
                current_score = score
            lb.append((convert_rank(current_rank), player_id, score))

        return lb


class EloLeaderboard:
    DATA_PATH = os.path.join("src", "data", "leaderboard.json")
    ELO = "elo"
    NAME = "name"
    DEFAULT_ELO = 1000
    LEADERBOARD_MAX_DISPLAY = 20

    def __init__(self):
        self.data = self._get_data()

    def _get_data(self) -> dict:
        try:
            with open(self.DATA_PATH, "r") as file:
                data = json.load(file, object_hook=json_converter)
        except FileNotFoundError:
            data = {}

        return data

    def get_elo(self, guild_id, player_id, player_name=None):
        if not guild_id in self.data:
            self.data[guild_id] = {}

        if not player_id in self.data[guild_id]:
            self.data[guild_id][player_id] = self.default_info(player_name)

        return self.data[guild_id][player_id][self.ELO]

    def default_info(self, player_name: str):
        return {self.ELO: self.DEFAULT_ELO, self.NAME: player_name}

    def _update_elo(self, guild_id, player_id, new_elo: int):
        self.data[guild_id][player_id][self.ELO] = new_elo

    def calc_and_save_new_elo(self, guild_id: int, leaderboard: Leaderboard):
        current_elo = {
            player_id: self.get_elo(guild_id, player_id) for player_id, _ in leaderboard
        }

        # don't save if only one player
        if len(leaderboard) == 1:
            return {
                player_id: [player_elo, format_number_with_sign(0)]
                for player_id, player_elo in current_elo.items()
            }

        new_elo = {}

        for player_id, player_score in leaderboard:
            player_elo = current_elo[player_id]
            additionnal_elo = sum(
                elo_formula(
                    player_elo, player_score, current_elo[opponent_id], opponent_score
                )
                for opponent_id, opponent_score in leaderboard
                if player_id != opponent_id
            )
            new_elo[player_id] = [
                player_elo + additionnal_elo,
                format_number_with_sign(additionnal_elo),
            ]
            self._update_elo(guild_id, player_id, player_elo + additionnal_elo)

        self._save()

        return new_elo

    def get_player_score(self, players_score: dict, player_id: int) -> tuple[str, int]:
        player_score = players_score[player_id]
        return player_score[self.NAME], player_score[self.ELO]

    def get_leaderboard(self, guild_id: int):
        players_score = self.data[guild_id]
        sorted_players = sorted(
            [
                self.get_player_score(players_score, player_id)
                for player_id in players_score
            ],
            key=lambda item: item[1],
            reverse=True,
        )

        lb = []
        current_rank = 1
        current_score = None

        for index, (player_name, score) in enumerate(sorted_players):
            if index == self.LEADERBOARD_MAX_DISPLAY or score == -1:
                break
            if score != current_score:
                current_rank = index + 1
                current_score = score
            lb.append((convert_rank(current_rank), player_name, score))

        return lb

    def get_player_ranking(self, guild_id: int, user_name: str):
        players_score = self.data[guild_id]
        sorted_players = sorted(
            [
                self.get_player_score(players_score, player_id)
                for player_id in players_score
            ],
            key=lambda item: item[1],
            reverse=True,
        )

        current_rank = 1
        current_score = None

        for index, (player_name, score) in enumerate(sorted_players):
            if score != current_score:
                current_rank = index + 1
                current_score = score

            if player_name == user_name:
                return score, current_rank, len(sorted_players)

        return None

    def _save(self):
        with open(self.DATA_PATH, "w") as file:
            file.write(json.dumps(self.data, indent=4))


class Question:
    def __init__(
        self,
        answers: dict[str, str],
        image_path: str,
        config_manager: ConfigurationManager,
    ):
        self.config_manager = config_manager
        self.answer_formatter = self.config_manager.answer_formatter
        self.answers = self._filter_answer(answers)
        self.image_path = image_path
        self.formatted_answers = self._get_formatted_answers()
        self.hints = self._get_default_hints()
        self.hints_shuffle = self._get_hints_shuffle()
        self.check_answer_count = 0
        self.hint_shown = 0
        self.first_message = None
        self.last_message = None
        self.last_hint_message = None
        self.allowed_players = self.config_manager.allowed_players

    def _filter_answer(self, answers: dict[str, str]):
        return {
            lang: answer
            for lang, answer in answers.items()
            if lang in self.config_manager.allowed_langs
        }

    def _get_formatted_answer(self, answer: str):
        return self.answer_formatter(answer)

    def _get_formatted_answers(self):
        return [self._get_formatted_answer(answer) for answer in self.answers.values()]

    def _get_default_hint(self, answer: str):
        return [
            "\u200B \u200B" if char == " " else "__\u200B \u200B \u200B__"
            for char in answer
        ]

    def _get_default_hints(self):
        return {
            lang: self._get_default_hint(answer)
            for lang, answer in self.answers.items()
        }

    def _get_hint_shuffle(self, answer: str):
        char_position = list(enumerate(answer))
        rd.shuffle(char_position)

        return char_position

    def _get_hints_shuffle(self):
        return {
            lang: self._get_hint_shuffle(answer)
            for lang, answer in self.answers.items()
        }

    def show_hint(self):
        self.check_answer_count += 1

        if self.check_answer_count * self.config_manager.CHECK_ANSWER_PERIOD >= int(
            self.config_manager.time_between_hint
        ):
            self.check_answer_count = 0
            return True

        return False

    def exceed_max_hint(self):
        return self.hint_shown < int(self.config_manager.max_hint)

    def _get_hint(self, lang):
        char_to_show_number = len(self.hints_shuffle[lang]) // (
            int(self.config_manager.max_hint) - self.hint_shown
        )

        for _ in range(char_to_show_number):
            pos, char = self.hints_shuffle[lang].pop()

            if char == " ":
                continue

            if char == "(":
                char = "\("

            self.hints[lang][pos] = f"__{char}__"

    def get_hints(self):
        for lang in self.hints:
            self._get_hint(lang)

        self.hint_shown += 1

    def is_correct_answer(self, user_answer: str):
        formatted_user_answer = self.answer_formatter(user_answer)

        for formatted_answer in self.formatted_answers:
            if (
                fuzz.ratio(formatted_user_answer, formatted_answer)
                >= self.config_manager.fuzz_threshold
            ):
                return True
        return False

    def is_winner(self, message_content: str, author_id: int):
        return (
            not self.allowed_players or author_id in self.allowed_players
        ) and self.is_correct_answer(message_content)


class QuizManager:
    TIME_BETWEEN_QUESTION = 10
    APPEARANCE_PROB = 0.5
    QUESTIONS_PATH = os.path.join("src", "data", "questions.csv")
    IMAGES_PATH = os.path.join("src", "data", "0_images")
    VNUM = "vnum"
    IS_MONSTER = "is_monster"
    IMAGE_NAME1 = "image_name1"
    IMAGE_NAME2 = "image_name2"

    def __init__(self, config_manager: ConfigurationManager):
        self._started = False
        self._waiting_for_answer = False
        self._questions = self._get_questions()
        self.ranked_quiz = False
        self.config_manager = config_manager
        self.leaderboard = Leaderboard()
        self.elo_leaderboard = EloLeaderboard()
        self.game_names = GameNames(config_manager.langs_data)
        self.total_questions = self._questions.shape[0]
        self.multilang_plural = ""

    def _get_questions(self):
        return pd.read_csv(self.QUESTIONS_PATH, sep=",", index_col=[self.VNUM])

    def start_quiz(self):
        self._started = True

        if len(self.config_manager.allowed_langs) >= 2:
            self.multilang_plural = "s"
        else:
            self.multilang_plural = ""

    def quiz_is_running(self):
        return self._started

    def start_question(self):
        self._waiting_for_answer = True

    def waiting_for_answer(self):
        return self._waiting_for_answer

    def get_ingame_names(self, vnum: int, is_monster: int):
        if is_monster:
            names = self.game_names.mob_names
        else:
            names = self.game_names.item_names

        ingame_names: dict[str, str] = names.loc[vnum].to_dict()

        for lang, ig_name in ingame_names.items():
            if ig_name.endswith("+0"):
                ingame_names[lang] = ig_name[:-2]

            ingame_names[lang] = ingame_names[lang].replace(chr(160), " ").strip()

        return ingame_names

    def choose_value(self, row: pd.Series) -> str:
        if pd.isna(row[self.IMAGE_NAME2]):
            return row[self.IMAGE_NAME1]
        else:
            return rd.choice([row[self.IMAGE_NAME1], row[self.IMAGE_NAME2]])

    def get_questions(self, number_of_question: int, max_year: str):
        if max_year == -1:
            questions = self._questions
        else:
            questions = self._questions[self._questions["year"] <= max_year]

        questions = questions.sample(number_of_question)

        questions = [
            Question(
                answers=self.get_ingame_names(vnum, question[self.IS_MONSTER]),
                image_path=os.path.join(self.IMAGES_PATH, self.choose_value(question)),
                config_manager=self.config_manager,
            )
            for vnum, question in questions.iterrows()
        ]

        return questions

    def end_quiz(self):
        self._started = False
        self._waiting_for_answer = False
        self.leaderboard.reset()

    def end_question(self):
        self._waiting_for_answer = False

    def is_ranked_quiz(self, game_category: str):
        is_ranked = game_category == self.config_manager.RANKED
        self.ranked_quiz = is_ranked
        return is_ranked

    def get_elo(self, guild_id: int, player_id: int, player_name: str):
        return self.elo_leaderboard.get_elo(guild_id, player_id, player_name)

    def get_player_ranking(self, guild_id: int, player_name: str):
        return self.elo_leaderboard.get_player_ranking(guild_id, player_name)

    def calc_and_save_new_elo(self, guild_id: int):
        return self.elo_leaderboard.calc_and_save_new_elo(guild_id, self.leaderboard)

    def get_elo_leaderboard(self, guild_id: int):
        return self.elo_leaderboard.get_leaderboard(guild_id)
