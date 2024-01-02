import random as rd
from collections import defaultdict
import json
import os

from unidecode import unidecode

from src.metin2_api import M2Wiki, Page
from src.data.read_files import ItemName


class MissingConfiguration(Exception):
    pass


class ConfigurationManager:
    CHECK_ANSWER_PERIOD = 1
    LANG = "fr"

    DEFAULT = "default"
    MODE = "mode"
    TIME_BETWEEN_HINT = "time_between_hint"
    MAX_HINT = "max_hint"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    VERY_PERMISSIVE = "very permissive"

    PARAMS = {MODE: [STRICT, PERMISSIVE, VERY_PERMISSIVE]}

    CONFIG_PATH = os.path.join("src", "config.json")
    TRANSLATION_PATH = os.path.join("src", "translation.json")

    def __init__(self):
        self.config = None
        self.formatted_answer = None
        self.saved_config = self._open(self.CONFIG_PATH)
        self.translation = self._open(self.TRANSLATION_PATH)

    def _open(self, path) -> dict[str, dict]:
        with open(path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def _save(self):
        with open(self.CONFIG_PATH, "w", encoding="utf-8") as config_file:
            config_file.write(json.dumps(self.saved_config, indent=4))

    def set_config(self, config_name: str):
        if config_name is not None and config_name in self.saved_config:
            self.config = self.saved_config[config_name]

        else:
            self.config = self.saved_config[self.DEFAULT]

        self.formatted_answer = self._get_formatted_answer()

    def _get_formatted_answer(self):
        mode = self._get_mode()

        if mode == self.STRICT:
            return self._strict

        elif mode == self.PERMISSIVE:
            return self._permissive

        elif mode == self.VERY_PERMISSIVE:
            return self._very_permissive

        return self._strict

    async def autocomplete_configuration(self, cog, interaction, user_input: str):
        return list(self.saved_config.keys())[:25]

    async def autocomplete_configuration_delete(
        self, cog, interaction, user_input: str
    ):
        return list(self.saved_config.keys())[1:25]

    def _strict(self, answer: str):
        return answer

    def _permissive(self, answer: str):
        return unidecode(answer.lower())

    def _very_permissive(self, answer: str):
        return "".join(
            letter
            for letter in self._permissive(answer)
            if letter.isalnum() or letter == " "
        ).replace("de", "du")

    def _get_mode(self):
        return self.config[self.MODE]

    def create_new_config(
        self, name: str, mode: str, time_between_hint: int, max_hint: int
    ):
        if name in self.saved_config:
            raise MissingConfiguration

        if mode not in self.PARAMS[self.MODE]:
            mode = self.STRICT

        time_between_hint = max(0, time_between_hint)
        max_hint = max(0, max_hint)

        self.saved_config[name] = {
            self.MODE: mode,
            self.TIME_BETWEEN_HINT: time_between_hint,
            self.MAX_HINT: max_hint,
        }
        self._save()

    def delete_config(self, name: str):
        if name not in self.saved_config:
            raise MissingConfiguration

        del self.saved_config[name]
        self._save()

    def get_config(self, name: str) -> dict[str, str]:
        if name not in self.saved_config:
            raise MissingConfiguration

        return self.saved_config[name]

    def translate(self, value: str) -> str:
        if value in self.translation[self.LANG]:
            return self.translation[self.LANG][value]

        if not value.isnumeric():
            print(f"{value} can't be translated.")

        return value

    def get_mode_choices(self):
        return {self.translate(key): key for key in self.PARAMS[self.MODE]}


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
        return self._formatted_answer(user_answer) == self.formatted_answer


class QuizManager:
    TIME_BETWEEN_QUESTION = 1

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
