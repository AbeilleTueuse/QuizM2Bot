import os

import pandas as pd


class ItemNames:
    # cz
    LANGS = ["ae", "de", "dk", "en", "fr", "gr", "hu", "it", "nl", "pl", "pt", "ro", "ru", "tr"]
    PATH = os.path.join("src", "data")
    FILENAME = "item_names.txt"

    VNUM = "VNUM"

    def __init__(self):
        self.data = self._create_data()

    def _read_csv(self, lang: str):
        path = os.path.join(self.PATH, lang, self.FILENAME)

        item_names = pd.read_csv(
            filepath_or_buffer=path,
            index_col=0,
            usecols=[0, 1],
            names=[self.VNUM, lang],
            encoding="Windows-1252",
            sep="\t",
            skiprows=1
        )

        return item_names[lang].str.replace(chr(160), " ")
    
    def _create_data(self):
        return pd.concat((self._read_csv(lang) for lang in self.LANGS), axis=1)
    

class MobNames:
    # cz
    LANGS = ["ae", "de", "dk", "en", "fr", "gr", "hu", "it", "nl", "pl", "pt", "ro", "ru", "tr"]
    PATH = os.path.join("src", "data")
    FILENAME = "mob_names.txt"

    VNUM = "VNUM"

    def __init__(self):
        self.data = self._create_data()

    def _read_csv(self, lang: str):
        path = os.path.join(self.PATH, lang, self.FILENAME)

        item_names = pd.read_csv(
            filepath_or_buffer=path,
            index_col=0,
            usecols=[0, 1],
            names=[self.VNUM, lang],
            encoding="Windows-1252",
            sep="\t",
            skiprows=1
        )

        return item_names[lang].str.replace(chr(160), " ")
    
    def _create_data(self):
        return pd.concat((self._read_csv(lang) for lang in self.LANGS), axis=1)