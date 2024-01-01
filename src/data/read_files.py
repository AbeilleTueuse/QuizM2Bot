import os

import pandas as pd


class ItemName:
    LOCAL_NAME = "LOCALE_NAME"
    INDEX = "VNUM"

    def __init__(self):
        self.data = self._read_csv()

    def _read_csv(self):
        item_names = pd.read_csv(
            os.path.join("src", "data", "item_names.txt"),
            index_col=self.INDEX,
            encoding="Windows-1252",
            sep="\t",
        )

        item_names[self.LOCAL_NAME] = item_names[self.LOCAL_NAME].str.replace(chr(160), " ")

        return item_names