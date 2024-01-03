from nextcord import Intents
from nextcord.ext.commands import Bot


if __name__ == "__main__":
    # TOKEN = input("Enter the discord bot token: ")
    TOKEN = "MTE5MjA2MjU0NDU2Nzg2NTQyNQ.Gc0oA6.zreJ4cN-lPLdyOJCHpVTQ5GqoUyhpJHpRqtoP0"
    
    intents = Intents.default()
    intents.message_content = True

    bot = Bot(intents=intents)
    bot.load_extension("src.start_quiz")

    bot.run(TOKEN)