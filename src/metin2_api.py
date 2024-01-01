import requests

import pandas as pd
import mwparserfromhell
from mwparserfromhell.wikicode import Wikicode
from mwparserfromhell.nodes.template import Template
from mwparserfromhell.nodes.extras.parameter import Parameter


ALPHABET = "abcdefghijklmnopqrstuvwxyz"
ALPHABET += ALPHABET.upper()
BASE = len(ALPHABET)


class Page:
    def __init__(self, title: str, content: Wikicode):
        self.title = title
        self.content = mwparserfromhell.parse(content)
        self.ig_name: str = None
        self.image_name = None
        self.template = self._get_template()

    def __str__(self):
        return f"(Page: {self.title})"

    def _get_template(self) -> Template:
        return self.content.filter(forcetype=Template)[0]

    def add_ig_name(self, item_names: pd.Series):
        parameter: Parameter = self.template.get("Code")
        code = str(parameter.value).strip()
        vnum = self.code_to_vnum(code)
        ig_name: str = item_names.at[vnum]

        if ig_name.endswith("+0"):
            ig_name = ig_name[:-2]

        self.ig_name = ig_name

    def add_image_name(self):
        image_parameter: Parameter = self.template.get("Image")
        image_name = str(image_parameter.value).strip()

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
