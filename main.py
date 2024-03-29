import logging

from nextcord import Intents, Game
from nextcord.ext.commands import Bot


if __name__ == "__main__":
    # logging.basicConfig(
    #     filename="logs.log",
    #     level=logging.DEBUG,
    #     format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
    #     datefmt="%Y-%m-%d %H:%M:%S",
    # )
    
    with open("token.txt", "r") as file:
        token = file.readline()

    intents = Intents.default()
    intents.message_content = True
    intents.members = True

    bot = Bot(intents=intents, activity=Game(name="/quiz"))
    bot.load_extension("src.start_quiz")

    bot.run(token)