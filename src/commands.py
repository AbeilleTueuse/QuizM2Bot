import asyncio
from datetime import timedelta, datetime, timezone
import os

import nextcord
from nextcord.ext.commands import Bot, Cog
from nextcord.ext import tasks

from src.widgets import DropDown, RegistrationButton
from src.quiz_manager import Quiz, QuizManager, Question, EloManager
from src.config import ConfigurationManager as cm
from src.paths import CONSOLE_PATH, LEADERBOARD_PATH, LANGS_BY_SERVERS_PATH


class QuizCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.quiz_manager = QuizManager()
        self.elo_manager = EloManager()

    @nextcord.slash_command(name="quiz")
    async def quiz(self, _):
        pass

    @quiz.subcommand(name="start")
    async def start_quiz(
        self,
        interaction: nextcord.Interaction,
        number_of_question: int = nextcord.SlashOption(
            name="questions",
            description="Choose the number of questions to ask.",
            choices=cm.NUMBER_OF_QUESTION,
            required=True,
        ),
        config_name: str = nextcord.SlashOption(
            name="difficulty",
            description="Choose the quiz difficulty.",
            choices=cm.SAVED_CONFIG.keys(),
            required=True,
        ),
        game_category: str = nextcord.SlashOption(
            name="category",
            description="Choose the category of the quiz.",
            choices=cm.GAME_CATEGORIES,
            required=True,
        ),
        year: int = nextcord.SlashOption(
            name="year",
            description="Only keep pages created on this year and before.",
            min_value=cm.MIN_YEAR,
            max_value=cm.MAX_YEAR,
            required=False,
            default=-1,
        ),
    ):
        """Start a quiz."""
        if self.quiz_manager.has_active_quiz(interaction.channel_id):
            await interaction.send("A quiz is already in progress in this channel.")
            return

        quiz = self.quiz_manager.start_quiz(
            interaction.guild_id,
            interaction.channel_id,
            number_of_question,
            config_name,
            game_category,
            year,
        )
        channel = interaction.channel

        await self.launch_embed(interaction, channel, quiz)

        if not quiz.is_running:
            return

        questions = quiz.get_questions()

        for question_index, question in enumerate(questions):
            if not quiz.is_running:
                return

            await self.ask_question(
                channel, quiz, question_index, question, number_of_question
            )

            quiz.waiting_for_answer = True

            while quiz.waiting_for_answer:
                await self.wait_for_answer(channel, quiz, question)

            if not quiz.is_running:
                return

            answer_message, answer_embed = await self.show_answer(
                channel, quiz, question
            )

            if question_index + 1 != number_of_question and quiz.is_running:
                await self.next_question_timer.start(quiz, answer_message, answer_embed)

        if quiz.is_running:
            await asyncio.sleep(cm.TIME_BETWEEN_QUESTION)
            await channel.send("The quiz is over, thanks for playing!")
            await self.show_leaderboard(channel, quiz)
            self.quiz_manager.end_quiz(channel.id)

    async def launch_embed(
        self,
        interaction: nextcord.Interaction,
        channel: nextcord.TextChannel,
        quiz: Quiz,
    ):
        embed = nextcord.Embed(
            title="Launch of the quiz!",
            color=0x5E296B,
        )
        embed.add_field(
            name="Settings",
            value=quiz.create_settings(),
        )
        embed.add_field(
            name="Allowed languages",
            value=" ".join(
                self.quiz_manager.get_lang_icon(lang) for lang in quiz.allowed_langs
            ),
            inline=False,
        )

        if quiz.is_ranked:
            embed.add_field(
                name="Participants", value="No one is registered.", inline=False
            )
            registration_button = RegistrationButton(
                elo_manager=self.elo_manager,
                quiz=quiz,
                embed=embed,
                registration_time=cm.REGISTRATION_TIME,
            )
            message = await interaction.send(embed=embed, view=registration_button)
            await registration_button.update(message)

            if not quiz.is_running:
                return

            if not quiz.allowed_players:
                await channel.send(
                    "There are not registered players, the quiz is canceled."
                )
                self.quiz_manager.end_quiz(channel.id)
                return
        else:
            await interaction.send(embed=embed)

    async def ask_question(
        self,
        channel: nextcord.TextChannel,
        quiz: Quiz,
        question_index: int,
        question: Question,
        number_of_question: int,
    ):
        embed = nextcord.Embed(
            title=f"Question {question_index + 1} of {number_of_question}",
            description=f"What is the name of this?",
            color=0x7AFF33,
        )
        image = nextcord.File(question.image_path, filename=cm.FILE_NAME)
        embed.set_image(url=f"attachment://{cm.FILE_NAME}")

        if quiz.is_ranked:
            embed.set_footer(text="Only registered players can participate.")

        message = await channel.send(embed=embed, file=image)
        question.last_message = message
        question.first_message = message

    async def get_close_answers(
        self,
        channel: nextcord.TextChannel,
        question: Question,
        first_message: nextcord.Message,
        winner_message: nextcord.Message,
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
        self, channel: nextcord.TextChannel, close_answers: list
    ):
        if len(close_answers) <= 1:
            return

        embed = nextcord.Embed(
            title="It was close!",
            description="\n".join(
                f"- {name}: {time:.3f}s (+{extra_time:.3f})"
                for name, time, extra_time in close_answers
            ),
            color=0xFF5733,
        )
        await channel.send(embed=embed)

    async def wait_for_close_answers(self, winner_message: nextcord.Message):
        current_time = datetime.now(timezone.utc)
        elapsed_time = (current_time - winner_message.created_at).total_seconds()
        time_to_wait = max(0, cm.CLOSE_ANSWSER_MAX_SECOND - elapsed_time)

        await asyncio.sleep(time_to_wait)

    async def wait_for_answer(
        self,
        channel: nextcord.TextChannel,
        quiz: Quiz,
        question: Question,
    ):
        await asyncio.sleep(cm.CHECK_ANSWER_PERIOD)
        message = question.last_message

        if not quiz.is_running:
            return

        async for message in channel.history(
            limit=None, after=message, oldest_first=True
        ):
            if question.is_winner(message.content, message.author.id):
                quiz.waiting_for_answer = False
                first_message: nextcord.Message = question.first_message
                answer_time = (
                    message.created_at - first_message.created_at
                ).total_seconds()

                await message.reply(
                    f"Good game! You answered in {answer_time:.3f} seconds."
                )
                quiz.increment_score(player=message.author)

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

            if not question.show_hint() or not quiz.waiting_for_answer:
                return

            if question.exceed_max_hint():
                question.get_hints()
                embed = nextcord.Embed(
                    title=f"Hint {question.hint_shown} of {quiz.max_hint}",
                    description="\n".join(
                        f"{self.quiz_manager.get_lang_icon(lang)} ┊ {' '.join(hint)}"
                        for lang, hint in question.hints.items()
                    ),
                    color=0xEDF02A,
                )

                last_hint_message: nextcord.Message = question.last_hint_message

                new_hint_message = await channel.send(embed=embed)
                question.last_hint_message = new_hint_message

                if last_hint_message is not None:
                    await last_hint_message.delete()

            else:
                quiz.waiting_for_answer = False
                await channel.send(f"Too late!")

    async def show_answer(
        self, interaction: nextcord.Interaction, quiz: Quiz, question: Question
    ):
        embed = nextcord.Embed(
            title=f"Answer{quiz.multilang_plural}",
            description="\n".join(
                f"{self.quiz_manager.get_lang_icon(lang)} ┊ {answer}"
                for lang, answer in question.answers.items()
            ),
            color=0x5E296B,
        )
        message = await interaction.send(embed=embed)

        return message, embed

    @tasks.loop(seconds=1)
    async def next_question_timer(
        self, quiz: Quiz, message: nextcord.Message, embed: nextcord.Embed
    ):
        remaining_time = (
            cm.TIME_BETWEEN_QUESTION - self.next_question_timer.current_loop
        )
        plural = "s" * (remaining_time >= 2)
        embed.set_footer(text=f"Next question in {remaining_time} second{plural}.")

        if not quiz.is_running:
            embed.remove_footer()
            self.next_question_timer.stop()

        await message.edit(embed=embed)

        if not remaining_time:
            self.next_question_timer.stop()
            embed.remove_footer()
            await message.edit(embed=embed)

    async def show_leaderboard(self, interaction: nextcord.Interaction, quiz: Quiz):
        if quiz.is_ranked:
            self.elo_manager.update_elo_ratings(quiz)

        embed = nextcord.Embed(title="Leaderboard 🏆", color=0x33A5FF)

        leaderboard = quiz.get_leaderboard()
        winner = next(leaderboard, None)

        if winner is not None:
            embed.description = winner.leaderboard_display() + "\n"

            for player in leaderboard:
                embed.description += player.leaderboard_display() + "\n"

            embed.set_thumbnail(winner.avatar)

        await interaction.send(embed=embed)

    @staticmethod
    def user_name_to_display_name(guild: nextcord.Guild, user_name: str):
        user = nextcord.utils.get(guild.members, name=user_name)

        if user is None:
            return user_name

        return user.display_name

    @staticmethod
    def user_name_to_display_avatar(guild: nextcord.Guild, user_name: str):
        user = nextcord.utils.get(guild.members, name=user_name)

        if user is None:
            return

        return user.display_avatar

    @quiz.subcommand(name="stop")
    async def stop_quiz(self, interaction: nextcord.Interaction):
        """Suddenly stops the current quiz."""
        if not self.quiz_manager.has_active_quiz(interaction.channel_id):
            await interaction.send("There is no quiz in progress in this channel.")
            return

        self.quiz_manager.end_quiz(interaction.channel_id)
        await interaction.send("The quiz has been stopped.")

    @quiz.subcommand(name="skip")
    async def skip_question(self, interaction: nextcord.Interaction):
        """Allows you to cancel the current question and move on to the next one."""
        if not self.quiz_manager.has_active_quiz(interaction.channel_id):
            await interaction.send("There is no quiz in progress in this channel.")
            return

        quiz = self.quiz_manager.get_quiz(interaction.channel_id)

        if not quiz.waiting_for_answer:
            await interaction.send("There are no questions in progress.")
            return

        quiz.waiting_for_answer = False
        await interaction.send("The question was canceled.")

    @quiz.subcommand(name="ranking")
    async def show_user_elo(
        self,
        interaction: nextcord.Interaction,
        member: nextcord.Member = nextcord.SlashOption(
            name="member",
            description="Choose a member to see his ranking.",
            required=False,
            default=None,
        ),
    ):
        """Show user ranking."""
        member = member if member is not None else interaction.user

        try:
            player_ranking = self.elo_manager.get_player_ranking(
                interaction.guild.id, member.name
            )

            if player_ranking is None:
                description = f"{member.mention} isn't ranked yet."

            else:
                elo, rank, total_player = player_ranking
                description = f"{member.mention} has {elo} elo ({rank}/{total_player})."

                if rank == 1:
                    description += " He's the best!"

        except KeyError:
            description = f"{member.mention} isn't ranked yet."

        embed = nextcord.Embed(
            title="Ranking 🏆", description=description, color=0x33A5FF
        )
        embed.set_thumbnail(member.display_avatar.url)

        await interaction.send(embed=embed)

    @quiz.subcommand(name="leaderboard")
    async def show_elo_leaderboard(
        self,
        interaction: nextcord.Interaction,
    ):
        """Show elo leaderboard."""
        try:
            leaderboard_data = self.elo_manager.get_elo_leaderboard(
                interaction.guild_id
            )

            if not leaderboard_data:
                await interaction.send("There are no leaderboard on this server yet.")

            leaderboard = "\n".join(
                f"{rank} ┊ **{self.user_name_to_display_name(interaction.guild, user_name)}** ({elo})"
                for rank, user_name, elo in leaderboard_data
            )
            embed = nextcord.Embed(
                title="Elo leaderboard 🏆", description=leaderboard, color=0x33A5FF
            )
            leader_avatar = self.user_name_to_display_avatar(
                interaction.guild, leaderboard_data[0][1]
            )
            if leader_avatar:
                embed.set_thumbnail(leader_avatar.url)

            await interaction.send(embed=embed)
        except KeyError:
            await interaction.send("There are no leaderboard on this server yet.")

    @quiz.subcommand(name="info")
    async def show_quiz_info(
        self,
        interaction: nextcord.Interaction,
    ):
        """Display information about the quiz."""
        embed = nextcord.Embed(
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
            + "\n".join(self.quiz_manager.config_manager.get_descriptions()),
            inline=False,
        )
        embed.add_field(name="Category", value="- friendly: ...\n- ranker: ...")

        await interaction.send(embed=embed)

    @quiz.subcommand(name="lang")
    async def set_lang(
        self,
        interaction: nextcord.Interaction,
    ):
        """Set languages authorized for the next quizzes."""
        user = interaction.user

        if user.id == self.bot.owner_id or user.guild_permissions.administrator:
            dropdown_view = nextcord.ui.View()
            dropdown_view.add_item(
                DropDown(
                    guild_id=interaction.guild_id,
                    config=self.quiz_manager.config_manager,
                )
            )

            await interaction.send(view=dropdown_view, ephemeral=True)

        else:
            await interaction.send("You can't use this command.", ephemeral=True)

    @nextcord.slash_command(name="info")
    async def info(self, interaction: nextcord.Interaction):
        """Get bot information."""
        if interaction.user.id == self.bot.owner_id:
            embed = nextcord.Embed(title="Bot information ℹ️", color=0x33A5FF)
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

    @nextcord.slash_command(name="console")
    async def get_console(
        self,
        interaction: nextcord.Interaction,
    ):
        """Get the console."""
        if interaction.user.id == self.bot.owner_id:
            if os.path.exists(CONSOLE_PATH):
                await interaction.send(file=nextcord.File(CONSOLE_PATH), ephemeral=True)
            else:
                await interaction.send(
                    f"The file {CONSOLE_PATH} doesn't exist.", ephemeral=True
                )
        else:
            await interaction.send("You can't use this command.", ephemeral=True)

    @nextcord.slash_command(name="files")
    async def get_files(
        self,
        interaction: nextcord.Interaction,
    ):
        """Get leaderboard and langs files."""
        if interaction.user.id == self.bot.owner_id:
            files_to_send = []

            if os.path.exists(LEADERBOARD_PATH):
                files_to_send.append(nextcord.File(LEADERBOARD_PATH))
            else:
                await interaction.send(
                    f"The file {LEADERBOARD_PATH} doesn't exist.", ephemeral=True
                )

            if os.path.exists(LANGS_BY_SERVERS_PATH):
                files_to_send.append(nextcord.File(LANGS_BY_SERVERS_PATH))
            else:
                await interaction.send(
                    f"The file {LANGS_BY_SERVERS_PATH} doesn't exist.", ephemeral=True
                )

            if files_to_send:
                await interaction.send(files=files_to_send, ephemeral=True)
        else:
            await interaction.send("You can't use this command.", ephemeral=True)
