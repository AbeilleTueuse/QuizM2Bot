import logging

from nextcord import Intents
from nextcord.ext.commands import Bot

# test
if __name__ == "__main__":
    logging.basicConfig(
        filename="logs.log",
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    with open("token.txt", "r") as file:
        token = file.readline()
    
    intents = Intents.default()
    intents.message_content = True

    bot = Bot(intents=intents)
    bot.load_extension("src.start_quiz")

    bot.run(token)