import requests
import random as rd

import mwparserfromhell
from mwparserfromhell.wikicode import Wikicode
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.nodes.extras.parameter import Parameter

from src.data.read_files import GameNames


ALPHABET = "abcdefghijklmnopqrstuvwxyz"
ALPHABET += ALPHABET.upper()
BASE = len(ALPHABET)


class Page:
    MONSTER = "Monstres"

    def __init__(self, title: str, content: Wikicode):
        self.title = title
        self.content = mwparserfromhell.parse(content)
        self.ingame_names: list[str] = None
        self.image_name = None
        self.template = self._get_template()
        self.type = self._get_type()

    def __str__(self):
        return f"(Page: {self.title})"

    def _get_template(self) -> Template:
        return self.content.filter(forcetype=Template)[0]
    
    def _get_type(self):
        return str(self.template.name).strip()

    def add_ingame_name(self, game_names: GameNames):
        parameter: Parameter = self.template.get("Code")
        code = str(parameter.value).strip()
        vnum = self.code_to_vnum(code)

        if self.type == self.MONSTER:
            names = game_names.mob_names
        else:
            names = game_names.item_names
        
        ingame_names: dict[str, str] = names.loc[vnum].to_dict()

        for lang, ig_name in ingame_names.items():
            if ig_name.endswith("+0"):
                ingame_names[lang] = ig_name[:-2]

        self.ingame_names = ingame_names

    def add_image_name(self, apparence_prob: float):
        if self.template.has("Apparence"):
            if rd.random() > apparence_prob:
                image_parameter: Parameter = self.template.get("Image")
            else:
                image_parameter: Parameter = self.template.get("Apparence")
        else:
            image_parameter: Parameter = self.template.get("Image")

        image_name = str(image_parameter.value).strip()

        if self.type == "Monstres":
            self.image_name = f"Fichier:{image_name}-min.png"
        else:
            self.image_name = f"Fichier:{image_name}.png"

    def code_to_vnum(self, letters: str) -> int:
        number = 0

        for i, letter in enumerate(letters):
            value = ALPHABET.index(letter)
            number += value * (BASE**i)

        return number


class M2Wiki:
    MAX_LAG = 1
    LIST_TO_PREFIX = {
        "categorymembers": "cm",
        "allimages": "ai",
        "allpages": "ap",
    }

    def __init__(self):
        self.session = requests.Session()
        self.api_url = "https://fr-wiki.metin2.gameforge.com/api.php"

    def wiki_request(self, query_params: dict) -> dict:
        query_params["maxlag"] = self.MAX_LAG
        return self.session.get(url=self.api_url, params=query_params).json()

    def query_request_recursive(self, query_params, result: list) -> list:
        request_result = self.wiki_request(query_params)
        continue_value = request_result.get("continue", False)
        list_value = query_params["list"]

        result += request_result["query"][list_value]

        if continue_value:
            prefix = self.LIST_TO_PREFIX[list_value] + "continue"
            query_params[prefix] = continue_value[prefix]
            self.query_request_recursive(query_params, result)

        return result

    def category(self, category: str, exclude_category: str = None) -> list[dict]:
        query_params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": "max",
            "cmtype": "page",
        }

        pages = self.query_request_recursive(query_params, [])

        if exclude_category is not None:
            pages_to_exclude = self.category(exclude_category)
            pages = [page for page in pages if page not in pages_to_exclude]

        return pages

    def get_pages_content(self, pagesinfo: list):
        query_params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "content",
            "formatversion": "2",
            "pageids": "|".join(str(pageinfo["pageid"]) for pageinfo in pagesinfo),
        }

        request_result = self.wiki_request(query_params)

        return [
            Page(title=page_data["title"], content=page_data["revisions"][0]["content"])
            for page_data in request_result["query"]["pages"]
        ]

    def get_image_urls(self, pages: list[Page]):
        query_params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": "|".join(page.image_name for page in pages),
            "iiprop": "url",
        }

        request_result = self.wiki_request(query_params)

        pages_info: dict = request_result["query"]["pages"]

        return [pages_info[pageid]["imageinfo"][0]["url"] for pageid in pages_info]