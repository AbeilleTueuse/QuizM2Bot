import json

from unidecode import unidecode

from src.paths import CONFIG_PATH, LANGS_BY_SERVERS_PATH, LANGS_DATA_PATH
from src.utils.utils import open_json


class ConfigurationManager:
    CHECK_ANSWER_PERIOD = 1
    REGISTRATION_TIME = 30
    CHANGE_LANG_TIME = 30
    CLOSE_ANSWSER_MAX_SECOND = 1
    TIME_BETWEEN_QUESTION = 10

    NUMBER_OF_QUESTION = [1, 5, 10, 20, 40]
    FRIENDYLY = "friendly"
    RANKED = "ranked"
    GAME_CATEGORIES = [FRIENDYLY, RANKED]

    MIN_YEAR = 2011
    MAX_YEAR = 2024

    HARDCORE = "hardcore"
    MODE = "mode"
    TIME_BETWEEN_HINT = "time_between_hint"
    MAX_HINT = "max_hint"
    DESCRIPTION = "description"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    VERY_PERMISSIVE = "very permissive"

    DEFAULT_LANG = "fr"
    EMOJI = "emoji"

    FUZZ_THRESHOLD = {
        STRICT: 100,
        PERMISSIVE: 97,
        VERY_PERMISSIVE: 94,
    }

    SAVED_CONFIG: dict[str, dict] = open_json(CONFIG_PATH)
    LANGS_DATA = open_json(LANGS_DATA_PATH)

    VNUM = "vnum"
    IS_MONSTER = "is_monster"
    IMAGE_NAME1 = "image_name1"
    IMAGE_NAME2 = "image_name2"

    FILE_NAME = "arcthegod.png"

    def __init__(self):
        self.langs_by_servers = open_json(LANGS_BY_SERVERS_PATH)

    def get_config(self, config_name: str):
        return self.SAVED_CONFIG[config_name]

    def get_answer_formatter(self, config: dict):
        mode = config[self.MODE]

        if mode == self.STRICT:
            return self._strict

        elif mode == self.PERMISSIVE:
            return self._permissive

        elif mode == self.VERY_PERMISSIVE:
            return self._very_permissive

        else:
            raise ValueError(f"{mode} isn't a correct value.")

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

    def get_allowed_langs(self, guild_id: int) -> list[str]:
        if guild_id in self.langs_by_servers:
            return self.langs_by_servers[guild_id]

        return [self.DEFAULT_LANG]

    def update_allowed_langs(self, guild_id: int, new_langs: list[str]):
        self.langs_by_servers[guild_id] = new_langs

        with open(LANGS_BY_SERVERS_PATH, "w") as file:
            file.write(json.dumps(self.langs_by_servers, indent=4))

    def get_lang_icon(self, lang: str) -> str:
        return self.LANGS_DATA[lang][self.EMOJI]

    def get_descriptions(self):
        return (
            config_parameters[self.DESCRIPTION]
            for config_parameters in self.SAVED_CONFIG.values()
        )
