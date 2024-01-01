import os

from nextcord import Intents
from nextcord.ext.commands import Bot


if __name__ == "__main__":
    with open(os.path.join("src", "token.txt"), "r") as file:
        TOKEN = file.read()
    
    intents = Intents.default()
    intents.message_content = True

    bot = Bot(intents=intents)
    bot.load_extension("start_quiz")

    bot.run(TOKEN)