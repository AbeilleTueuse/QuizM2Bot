import random as rd
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
    convert_rank,
    get_current_time,
)
from src.config import ConfigurationManager as cm
from src.paths import IMAGES_PATH, QUESTIONS_PATH, LEADERBOARD_PATH


class Player:
    def __init__(self, player: nextcord.Member, elo: int = None, score: int = 0):
        self.id = player.id
        self.name = player.display_name
        self.avatar = player.display_avatar
        self.elo = elo
        self.score = score
        self.rank = None
        self.elo_augmentation = None

    def increment_score(self):
        self.score += 1

    def leaderboard_display(self):
        ranking = f"{convert_rank(self.rank)} ┊ **{self.name}** ({self.score} point{'s' * (self.score > 1)})"

        if self.elo_augmentation is not None:
            new_elo = self.elo + self.elo_augmentation
            ranking += (
                f" ┊ {new_elo} ({format_number_with_sign(self.elo_augmentation)})"
            )

        return ranking

    def register_display(self):
        return f"{self.name} ({self.elo})"


class Question:
    def __init__(
        self,
        image_path: str,
        allowed_langs: list,
        allowed_players: set[int],
        max_hint: int,
        time_between_hints: int,
        answer_formatter,
        fuzz_threshold: int,
        answers: dict[str, str],
    ):
        self.image_path = image_path
        self.allowed_langs = allowed_langs
        self.allowed_players = allowed_players
        self.max_hint = max_hint
        self.time_between_hints = time_between_hints
        self.answer_formatter = answer_formatter
        self.fuzz_threshold = fuzz_threshold
        self.answers = self._filter_answer(answers)
        self.formatted_answers = self._get_formatted_answers()
        self.hints = self._get_default_hints()
        self.hints_shuffle = self._get_hints_shuffle()
        self.check_answer_count = 0
        self.hint_shown = 0
        self.first_message: nextcord.Message = None
        self.first_message_timestamp : float = None
        self.last_message: nextcord.Message = None
        self.last_hint_message: nextcord.Message = None

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
    
    def add_first_message(self, message: nextcord.Message):
        self.last_message = message
        self.first_message = message
        self.first_message_timestamp = message.created_at.timestamp()

    def show_hint(self):
        if (
            get_current_time() - self.first_message.created_at
        ).total_seconds() + cm.CHECK_ANSWER_PERIOD / 2 >= (
            self.hint_shown + 1
        ) * self.time_between_hints:
            return True

        return False

    def under_hint_limit(self):
        return self.hint_shown < self.max_hint

    def _get_hint(self, lang):
        char_to_show_number = len(self.hints_shuffle[lang]) // (
            self.max_hint - self.hint_shown
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
        self._questions = questions
        self._game_names = game_names
        self._config_name = config_name
        self._config = self._get_config()

        self.guild_id = guild_id
        self.is_running = True
        self.waiting_for_answer = False
        self.number_of_question = number_of_question
        self.allowed_langs = self._get_allowed_langs()
        self.max_hint = self._get_max_hint()
        self.time_between_hints = self._get_time_between_hint()
        self.answer_formatter = self._get_answer_formatter()
        self.fuzz_threshold = self._get_fuzz_threshold()
        self.game_category = game_category
        self.year = year
        self.is_ranked = game_category == cm.RANKED
        self.players: dict[int, Player] = {}
        self.allowed_players: set[int] = set()
        self.multilang_plural = "s" if len(self.allowed_langs) >= 2 else ""

    def _get_config(self):
        return self._config_manager.get_config(self._config_name)

    def _get_allowed_langs(self):
        return self._config_manager.get_allowed_langs(self.guild_id)

    def _get_max_hint(self):
        return self._config[cm.MAX_HINT]

    def _get_time_between_hint(self):
        return self._config[cm.TIME_BETWEEN_HINT]

    def _get_answer_formatter(self):
        return self._config_manager.get_answer_formatter(self._config)

    def _get_fuzz_threshold(self):
        return cm.FUZZ_THRESHOLD[self._config[cm.MODE]]

    def create_settings(self):
        settings = [
            f"- questions: **{self.number_of_question}**",
            f"- difficulty: **{self._config_name}**",
            f"- category: **{self.game_category}**",
        ]

        if self.year != -1:
            settings.append(f"- year: **{self.year} and before**")

        return "\n".join(settings)

    def add_new_player(self, player: nextcord.Member, elo: int) -> Player:
        self.allowed_players.add(player.id)

        player = Player(player=player, elo=elo, score=0)
        self.players[player.id] = player

        return player

    def increment_score(self, player: nextcord.Member):
        if player.id in self.players:
            self.players[player.id].score += 1

        elif not self.is_ranked:
            self.players[player.id] = Player(player=player, score=1)

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
                max_hint=self.max_hint,
                time_between_hints=self.time_between_hints,
                answer_formatter=self.answer_formatter,
                fuzz_threshold=self.fuzz_threshold,
                answers=self.get_ingame_names(vnum, question[cm.IS_MONSTER]),
            )
            for vnum, question in questions.iterrows()
        ]

        return questions

    def get_leaderboard(self):
        sorted_players = sorted(
            self.players.items(), key=lambda item: item[1].score, reverse=True
        )

        current_rank = 1
        current_score = None

        for index, (_, player) in enumerate(sorted_players, start=1):
            if player.score != current_score:
                current_rank = index
                current_score = player.score

            player.rank = current_rank

            yield player

    def stop(self):
        self.waiting_for_answer = False
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


class EloManager:
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

    def _save_data(self):
        with open(LEADERBOARD_PATH, "w") as file:
            file.write(json.dumps(self._data, indent=4))

    def get_elo(self, guild_id: int, player_id: int, player_name=None):
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

    def _update(self, guild_id, player_id, new_elo: int):
        self._data[guild_id][player_id][self.ELO] = new_elo

    def update_elo_ratings(self, quiz: Quiz):
        if len(quiz.allowed_players) == 1:
            return

        current_elo = {
            player_id: player.elo for player_id, player in quiz.players.items()
        }
        players_items = quiz.players.items()

        for player_id, player in players_items:
            player_elo = current_elo[player_id]
            elo_augmentation = sum(
                elo_formula(
                    player_elo, player.score, current_elo[opponent_id], opponent.score
                )
                for opponent_id, opponent in players_items
                if player_id != opponent_id
            )
            quiz.players[player_id].elo_augmentation = elo_augmentation
            self._update(quiz.guild_id, player_id, player_elo + elo_augmentation)

        self._save_data()

    def get_leaderboard(self, guild_id: int):
        players_score: dict[int, dict] = self._data[guild_id]
        valid_scores = (
            (player_score[self.NAME], player_score[self.ELO])
            for player_score in players_score.values()
            if self.ELO in player_score
        )
        sorted_players = sorted(valid_scores, key=lambda score: score[1], reverse=True)

        current_rank = 1
        current_score = None

        for index, (player_name, score) in enumerate(sorted_players, start=1):
            if index == self.LEADERBOARD_MAX_DISPLAY + 1:
                break

            if score != current_score:
                current_rank = index
                current_score = score

            yield ((convert_rank(current_rank), player_name, score))

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
