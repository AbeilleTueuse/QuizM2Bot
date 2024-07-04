import asyncio
from datetime import timedelta, datetime, timezone
import os

import nextcord
from nextcord.ext.commands import Bot, Cog
from nextcord.ext import tasks
from nextcord import Interaction, Embed, slash_command

from src.quiz_manager import QuizManager, ConfigurationManager, Question, EloLeaderboard

CONSOLE_PATH = "output-1187021385093107765.log"
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
        self.embed_value = ""

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

    @nextcord.ui.button(
        label="Registration", style=nextcord.ButtonStyle.success, emoji="🎟️"
    )
    async def button_callback(self, _, interaction: nextcord.Interaction):
        user = interaction.user

        if user.id in self.players:
            return

        self.players[user.id] = user.name
        self.embed_value += f"\n- {user.display_name} ({self.quiz_manager.get_elo(interaction.guild_id, user.id, user.name)})"

        self.embed.set_field_at(
            index=2,
            name="Participants",
            value=self.embed_value,
            inline=False,
        )


class DropDown(nextcord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        default_langs = CONFIGURATION_MANAGER.get_default_langs(guild_id)

        super().__init__(
            placeholder="Choose languages",
            min_values=1,
            max_values=len(CONFIGURATION_MANAGER.langs_data.keys()),
            options=[
                nextcord.SelectOption(
                    label=lang,
                    emoji=data["emoji"],
                    default=lang in default_langs,
                )
                for lang, data in CONFIGURATION_MANAGER.langs_data.items()
            ],
        )

    async def callback(self, interaction: Interaction):
        CONFIGURATION_MANAGER.update_allowed_langs(self.guild_id, self.values)
        await interaction.send(
            "Languages have been successfully changed.", ephemeral=True
        )


class QuizCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.quiz_manager = QuizManager(config_manager=CONFIGURATION_MANAGER)

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
            name="category",
            description="Choose the category of the quiz.",
            choices=CONFIGURATION_MANAGER.GAME_CATEGORIES,
            required=True,
        ),
        max_year: int = nextcord.SlashOption(
            name="max_year",
            description="Only keep pages created on this year and before.",
            min_value=2011,
            max_value=2024,
            required=False,
            default=-1,
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
        settings_value = f"- questions: **{number_of_question}**\n- difficulty: **{config_name}**\n- category: **{game_category}**"

        if max_year != -1:
            settings_value = f"{settings_value}\n- year: **before {max_year}**"

        embed.add_field(
            name="Settings",
            value=settings_value,
        )
        embed.add_field(
            name="Allowed languages",
            value=" ".join(
                CONFIGURATION_MANAGER.get_icon(lang)
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

            if not self.quiz_manager.quiz_is_running():
                return

            allowed_players = registration_button.players.keys()

            if not len(allowed_players):
                await channel.send(
                    "There are not registered players, the quiz is canceled."
                )
                self.quiz_manager.end_quiz()
                return

            self.quiz_manager.leaderboard.initialize(allowed_players)
        else:
            allowed_players = []
            await interaction.send(embed=embed)

        CONFIGURATION_MANAGER.allowed_players = allowed_players
        questions = self.quiz_manager.get_questions(number_of_question, max_year)

        for question_index, question in enumerate(questions):
            if not self.quiz_manager.quiz_is_running():
                break

            await self.ask_question(
                channel, question_index, question, number_of_question
            )

            while self.quiz_manager.waiting_for_answer():
                await self.wait_for_answer(channel, question)

            answer_message, answer_embed = await self.show_answer(channel, question)

            if (
                question_index + 1 != number_of_question
                and self.quiz_manager.quiz_is_running()
            ):
                await self.next_question_timer.start(answer_message, answer_embed)

        if self.quiz_manager.quiz_is_running():
            await asyncio.sleep(self.quiz_manager.TIME_BETWEEN_QUESTION)
            await channel.send("The quiz is over, thanks for playing!")
            await self.show_leaderboard(channel)
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
        image = nextcord.File(question.image_path, filename="arcthegod.png")
        embed.set_image(url="attachment://arcthegod.png")

        if self.quiz_manager.ranked_quiz:
            embed.set_footer(text="Only registered players can participate.")

        message = await channel.send(embed=embed, file=image)
        self.quiz_manager.start_question()
        question.last_message = message
        question.first_message = message

    async def get_close_answers(
        self,
        channel: nextcord.channel.TextChannel,
        question: Question,
        first_message: nextcord.message.Message,
        winner_message: nextcord.message.Message,
        winner_time: float,
    ):
        close_answers = [[winner_message.author.display_name, winner_time, 0]]

        async for message in channel.history(
            limit=None,
            after=winner_message,
            before=winner_message.created_at + timedelta(seconds=1),
            oldest_first=True,
        ):
            if question.is_winner(message.content, message.author.id):
                answer_time = (
                    message.created_at - first_message.created_at
                ).total_seconds()
                close_answers.append(
                    [
                        message.author.display_name,
                        answer_time,
                        answer_time - winner_time,
                    ]
                )

        return close_answers

    async def show_close_answers(
        self, channel: nextcord.channel.TextChannel, close_answers: list
    ):
        if len(close_answers) <= 1:
            return

        embed = Embed(
            title="It was close!",
            description="\n".join(
                f"- {name}: {time:.3f}s (+{extra_time:.3f})"
                for name, time, extra_time in close_answers
            ),
            color=0xFF5733,
        )
        await channel.send(embed=embed)

    async def wait_for_close_answers(self, winner_message: nextcord.message.Message):
        current_time = datetime.now(timezone.utc)
        elapsed_time = (current_time - winner_message.created_at).total_seconds()
        time_to_wait = max(
            0, CONFIGURATION_MANAGER.CLOSE_ANSWSER_MAX_SECOND - elapsed_time
        )

        await asyncio.sleep(time_to_wait)

    async def wait_for_answer(
        self,
        channel: nextcord.channel.TextChannel,
        question: Question,
    ):
        await asyncio.sleep(CONFIGURATION_MANAGER.CHECK_ANSWER_PERIOD)
        message = question.last_message

        async for message in channel.history(
            limit=None, after=message, oldest_first=True
        ):
            if question.is_winner(message.content, message.author.id):
                self.quiz_manager.end_question()
                first_message: nextcord.message.Message = question.first_message
                answer_time = (
                    message.created_at - first_message.created_at
                ).total_seconds()

                await message.reply(
                    f"Good game! You answered in {answer_time:.3f} seconds."
                )
                self.quiz_manager.leaderboard.increment_score(message.author.id)

                await self.wait_for_close_answers(message)
                close_answers = await self.get_close_answers(
                    channel,
                    question,
                    first_message,
                    message,
                    answer_time,
                )
                await self.show_close_answers(channel, close_answers)
                break
        else:
            question.last_message = message

            if not question.show_hint() or not self.quiz_manager.waiting_for_answer():
                return

            if question.exceed_max_hint():
                question.get_hints()
                embed = Embed(
                    title=f"Hint {question.hint_shown} of {CONFIGURATION_MANAGER.max_hint}",
                    description="\n".join(
                        f"{CONFIGURATION_MANAGER.get_icon(lang)} ┊ {' '.join(hint)}"
                        for lang, hint in question.hints.items()
                    ),
                    color=0xEDF02A,
                )

                last_hint_message: nextcord.message.Message = question.last_hint_message

                new_hint_message = await channel.send(embed=embed)
                question.last_hint_message = new_hint_message

                if last_hint_message is not None:
                    await last_hint_message.delete()

            else:
                self.quiz_manager.end_question()
                await channel.send(f"Too late!")

    async def show_answer(
        self, channel: nextcord.channel.TextChannel, question: Question
    ):
        if not self.quiz_manager.quiz_is_running():
            return None, None

        embed = Embed(
            title=f"Answer{self.quiz_manager.multilang_plural}",
            description="\n".join(
                f"{CONFIGURATION_MANAGER.get_icon(lang)} ┊ {answer}"
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

        if not self.quiz_manager.quiz_is_running():
            embed.remove_footer()
            self.next_question_timer.stop()

        await message.edit(embed=embed)

        if not remaining_time:
            self.next_question_timer.stop()
            embed.remove_footer()
            await message.edit(embed=embed)

    async def show_leaderboard(self, channel: nextcord.channel.TextChannel):
        if self.quiz_manager.ranked_quiz:
            elo_augmentation = self.quiz_manager.get_new_elo(channel.guild.id)
        else:
            elo_augmentation = None

        leaderboard = "\n".join(
            self.user_row_leaderboard(channel, user_id, rank, score, elo_augmentation)
            for rank, user_id, score in self.quiz_manager.leaderboard.get_leaderboard()
        )
        embed = Embed(title="Leaderboard 🏆", description=leaderboard, color=0x33A5FF)
        await channel.send(embed=embed)

    def user_row_leaderboard(
        self,
        channel: nextcord.channel.TextChannel,
        user_id: int,
        rank: str,
        score: int,
        elo_augmentation: dict,
    ):
        user_name = self.user_id_to_display_name(channel, user_id)

        row = f"{rank} ┊ **{user_name}** ({score} point{'s' * (score > 1)})"

        if elo_augmentation is not None:
            new_elo, elo_augmentation = elo_augmentation[user_id]
            row += f" ┊ {new_elo} ({elo_augmentation})"

        return row

    @staticmethod
    def user_id_to_display_name(channel: nextcord.channel.TextChannel, user_id: int):
        return channel.guild.get_member(user_id).display_name
    
    @staticmethod
    def user_name_to_display_name(guild: nextcord.Guild, user_name: str) -> str:
        member = nextcord.utils.get(guild.members, name=user_name)
        if member is not None:
            return member.display_name
        return user_name

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

    @quiz.subcommand(name="ranking")
    async def show_user_elo(
        self,
        interaction: Interaction,
    ):
        """Show user elo."""
        elo = self.quiz_manager.get_elo(
            interaction.guild_id, interaction.user.id, interaction.user.name
        )

        await interaction.send(f"You have {elo} elo.")

    @quiz.subcommand(name="leaderboard")
    async def show_elo_leaderboard(
        self,
        interaction: Interaction,
    ):
        """Show elo leaderboard."""
        leaderboard = "\n".join(
            f"{rank} ┊ **{self.user_name_to_display_name(interaction.guild, user_name)}** ({elo})"
            for rank, user_name, elo in self.quiz_manager.get_elo_leaderboard(
                interaction.guild_id
            )
        )
        embed = Embed(
            title="Elo leaderboard 🏆", description=leaderboard, color=0x33A5FF
        )
        await interaction.send(embed=embed)

    @quiz.subcommand(name="info")
    async def show_quiz_info(
        self,
        interaction: Interaction,
    ):
        """Display information about the quiz."""
        await interaction.response.defer()

        embed = Embed(
            title="Quiz information",
            description=f"Use the command `/quiz start` to start a quiz. There are currently **{self.quiz_manager.total_questions}** names to guess. The parameters below must be set.",
            color=0x33A5FF,
        )
        embed.add_field(
            name="Questions",
            value="The number of questions of the quiz. Choose a value from the displayed list.",
            inline=False,
        )

        difficulty_description = "The difficulty changes the precision required for answers to be accepted as well as the number of hints and the time between hints."

        embed.add_field(
            name="Difficulty",
            value=difficulty_description
            + "\n"
            + "\n".join(CONFIGURATION_MANAGER.get_descriptions()),
            inline=False,
        )
        embed.add_field(name="Category", value="- friendly: ...\n- ranker: ...")

        await interaction.send(embed=embed)

    @quiz.subcommand(name="lang")
    async def set_lang(
        self,
        interaction: Interaction,
    ):
        """Set languages authorized for the next quizzes."""
        user = interaction.user

        if user.id == self.bot.owner_id or user.guild_permissions.administrator:
            dropdown_view = nextcord.ui.View()
            dropdown_view.add_item(DropDown(interaction.guild_id))

            await interaction.send(view=dropdown_view, ephemeral=True)

        else:
            await interaction.send("You can't use this command.", ephemeral=True)

    @slash_command(name="info")
    async def info(self, interaction: Interaction):
        """Get bot information."""
        if interaction.user.id == self.bot.owner_id:
            embed = Embed(title="Bot information ℹ️", color=0x33A5FF)
            embed.add_field(
                name="Servers list",
                value="\n".join(
                    f"- {guild.name} ({guild.member_count})"
                    for guild in self.bot.guilds
                ),
            )
            await interaction.send(embed=embed, ephemeral=True)
        else:
            await interaction.send("You can't use this command.", ephemeral=True)

    @slash_command(name="console")
    async def get_console(
        self,
        interaction: Interaction,
    ):
        """Get the console."""
        if interaction.user.id == self.bot.owner_id:
            if os.path.exists(CONSOLE_PATH):
                await interaction.send(file=nextcord.File(CONSOLE_PATH), ephemeral=True)
            else:
                await interaction.send(f"The file {CONSOLE_PATH} doesn't exist.", ephemeral=True)
        else:
            await interaction.send("You can't use this command.", ephemeral=True)

    @slash_command(name="file")
    async def get_leaderboard(
        self,
        interaction: Interaction,
    ):
        """Get the leaderboard."""
        if interaction.user.id == self.bot.owner_id:
            leaderboard_path = EloLeaderboard.DATA_PATH

            if os.path.exists(leaderboard_path):
                await interaction.send(
                    file=nextcord.File(leaderboard_path), ephemeral=True
                )
            else:
                await interaction.send(f"The file {leaderboard_path} doesn't exist.", ephemeral=True)
        else:
            await interaction.send("You can't use this command.", ephemeral=True)


def setup(bot: Bot):
    bot.add_cog(QuizCog(bot))
