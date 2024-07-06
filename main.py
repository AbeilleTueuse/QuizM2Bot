from nextcord import Intents, Game
from nextcord.ext.commands import Bot

from src.commands import QuizCog


if __name__ == "__main__":
    GOD_ID = 413429373996367872
    ACTIVITY = Game(name="/quiz")

    with open("token.txt", "r") as file:
        token = file.readline()

    intents = Intents.default()
    intents.message_content = True
    intents.members = True

    bot = Bot(intents=intents, activity=ACTIVITY, owner_id=GOD_ID)
    bot.add_cog(QuizCog(bot))

    bot.run(token)

    # cc
    # abeille
    # bateau
    # bertrand
    
