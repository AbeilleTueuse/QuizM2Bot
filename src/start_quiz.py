import asyncio

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

    def __init__(self, quiz_manager: QuizManager, embed: Embed, registration_time: int):
        super().__init__()
        self.quiz_manager = quiz_manager
        self.embed = embed
        self.registration_time = registration_time
        self.players = {}

    async def update(self, message: nextcord.message.Message):
        await self.registration_timer.start(message)

    @tasks.loop(seconds=1)
    async def registration_timer(self, message: nextcord.message.Message):
        remaining_time = self.registration_time - self.registration_timer.current_loop
        plural = "s" * (remaining_time >= 2)

        self.embed.set_footer(
            text=self.MESSAGE_OPEN.format(remaining_time=remaining_time, plural=plural)
        )
        await message.edit(embed=self.embed, view=self)

        if not remaining_time or not self.quiz_manager.quiz_is_running():
            button: nextcord.ui.Button = self.children[0]
            button.disabled = True
            self.embed.set_footer(text=self.MESSAGE_CLOSE)
            await message.edit(embed=self.embed, view=self)
            self.registration_timer.stop()

    @nextcord.ui.button(label="Registration", style=nextcord.ButtonStyle.success, emoji="🎟️")
    async def button_callback(self, _, interaction: nextcord.Interaction):
        user = interaction.user

        if user.id in self.players:
            return

        self.players[user.id] = user.name
        self.embed.set_field_at(
            index=2,
            name="Participants",
            value="\n".join(
                f"- {player_name} ({self.quiz_manager.get_elo(interaction.guild_id, player_id, player_name)})"
                for player_id, player_name in self.players.items()
            ),
            inline=False,
        )


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

        CONFIGURATION_MANAGER.set_config(config_name, interaction.guild_id)
        channel = interaction.channel
        self.quiz_manager.start_quiz()

        embed = Embed(
            title="Launch of the quiz!",
            color=0x5E296B,
        )
        embed.add_field(
            name="Settings",
            value=f"- questions: **{number_of_question}**\n- difficulty: **{config_name}**\n- category: **{game_category}**",
        )
        embed.add_field(
            name="Allowed languages",
            value=" ".join(
                f":flag_{lang.replace('en', 'gb')}:"
                for lang in CONFIGURATION_MANAGER.allowed_langs
            ),
            inline=False,
        )

        if self.quiz_manager.is_ranked_quiz(game_category):
            embed.add_field(
                name="Participants", value="No one is registered.", inline=False
            )
            registration_button = RegistrationButton(
                quiz_manager=self.quiz_manager,
                embed=embed,
                registration_time=CONFIGURATION_MANAGER.REGISTRATION_TIME,
            )
            message = await interaction.send(embed=embed, view=registration_button)
            await registration_button.update(message)

            allowed_players = registration_button.players.keys()

            if not len(allowed_players):
                await channel.send(
                    "There are not registered players, the quiz is canceled."
                )
                self.quiz_manager.end_quiz()
                return

            self.quiz_manager.ranking.initialize(allowed_players)

            await channel.send("The quiz will start soon!")

        else:
            allowed_players = []
            await interaction.send(embed=embed)

        questions = self.quiz_manager.get_questions(number_of_question)

        for question_index, question in enumerate(questions):
            if not self.quiz_manager.quiz_is_running():
                break

            await self.ask_question(
                channel, question_index, question, number_of_question
            )

            while self.quiz_manager.waiting_for_answer():
                await self.wait_for_answer(channel, question, allowed_players)

            answer_message, answer_embed = await self.show_answer(channel, question)

            if (
                question_index + 1 != number_of_question
                and self.quiz_manager.quiz_is_running()
            ):
                await self.next_question_timer.start(answer_message, answer_embed)

        if self.quiz_manager.quiz_is_running():
            await asyncio.sleep(self.quiz_manager.TIME_BETWEEN_QUESTION)
            await channel.send("The quiz is over, thanks for playing!")
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

        if self.quiz_manager.ranked_quiz:
            embed.set_footer(text="Only registered players can participate.")

        message = await channel.send(embed=embed)
        self.quiz_manager.start_question()
        question.change_last_message(message)

    async def wait_for_answer(
        self,
        channel: nextcord.channel.TextChannel,
        question: Question,
        allowed_players: list,
    ):
        await asyncio.sleep(CONFIGURATION_MANAGER.CHECK_ANSWER_PERIOD)
        message = question.get_last_message()

        async for message in channel.history(
            limit=None, after=message, oldest_first=True
        ):
            if (
                not allowed_players or message.author.id in allowed_players
            ) and question.is_correct_answer(message.content):
                self.quiz_manager.end_question()
                await message.reply(f"Good game!")
                self.quiz_manager.ranking.increment_score(message.author.id)
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

    async def show_answer(
        self, channel: nextcord.channel.TextChannel, question: Question
    ):
        if not self.quiz_manager.quiz_is_running():
            return
        
        embed = Embed(
            title="Answers",
            description="\n".join(
                f":flag_{lang.replace('en', 'gb')}: ┊ {answer}"
                for lang, answer in question.answers.items()
            ),
            color=0x5E296B,
        )
        message = await channel.send(embed=embed)

        return message, embed

    @tasks.loop(seconds=1)
    async def next_question_timer(
        self, message: nextcord.message.Message, embed: Embed
    ):
        remaining_time = (
            self.quiz_manager.TIME_BETWEEN_QUESTION
            - self.next_question_timer.current_loop
        )
        plural = "s" * (remaining_time >= 2)
        embed.set_footer(text=f"Next question in {remaining_time} second{plural}.")
        await message.edit(embed=embed)

        if not remaining_time:
            self.next_question_timer.stop()

    async def show_ranking(self, channel: nextcord.channel.TextChannel):
        if self.quiz_manager.ranked_quiz:
            elo_augmentation = self.quiz_manager.get_new_elo(channel.guild.id)
        else:
            elo_augmentation = None

        ranking = "\n".join(
            self.user_row(channel, user_id, rank, score, elo_augmentation)
            for rank, user_id, score in self.quiz_manager.ranking.get_ranking()
        )
        embed = Embed(title="Ranking 🏆", description=ranking, color=0x33A5FF)
        await channel.send(embed=embed)

    def user_row(
        self,
        channel: nextcord.channel.TextChannel,
        user_id: int,
        rank: str,
        score: int,
        elo_augmentation: dict,
    ):
        user_name = self.user_id_to_name(channel, user_id)

        row = f"{rank} ┊ **{user_name}** ({score} point{'s' * (score > 1)})"

        if elo_augmentation is not None:
            new_elo, elo_augmentation = elo_augmentation[user_id]
            row += f" ┊ {new_elo} ({elo_augmentation})"

        return row

    @staticmethod
    def user_id_to_name(channel: nextcord.channel.TextChannel, user_id: int):
        return channel.guild.get_member(user_id).name

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

    @quiz.subcommand(name="rank")
    async def show_user_elo(
        self,
        interaction: Interaction,
    ):
        """Show user elo."""
        elo = self.quiz_manager.get_elo(
            interaction.guild_id, interaction.user.id, interaction.user.name
        )

        await interaction.send(f"You have {elo} elo.")

    @quiz.subcommand(name="ranking")
    async def show_elo_ranking(
        self,
        interaction: Interaction,
    ):
        """Show elo ranking."""
        ranking = "\n".join(
            f"{rank} ┊ **{user_name}** ({elo})"
            for rank, user_name, elo in self.quiz_manager.get_elo_ranking(
                interaction.guild_id
            )
        )
        embed = Embed(title="Elo ranking 🏆", description=ranking, color=0x33A5FF)
        await interaction.send(embed=embed)


def setup(bot: Bot):
    bot.add_cog(QuizCog(bot))
