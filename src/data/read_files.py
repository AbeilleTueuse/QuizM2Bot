import os
import json

import pandas as pd


class GameNames:
    ENCODING_PATH = os.path.join("src", "data", "lang_encoding.json")
    DATA_PATH = os.path.join("src", "data")

    MOB_NAMES = "mob_names.txt"
    ITEM_NAMES = "item_names.txt"

    INDEX_NAME = "vnnum"
    SEPARATOR = "\t"

    def __init__(self):
        self.encoding = self._get_encoding()
        self.mob_names = self._get_data(self.MOB_NAMES)
        self.item_names = self._get_data(self.ITEM_NAMES)

    def _get_encoding(self) -> dict[str, str]:
        with open(self.ENCODING_PATH, "r") as file:
            return json.load(file)

    def _read_csv(self, filename: str, lang: str, encoding: str):
        names = pd.read_csv(
            filepath_or_buffer=os.path.join(self.DATA_PATH, lang, filename),
            index_col=0,
            usecols=[0, 1],
            names=[self.INDEX_NAME, lang],
            encoding=encoding,
            sep=self.SEPARATOR,
            skiprows=1,
        )

        return names[lang]

    def _get_data(self, filename: str):
        return pd.concat(
            (
                self._read_csv(filename, lang, encoding)
                for lang, encoding in self.encoding.items()
            ),
            axis=1,
        )
