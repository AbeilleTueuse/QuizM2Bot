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

    DISPLAYED_LANGS = ["en", "fr", "ro"]

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
        self.fuzz_threshold = 100
        self.saved_config = self._open(self.CONFIG_PATH)

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
        answer = answer.replace("-", " ")
        formatted_answer = "".join(
            letter
            for letter in self._permissive(answer)
            if letter.isalnum() or letter == " "
        )
        return " ".join(formatted_answer.split())

    def get_config(self, name: str) -> dict[str, str]:
        return self.saved_config[name]


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
        self, answers: dict[str, str], image_url: str, config_manager: ConfigurationManager
    ):
        self.answers = answers
        self.image_url = image_url
        self.config_manager = config_manager
        self.displayed_hints = self._get_displayed_hints()
        self.formatted_answers = self._formatted_answers()
        self.hints = self._get_default_hints()
        self.hints_shuffle = self._get_hints_shuffle()
        self.check_answer_count = 0
        self.hint_shown = 0
        self.last_message = None

    def _get_displayed_hints(self):
        return {lang: answer for lang, answer in self.answers.items() if lang in self.config_manager.DISPLAYED_LANGS}
    
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
        return {lang: self._get_default_hint(answer) for lang, answer in self.displayed_hints.items()}

    def _get_hint_shuffle(self, answer: str):
        char_position = list(enumerate(answer))
        rd.shuffle(char_position)

        return char_position
    
    def _get_hints_shuffle(self):
        return {lang: self._get_hint_shuffle(answer) for lang, answer in self.displayed_hints.items()}

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
            if fuzz.ratio(formatted_user_answer, formatted_answer) >= self.config_manager.fuzz_threshold:
                return True
        return False
    
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
            Question(page.ig_names, image_url, self.config_manager)
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
