import random as rd
from collections import defaultdict
import json
import os

from fuzzywuzzy import fuzz
import pandas as pd
import nextcord

from src.data.read_files import GameNames
from src.utils.utils import (
    format_number_with_sign,
    elo_formula,
    convert_rank,
    open_json,
)
from src.config import ConfigurationManager as cm
from src.paths import IMAGES_PATH, QUESTIONS_PATH, LEADERBOARD_PATH


class Leaderboard:
    def __init__(self):
        self.scores = defaultdict(int)

    def initialize(self, players: dict):
        for player_id in players:
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
    ELO = "elo"
    NAME = "name"
    DEFAULT_ELO = 1000
    LEADERBOARD_MAX_DISPLAY = 20

    def __init__(self):
        self._data = self._get_data()

    def _get_data(self) -> dict:
        if os.path.exists(LEADERBOARD_PATH):
            return open_json(LEADERBOARD_PATH)

        return {}

    def get_elo(self, guild_id, player_id, player_name=None):
        if not guild_id in self._data:
            self._data[guild_id] = {}

        if not player_id in self._data[guild_id]:
            self._data[guild_id][player_id] = self.default_info(player_name)
            return self.DEFAULT_ELO

        if self.ELO in self._data[guild_id][player_id]:
            return self._data[guild_id][player_id][self.ELO]

        return self.DEFAULT_ELO

    def default_info(self, player_name: str):
        return {self.NAME: player_name}

    def _update_elo(self, guild_id, player_id, new_elo: int):
        self._data[guild_id][player_id][self.ELO] = new_elo

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

    def get_leaderboard(self, guild_id: int):
        players_score: dict[int, dict] = self._data[guild_id]
        valid_scores = (
            (player_score[self.NAME], player_score[self.ELO])
            for player_score in players_score.values()
            if self.ELO in player_score
        )
        sorted_players = sorted(valid_scores, key=lambda score: score[1], reverse=True)

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
        players_score: dict[int, dict] = self._data[guild_id]
        valid_scores = (
            (player_score[self.NAME], player_score[self.ELO])
            for player_score in players_score.values()
            if self.ELO in player_score
        )
        sorted_players = sorted(valid_scores, key=lambda score: score[1], reverse=True)

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
        with open(LEADERBOARD_PATH, "w") as file:
            file.write(json.dumps(self.data, indent=4))


class Question:
    def __init__(
        self,
        image_path: str,
        allowed_langs: list,
        allowed_players: set[nextcord.Member],
        time_between_hints: int,
        answer_formatter,
        fuzz_threshold: int,
        answers: dict[str, str],
    ):
        self.image_path = image_path
        self.allowed_langs = allowed_langs
        self.allowed_players = allowed_players
        self.time_between_hints = time_between_hints
        self.answer_formatter = answer_formatter
        self.fuzz_threshold = fuzz_threshold
        self.answers = self._filter_answer(answers)
        self.formatted_answers = self._get_formatted_answers()
        self.hints = self._get_default_hints()
        self.hints_shuffle = self._get_hints_shuffle()
        self.waiting_for_answer = True
        self.check_answer_count = 0
        self.hint_shown = 0
        self.first_message = None
        self.last_message = None
        self.last_hint_message = None

    def _filter_answer(self, answers: dict[str, str]):
        return {
            lang: answer
            for lang, answer in answers.items()
            if lang in self.allowed_langs
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

        if self.check_answer_count * cm.CHECK_ANSWER_PERIOD >= int(
            self.time_between_hint
        ):
            self.check_answer_count = 0
            return True

        return False

    def exceed_max_hint(self):
        return self.hint_shown < int(cm.MAX_HINT)

    def _get_hint(self, lang):
        char_to_show_number = len(self.hints_shuffle[lang]) // (
            int(cm.MAX_HINT) - self.hint_shown
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
                >= self.fuzz_threshold
            ):
                return True
        return False

    def is_winner(self, message_content: str, author_id: int):
        return (
            not self.allowed_players or author_id in self.allowed_players
        ) and self.is_correct_answer(message_content)


class Quiz:
    def __init__(
        self,
        config_manager: cm,
        guild_id: int,
        questions: pd.DataFrame,
        game_names: GameNames,
        number_of_question: int,
        config_name: str,
        game_category: str,
        year: str,
    ):
        self._config_manager = config_manager
        self._guild_id = guild_id
        self._questions = questions
        self._game_names = game_names
        self._config_name = config_name
        self._config = self._get_config()

        self.is_running = True
        self.waiting_for_answer = False
        self.number_of_question = number_of_question
        self.allowed_langs = self._get_allowed_langs()
        self.max_hint = self._get_max_hint()
        self.time_between_hint = self._get_time_between_hint()
        self.answer_formatter = self._get_answer_formatter()
        self.fuzz_threshold = self._get_fuzz_threshold()
        self.game_category = game_category
        self.year = year
        self.is_ranked = game_category == cm.RANKED
        self.allowed_players: set[nextcord.Member] = set()
        self.leaderboard = Leaderboard()
        self.multilang_plural = "s" if len(self.allowed_langs) >= 2 else ""

        if self.is_ranked:
            self.elo_leaderboard = EloLeaderboard()

    def _get_config(self):
        return self._config_manager.get_config(self._config_name)

    def _get_allowed_langs(self):
        return self._config_manager.get_allowed_langs(self._guild_id)

    def _get_max_hint(self):
        return self._config_manager.get_max_hint(self._config)
    
    def _get_time_between_hint(self):
        return 

    def _get_answer_formatter(self):
        return self._config_manager.get_answer_formatter(self._config)

    def _get_fuzz_threshold(self):
        return self._config_manager.get_fuzz_threshold(self._config)

    def create_settings(self):
        settings = [
            f"- questions: **{self.number_of_question}**",
            f"- difficulty: **{self._config_name}**",
            f"- category: **{self.game_category}**",
        ]

        if self.year != -1:
            settings.append(f"- year: **{self.year} and before**")

        return "\n".join(settings)

    def initialize_leaderboard(self):
        self.leaderboard.initialize(self.allowed_players)

    def get_ingame_names(self, vnum: int, is_monster: int):
        if is_monster:
            names = self._game_names.mob_names
        else:
            names = self._game_names.item_names

        ingame_names: dict[str, str] = names.loc[vnum].to_dict()

        for lang, ig_name in ingame_names.items():
            if ig_name.endswith("+0"):
                ingame_names[lang] = ig_name[:-2]

            ingame_names[lang] = ingame_names[lang].replace(chr(160), " ").strip()

        return ingame_names

    def choose_value(self, row: pd.Series) -> str:
        if pd.isna(row[cm.IMAGE_NAME2]):
            return row[cm.IMAGE_NAME1]
        else:
            return rd.choice(
                [
                    row[cm.IMAGE_NAME1],
                    row[cm.IMAGE_NAME2],
                ]
            )

    def get_questions(self):
        if self.year == -1:
            questions = self._questions
        else:
            questions = self._questions[self._questions["year"] <= self.year]

        questions = questions.sample(self.number_of_question)

        questions = [
            Question(
                image_path=os.path.join(IMAGES_PATH, self.choose_value(question)),
                allowed_langs=self.allowed_langs,
                allowed_players=self.allowed_players,
                time_between_hint=self.time_between_hint,
                answer_formatter=self.answer_formatter,
                fuzz_threshold=self.fuzz_threshold,
                answers=self.get_ingame_names(vnum, question[cm.IS_MONSTER]),
            )
            for vnum, question in questions.iterrows()
        ]

        return questions

    def calc_and_save_new_elo(self):
        return self.elo_leaderboard.calc_and_save_new_elo(
            self._guild_id, self.leaderboard
        )

    def stop(self):
        self.is_running = False


class QuizManager:
    def __init__(self):
        self._questions = self._get_questions()
        self.config_manager = cm()
        self._game_names = GameNames(langs_data=cm.LANGS_DATA)
        self.total_questions = self._questions.shape[0]
        self.quizzes_in_progress: dict[int, Quiz] = {}

    def _get_questions(self):
        return pd.read_csv(QUESTIONS_PATH, sep=",", index_col=[cm.VNUM])

    def has_active_quiz(self, channel_id: int):
        if channel_id not in self.quizzes_in_progress:
            return False

        return True

    def get_quiz(self, channel_id: int):
        return self.quizzes_in_progress[channel_id]

    def start_quiz(
        self,
        guild_id: int,
        channel_id: int,
        number_of_question: int,
        config_name: str,
        game_category: str,
        year: int,
    ):
        new_quiz = Quiz(
            config_manager=self.config_manager,
            guild_id=guild_id,
            questions=self._questions,
            game_names=self._game_names,
            number_of_question=number_of_question,
            config_name=config_name,
            game_category=game_category,
            year=year,
        )
        self.quizzes_in_progress[channel_id] = new_quiz
        return new_quiz

    def end_quiz(self, channel_id: int):
        self.quizzes_in_progress[channel_id].stop()
        del self.quizzes_in_progress[channel_id]

    def get_lang_icon(self, lang: str):
        return self.config_manager.get_lang_icon(lang)

    def get_elo(self, guild_id: int, player: nextcord.Member):
        return self.elo_leaderboard.get_elo(guild_id, player)

    def get_player_ranking(self, guild_id: int, player_name: str):
        return self.elo_leaderboard.get_player_ranking(guild_id, player_name)

    def get_elo_leaderboard(self, guild_id: int):
        return self.elo_leaderboard.get_leaderboard(guild_id)
