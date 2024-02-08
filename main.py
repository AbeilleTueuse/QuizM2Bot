from nextcord import Intents, Game
from nextcord.ext.commands import Bot


if __name__ == "__main__":
    GOD_ID = 413429373996367872
    
    with open("token.txt", "r") as file:
        token = file.readline()

    intents = Intents.default()
    intents.message_content = True
    intents.members = True

    bot = Bot(intents=intents, activity=Game(name="/quiz"), owner_id=GOD_ID)
    bot.load_extension("src.start_quiz")

    bot.run(token)