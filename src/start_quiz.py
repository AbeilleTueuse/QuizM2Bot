import asyncio
from datetime import datetime

import nextcord
from nextcord.ext.commands import Bot, Cog
from nextcord.ext import tasks
from nextcord import Interaction, Embed, slash_command

from src.quiz_manager import (
    QuizManager,
    ConfigurationManager,
    Question,
)
from src.metin2_api import M2Wiki


CONFIGURATION_MANAGER = ConfigurationManager()


class RegistrationButton(nextcord.ui.View):
    MESSAGE_OPEN = "Registrations will close in {remaining_time} second{plural}."
    MESSAGE_CLOSE = "Registrations are closed."

    def __init__(self, embed: Embed):
        super().__init__()
        self.embed = embed
        self.count = 10
        self.players = {}

    async def update(self, message: nextcord.message.Message):
        await self.timer.start(message)

    @tasks.loop(seconds=1)
    async def timer(self, message: nextcord.message.Message):
        plural = "s" * (self.count >= 2)

        self.embed.set_footer(text=self.MESSAGE_OPEN.format(remaining_time=self.count, plural=plural))
        await message.edit(embed=self.embed, view=self)

        if not self.count:
            self.children[0].disabled = True
            self.embed.set_footer(text=self.MESSAGE_CLOSE)
            await message.edit(embed=self.embed, view=self)
            self.timer.stop()

        self.count -= 1

    @nextcord.ui.button(label="Registration", style=nextcord.ButtonStyle.success, emoji="🎟️")
    async def button_callback(self, _, interaction: nextcord.Interaction):
        user = interaction.user

        if user.id in self.players:
            return

        self.players[user.id] = user.name
        self.embed.set_field_at(2, name="Participants", value="\n".join(f"- {name}" for name in self.players.values()), inline=False)


class QuizCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.quiz_manager = QuizManager(
            m2_wiki=M2Wiki(), config_manager=CONFIGURATION_MANAGER
        )

    @slash_command(name="quiz")
    async def quiz(self, interaction: Interaction):
        pass

    @quiz.subcommand(name="start")
    async def start_quiz(
        self,
        interaction: Interaction,
        number_of_question: int = nextcord.SlashOption(
            name="questions",
            description="Choose the number of questions to ask.",
            choices=CONFIGURATION_MANAGER.NUMBER_OF_QUESTION,
            required=True,
        ),
        config_name: str = nextcord.SlashOption(
            name="difficulty",
            description="Choose the quiz difficulty.",
            choices=CONFIGURATION_MANAGER.saved_config.keys(),
            required=True,
        ),
        game_category: str = nextcord.SlashOption(
            name="type",
            description="Choose the type of the quiz.",
            choices=CONFIGURATION_MANAGER.GAME_CATEGORIES,
            required=True,
        ),
    ):
        """Start a quiz."""
        if self.quiz_manager.quiz_is_running():
            await interaction.send("A quiz is already in progress.")
            return

        CONFIGURATION_MANAGER.set_config(config_name)

        channel = interaction.channel
        self.quiz_manager.start_quiz()

        embed = Embed(
            title="Launch of the quiz!",
            color=0x5E296B,
        )
        embed.add_field(
            name="Settings",
            value=f"- **{number_of_question}** questions\n- difficulty **{config_name}**\n- category **{game_category}**",
        )
        embed.add_field(
            name="Allowed languages",
            value=" ".join(
                f":flag_{lang.replace('en', 'gb')}:"
                for lang in CONFIGURATION_MANAGER.ALLOWED_LANGS
            ),
            inline=False
        )

        if self.quiz_manager.is_ranked_quiz(game_category):
            embed.add_field(name="Participants", value="No one is registered.", inline=False)
            registration_button = RegistrationButton(embed=embed)
            message = await interaction.send(embed=embed, view=registration_button)
            await registration_button.update(message)

            if len(registration_button.players.keys()) <= 1:
                await channel.send("There are not enough players registered, the quiz is canceled.")
                self.quiz_manager.end_quiz()
                return

            # f"- {player_name} ({self.quiz_manager.get_elo(interaction.guild_id, player_id, player_name)} elo)"
            # for player_id, player_name in registration_button.players.items()

            await channel.send(embed=embed)
            await channel.send("The quiz will start soon!")

        else:
            await interaction.send(embed=embed)

        questions = self.quiz_manager.get_questions(number_of_question)

        for question_index, question in enumerate(questions):
            if not self.quiz_manager.quiz_is_running():
                break

            await self.ask_question(
                channel, question_index, question, number_of_question
            )

            while self.quiz_manager.waiting_for_answer():
                await self.wait_for_answer(channel, question)

            if (
                question_index + 1 != number_of_question
                and self.quiz_manager.quiz_is_running()
            ):
                await channel.send(
                    f"Next question in {self.quiz_manager.TIME_BETWEEN_QUESTION} seconds!"
                )

            await asyncio.sleep(self.quiz_manager.TIME_BETWEEN_QUESTION)

        if self.quiz_manager.quiz_is_running():
            if self.quiz_manager.ranked_quiz:
                self.quiz_manager.update_ranked_ranking()
                await self.show_ranked_ranking(channel)
            else:
                await self.show_ranking(channel)
            self.quiz_manager.end_quiz()

    async def ask_question(
        self,
        channel: nextcord.channel.TextChannel,
        question_index: int,
        question: Question,
        number_of_question: int,
    ):
        embed = Embed(
            title=f"Question {question_index + 1} of {number_of_question}",
            description=f"What is the name of this?",
            color=0x7AFF33,
        )
        embed.set_image(url=question.image_url)

        message = await channel.send(embed=embed)
        self.quiz_manager.start_question()
        question.change_last_message(message)

    async def wait_for_answer(
        self,
        channel: nextcord.channel.TextChannel,
        question: Question,
    ):
        await asyncio.sleep(CONFIGURATION_MANAGER.CHECK_ANSWER_PERIOD)
        message = question.get_last_message()

        async for message in channel.history(
            limit=None, after=message, oldest_first=True
        ):
            if question.is_correct_answer(message.content):
                self.quiz_manager.end_question()
                await message.reply(f"Good game!")
                await self.show_answer(channel, question)
                self.quiz_manager.ranking.increment_score(message.author.name)
                break
        else:
            question.change_last_message(message)

            if not question.show_hint() or not self.quiz_manager.waiting_for_answer():
                return

            if question.exceed_max_hint():
                question.get_hints()
                embed = Embed(
                    title=f"Hint {question.hint_shown} of {CONFIGURATION_MANAGER.config[CONFIGURATION_MANAGER.MAX_HINT]}",
                    description="\n".join(
                        f":flag_{lang.replace('en', 'gb')}: ┊ {' '.join(hint)}"
                        for lang, hint in question.hints.items()
                    ),
                    color=0xEDF02A,
                )

                last_hint_message: nextcord.message.Message = (
                    question.get_last_hint_message()
                )

                new_hint_message = await channel.send(embed=embed)
                question.change_last_hint_message(new_hint_message)

                if last_hint_message is not None:
                    await last_hint_message.delete()

            else:
                self.quiz_manager.end_question()
                await channel.send(f"Too late!")
                await self.show_answer(channel, question)

    async def show_answer(
        self, channel: nextcord.channel.TextChannel, question: Question
    ):
        embed = Embed(
            title="Answers",
            description="\n".join(
                f":flag_{lang.replace('en', 'gb')}: ┊ {answer}"
                for lang, answer in question.answers.items()
            ),
            color=0x5E296B,
        )
        await channel.send(embed=embed)

    async def show_ranking(self, channel: nextcord.channel.TextChannel):
        await channel.send("The quiz is over, thanks for playing!")
        self.quiz_manager.ranking.sort()
        ranking = "\n".join(
            f"{self.quiz_manager.ranking.convert_rank(rank + 1)} : **{name}** ({score} point{'s' * (score > 1)})"
            for rank, (name, score) in enumerate(self.quiz_manager.ranking)
        )
        embed = Embed(title="Ranking 🏆", description=ranking, color=0x33A5FF)
        await channel.send(embed=embed)

    async def show_ranked_ranking(self, channel: nextcord.channel.TextChannel):
        channel.send("Not added.")

    @quiz.subcommand(name="stop")
    async def stop_quiz(self, interaction: Interaction):
        """Suddenly stops the current quiz."""
        if not self.quiz_manager.quiz_is_running():
            await interaction.send("There are no quizzes in progress.")
            return

        self.quiz_manager.end_quiz()
        await interaction.send("The quiz has been stopped.")

    @quiz.subcommand(name="skip")
    async def skip_question(self, interaction: Interaction):
        """Allows you to cancel the current question and move on to the next one."""
        if not self.quiz_manager.quiz_is_running():
            await interaction.send("There are no quizzes in progress.")
            return

        if not self.quiz_manager.waiting_for_answer():
            await interaction.send("There are no questions in progress.")
            return

        self.quiz_manager.end_question()
        await interaction.send("The question was canceled.")

    # @quiz.subcommand(name="ranking")
    # async def show_general_ranking(
    #     self,
    #     interaction: Interaction,
    #     config_name: str = nextcord.SlashOption(
    #         name="difficulty",
    #         description="Choose the ranking.",
    #         choices=CONFIGURATION_MANAGER.saved_config.keys(),
    #         required=True,
    #     ),
    # ):
    #     """Show general ranking."""
    #     self.quiz_manager.general_ranking.sort()
    #     ranking = "\n".join(
    #         f"{self.quiz_manager.ranking.convert_rank(rank + 1)} : **{name}** ({score} point{'s' * (score > 1)})"
    #         for rank, (name, score) in enumerate(self.quiz_manager.general_ranking)
    #     )
    #     embed = Embed(title=f"General ranking ({config_name})", description=ranking, color=0x33A5FF)
    #     await interaction.send(embed=embed)


def setup(bot: Bot):
    bot.add_cog(QuizCog(bot))
