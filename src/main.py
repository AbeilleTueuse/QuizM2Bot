import os

from nextcord import Intents
from nextcord.ext.commands import Bot


if __name__ == "__main__":
    TOKEN = input("Enter the discord bot token: ")
    
    intents = Intents.default()
    intents.message_content = True

    bot = Bot(intents=intents)
    bot.load_extension("start_quiz")

    bot.run(TOKEN)