import asyncio
import logging

import nextcord
from nextcord.ext.commands import Bot, Cog
from nextcord import Interaction, Embed, slash_command

from src.quiz_manager import (
    QuizManager,
    ConfigurationManager,
    Question,
)
from src.metin2_api import M2Wiki


CONFIGURATION_MANAGER = ConfigurationManager()


class QuizCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.quiz_manager = QuizManager(m2_wiki=M2Wiki())

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
            choices=[5, 10, 20, 40],
            required=True,
        ),
        config_name: str = nextcord.SlashOption(
            name="difficulty",
            description="Choose the quiz difficulty.",
            choices=CONFIGURATION_MANAGER.saved_config.keys(),
            required=True,
        ),
    ):
        """Start a quiz."""
        if self.quiz_manager.quiz_is_running():
            await interaction.send("A quiz is already in progress.")
            return

        logging.info("Launch of the quiz.")
        channel = interaction.channel
        CONFIGURATION_MANAGER.set_config(config_name)

        self.quiz_manager.start_quiz(config_manager=CONFIGURATION_MANAGER)

        embed = Embed(
            title="Launch of the quiz!",
            description=f"The quiz settings are as follows:\n- {number_of_question} questions,\n- difficulty {config_name}.",
            color=0x5E296B,
        )
        if config_name != CONFIGURATION_MANAGER.HARDCORE:
            embed.add_field(
                name="Allowed languages",
                value=" ".join(
                    f":flag_{lang.replace('en', 'gb')}:"
                    for lang in CONFIGURATION_MANAGER.ALLOWED_LANGS
                ),
            )

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
        embed = Embed(title="Ranking", description=ranking, color=0x33A5FF)
        await channel.send(embed=embed)

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
