import random as rd
from collections import defaultdict
import json
import os

from unidecode import unidecode
from fuzzywuzzy import fuzz

from src.metin2_api import M2Wiki, Page
from src.data.read_files import ItemName


class ConfigurationManager:
    CHECK_ANSWER_PERIOD = 1
    LANG = "fr"

    MODE = "mode"
    TIME_BETWEEN_HINT = "time_between_hint"
    MAX_HINT = "max_hint"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    VERY_PERMISSIVE = "very permissive"

    CONFIG_PATH = os.path.join("src", "config.json")
    TRANSLATION_PATH = os.path.join("src", "translation.json")

    FUZZ_THRESHOLD = {
        STRICT: 100,
        PERMISSIVE: 97,
        VERY_PERMISSIVE: 95,
    }

    def __init__(self):
        self.config = None
        self.formatted_answer = None
        self.fuzz_threshold = 100
        self.saved_config = self._open(self.CONFIG_PATH)
        self.translation = self._open(self.TRANSLATION_PATH)

    def _open(self, path) -> dict[str, dict]:
        with open(path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def set_config(self, config_name: str):
        self.config = self.saved_config[config_name]
        self.formatted_answer = self._get_formatted_answer()

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
        answer = answer.replace("-", " ").replace("de", "du")
        formatted_answer = "".join(
            letter
            for letter in self._permissive(answer)
            if letter.isalnum() or letter == " "
        )
        return " ".join(formatted_answer.split())

    def get_config(self, name: str) -> dict[str, str]:
        return self.saved_config[name]

    def translate(self, value: str) -> str:
        if value in self.translation[self.LANG]:
            return self.translation[self.LANG][value]

        if not value.isnumeric():
            print(f"{value} can't be translated.")

        return value
    
    def config_names(self):
        return {self.translate(key): key for key in self.saved_config}


class Leaderboard:
    PSEUDO_COLUMN = "Pseudo"
    SCORE_COLUMN = "Score"

    def __init__(self):
        self.scores = defaultdict(int)

    def increment_score(self, name: str):
        self.scores[name] += 1

    def sort(self):
        self.scores = sorted(self.scores, key=lambda player: player[self.SCORE_COLUMN])

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
        return iter(sorted(self.scores.items(), key=lambda item: item[1], reverse=True))


class Question:
    def __init__(
        self, answer: str, image_url: str, config_manager: ConfigurationManager
    ):
        self.answer = answer
        self.image_url = image_url
        self.config_manager = config_manager
        self.formatted_answer = self._formatted_answer(answer)
        self.hint = self._get_default_hint()
        self.hint_shuffle = self._get_hint_shuffle()
        self.answer_len = len(answer)
        self.check_answer_count = 0
        self.hint_shown = 0
        self.last_message = None

    def _formatted_answer(self, answer: str):
        return self.config_manager.formatted_answer(answer)

    def _get_default_hint(self):
        return [
            "\u200B \u200B" if char == " " else "__\u200B \u200B \u200B__"
            for char in self.answer
        ]

    def _get_hint_shuffle(self):
        char_position = list(enumerate(self.answer))
        rd.shuffle(char_position)

        return char_position

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

    def get_hint(self):
        char_to_show_number = len(self.hint_shuffle) // (
            int(self.config_manager.config[self.config_manager.MAX_HINT])
            - self.hint_shown
        )

        for _ in range(char_to_show_number):
            pos, char = self.hint_shuffle.pop()

            if char == " ":
                continue

            self.hint[pos] = f"__{char}__"

        self.hint_shown += 1

    def is_correct_answer(self, user_answer: str):
        print(self.config_manager.fuzz_threshold)
        return fuzz.ratio(self._formatted_answer(user_answer), self.formatted_answer) >= self.config_manager.fuzz_threshold
    
    def change_last_message(self, message):
        self.last_message = message


class QuizManager:
    TIME_BETWEEN_QUESTION = 5

    def __init__(self, m2_wiki: M2Wiki):
        self._started = False
        self._waiting_for_answer = False
        self.m2_wiki = m2_wiki
        self.config = None
        self.leaderboard = Leaderboard()
        self.item_names = ItemName().data

    def start_quiz(self, config_manager: ConfigurationManager):
        self.config_manager = config_manager
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
            ),
            k=number_of_question,
        )
        pages = self.m2_wiki.get_pages_content(pages_info)

        for page in pages:
            page.add_ig_name(self.item_names)
            page.add_image_name()

        pages: list[Page] = sorted(pages, key=lambda page: page.image_name)
        image_urls = self.m2_wiki.get_image_urls(pages)

        questions = [
            Question(page.ig_name, image_url, self.config_manager)
            for page, image_url in zip(pages, image_urls)
        ]
        rd.shuffle(questions)

        return questions

    def end_quiz(self):
        self._started = False
        self._waiting_for_answer = False
        self.leaderboard.reset()

    def end_question(self):
        self._waiting_for_answer = False
