import os

import pandas as pd

from src.paths import MOB_NAMES_PATH, ITEM_NAMES_PATH


class GameNames:
    INDEX_NAME = "vnum"
    SEPARATOR = "\t"

    def __init__(self, langs_data: dict[str, dict]):
        self.langs_data = langs_data
        self.mob_names = self._get_data(MOB_NAMES_PATH)
        self.item_names = self._get_data(ITEM_NAMES_PATH)

    def _read_csv(self, path: str, lang: str, encoding: str):
        names = pd.read_csv(
            filepath_or_buffer=path.format(lang=lang),
            index_col=0,
            usecols=[0, 1],
            names=[self.INDEX_NAME, lang],
            encoding=encoding,
            sep=self.SEPARATOR,
            skiprows=1,
        )

        return names[lang]

    def _get_data(self, path: str):
        return pd.concat(
            (
                self._read_csv(path, lang, data["encoding"])
                for lang, data in self.langs_data.items()
            ),
            axis=1,
        )
