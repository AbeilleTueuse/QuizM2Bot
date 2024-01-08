import random as rd
from collections import defaultdict
import json
import os

from unidecode import unidecode
from fuzzywuzzy import fuzz

from src.metin2_api import M2Wiki, Page
from src.data.read_files import GameNames
from src.utils.utils import json_converter, format_number_with_sign, elo_formula


class ConfigurationManager:
    CHECK_ANSWER_PERIOD = 1
    REGISTRATION_TIME = 30

    NUMBER_OF_QUESTION = [5, 10, 20, 40]
    FRIENDYLY = "friendly"
    RANKED = "ranked"
    GAME_CATEGORIES = [FRIENDYLY, RANKED]
    ALLOWED_LANGS = {
        507732107036983297: ["en", "fr", "ro", "it"], # Metin2Dev
        719469557647147018: ["fr"], # Shaaky
        970626513131147264: ["ae", "en", "fr", "pt"], # Wiki
        963091224988889088: ["fr"], #JusQuoBou
    }

    HARDCORE = "hardcore"
    MODE = "mode"
    TIME_BETWEEN_HINT = "time_between_hint"
    MAX_HINT = "max_hint"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    VERY_PERMISSIVE = "very permissive"

    CONFIG_PATH = os.path.join("src", "config.json")

    FUZZ_THRESHOLD = {
        STRICT: 100,
        PERMISSIVE: 97,
        VERY_PERMISSIVE: 95,
    }

    def __init__(self):
        self.config = None
        self.formatted_answer = None
        self.allowed_langs = ["fr"]
        self.fuzz_threshold = 100
        self.saved_config = self._open(self.CONFIG_PATH)

    def _open(self, path) -> dict[str, dict]:
        with open(path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def set_config(self, config_name: str, guild_id: int):
        self.config = self.saved_config[config_name]
        self.formatted_answer = self._get_formatted_answer()

        if guild_id in self.ALLOWED_LANGS:
            self.allowed_langs = self.ALLOWED_LANGS[guild_id]

    def _get_formatted_answer(self):
        mode = self.config[self.MODE]
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


class Ranking:
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

    def convert_rank(self, rank):
        if rank == 1:
            return "🥇"
        if rank == 2:
            return "🥈"
        if rank == 3:
            return "🥉"
        return f"{rank}e"

    def reset(self):
        self.__init__()

    def __iter__(self):
        return iter(self.scores.items())

    def __len__(self):
        return len(self.scores.keys())

    def get_ranking(self):
        sorted_players = sorted(self, key=lambda x: x[1], reverse=True)

        ranking = []
        current_rank = 1
        current_score = None

        for index, (player_id, score) in enumerate(sorted_players):
            if score != current_score:
                current_rank = index + 1
                current_score = score
            ranking.append((self.convert_rank(current_rank), player_id, score))

        return ranking


class EloRanking:
    DATA_PATH = os.path.join("src", "ranking.json")
    ELO = "elo"
    NAME = "name"
    DEFAULT_ELO = 1000

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

    def _update_elo(self, guild_id, player_id, additionnal_elo):
        self.data[guild_id][player_id][self.ELO] += additionnal_elo

    def get_new_elo(self, guild_id: int, ranking: Ranking):
        current_elo = {
            player_id: self.get_elo(guild_id, player_id) for player_id, _ in ranking
        }
        new_elo = {}

        for player_id, player_score in ranking:
            player_elo = current_elo[player_id]
            additionnal_elo = sum(
                elo_formula(
                    player_elo, player_score, current_elo[opponent_id], opponent_score
                )
                for opponent_id, opponent_score in ranking
                if player_id != opponent_id
            )
            new_elo[player_id] = [
                player_elo + additionnal_elo,
                format_number_with_sign(additionnal_elo),
            ]
            self._update_elo(guild_id, player_id, additionnal_elo)
        self._save()

        return new_elo

    def _save(self):
        with open(self.DATA_PATH, "w") as file:
            file.write(json.dumps(self.data, indent=4))


class Question:
    def __init__(
        self,
        answers: dict[str, str],
        image_url: str,
        config_manager: ConfigurationManager,
    ):
        self.config_manager = config_manager
        self.answers = self._filter_answer(answers)
        self.image_url = image_url
        self.formatted_answers = self._formatted_answers()
        self.hints = self._get_default_hints()
        self.hints_shuffle = self._get_hints_shuffle()
        self.check_answer_count = 0
        self.hint_shown = 0
        self._last_message = None
        self._last_hint_message = None

    def _filter_answer(self, answers: dict[str, str]):
        return {
            lang: answer
            for lang, answer in answers.items()
            if lang in self.config_manager.allowed_langs
        }

    def _formatted_answer(self, answer: str):
        return self.config_manager.formatted_answer(answer)

    def _formatted_answers(self):
        return [self._formatted_answer(answer) for answer in self.answers.values()]

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
            self.config_manager.config[self.config_manager.TIME_BETWEEN_HINT]
        ):
            self.check_answer_count = 0
            return True

        return False

    def exceed_max_hint(self):
        return self.hint_shown < int(
            self.config_manager.config[self.config_manager.MAX_HINT]
        )

    def _get_hint(self, lang):
        char_to_show_number = len(self.hints_shuffle[lang]) // (
            int(self.config_manager.config[self.config_manager.MAX_HINT])
            - self.hint_shown
        )

        for _ in range(char_to_show_number):
            pos, char = self.hints_shuffle[lang].pop()

            if char == " ":
                continue

            self.hints[lang][pos] = f"__{char}__"

    def get_hints(self):
        for lang in self.hints:
            self._get_hint(lang)

        self.hint_shown += 1

    def is_correct_answer(self, user_answer: str):
        formatted_user_answer = self._formatted_answer(user_answer)
        for formatted_answer in self.formatted_answers:
            if (
                fuzz.ratio(formatted_user_answer, formatted_answer)
                >= self.config_manager.fuzz_threshold
            ):
                return True
        return False

    def change_last_message(self, message):
        self._last_message = message

    def get_last_message(self):
        return self._last_message

    def change_last_hint_message(self, message):
        self._last_hint_message = message

    def get_last_hint_message(self):
        return self._last_hint_message


class QuizManager:
    TIME_BETWEEN_QUESTION = 5

    def __init__(self, m2_wiki: M2Wiki, config_manager: ConfigurationManager):
        self._started = False
        self._waiting_for_answer = False
        self.ranked_quiz = False
        self.m2_wiki = m2_wiki
        self.config_manager = config_manager
        self.ranking = Ranking()
        self.elo_ranking = EloRanking()
        self.game_names = GameNames()

    def start_quiz(self):
        self._started = True

    def quiz_is_running(self):
        return self._started

    def start_question(self):
        self._waiting_for_answer = True

    def waiting_for_answer(self):
        return self._waiting_for_answer

    def get_questions(self, number_of_question: int = 1):
        pages_info = rd.choices(
            self.m2_wiki.category(
                category="Objets (temporaire)", exclude_category="Objets multiples"
            )
            + self.m2_wiki.category(category="Monstres (temporaire)"),
            k=number_of_question,
        )
        pages = self.m2_wiki.get_pages_content(pages_info)

        for page in pages:
            page.add_ingame_name(self.game_names)
            page.add_image_name()

        pages: list[Page] = sorted(pages, key=lambda page: page.image_name)
        image_urls = self.m2_wiki.get_image_urls(pages)

        questions = [
            Question(page.ingame_names, image_url, self.config_manager)
            for page, image_url in zip(pages, image_urls)
        ]
        rd.shuffle(questions)

        return questions

    def end_quiz(self):
        self._started = False
        self._waiting_for_answer = False
        self.ranking.reset()

    def end_question(self):
        self._waiting_for_answer = False

    def is_ranked_quiz(self, game_category: str):
        is_ranked = game_category == self.config_manager.RANKED
        self.ranked_quiz = is_ranked
        return is_ranked

    def get_elo(self, guild_id: int, player_id: int, player_name: str):
        return self.elo_ranking.get_elo(guild_id, player_id, player_name)

    def get_new_elo(self, guild_id: int):
        return self.elo_ranking.get_new_elo(guild_id, self.ranking)
