import nextcord
from nextcord.ext import tasks

from src.quiz_manager import Quiz, QuizManager
from src.config import ConfigurationManager as cm


class RegistrationButton(nextcord.ui.View):
    MESSAGE_OPEN = "Registrations will close in {remaining_time} second{plural}."
    MESSAGE_CLOSE = "Registrations are closed."

    def __init__(
        self, quiz_manager: QuizManager, quiz: Quiz, embed: nextcord.Embed, registration_time: int
    ):
        super().__init__()
        self.quiz_manager = quiz_manager
        self.quiz = quiz
        self.embed = embed
        self.registration_time = registration_time
        self.embed_value = ""

    async def update(self, message: nextcord.Message):
        await self.registration_timer.start(message)

    @tasks.loop(seconds=1)
    async def registration_timer(self, message: nextcord.Message):
        remaining_time = self.registration_time - self.registration_timer.current_loop
        plural = "s" * (remaining_time >= 2)

        self.embed.set_footer(
            text=self.MESSAGE_OPEN.format(remaining_time=remaining_time, plural=plural)
        )
        await message.edit(embed=self.embed, view=self)

        if not remaining_time or not self.quiz.is_running:
            button: nextcord.Button = self.children[0]
            button.disabled = True
            self.embed.set_footer(text=self.MESSAGE_CLOSE)
            await message.edit(embed=self.embed, view=self)
            self.registration_timer.stop()

    @nextcord.ui.button(
        label="Registration", style=nextcord.ButtonStyle.success, emoji="🎟️"
    )
    async def button_callback(self, _, interaction: nextcord.Interaction):
        user = interaction.user
        self.quiz.players.add(user)
        self.embed_value += f"\n- {user.display_name} ({self.quiz_manager.get_elo(interaction.guild_id, user)})"

        self.embed.set_field_at(
            index=2,
            name="Participants",
            value=self.embed_value,
            inline=False,
        )


class DropDown(nextcord.ui.StringSelect):
    def __init__(self, guild_id: int, config: cm):
        self.guild_id = guild_id
        self.config = config

        super().__init__(
            placeholder="Choose languages",
            min_values=1,
            max_values=len(config.langs_data.keys()),
            options=[
                nextcord.SelectOption(
                    label=lang,
                    emoji=data["emoji"],
                    default=lang in config.get_default_langs(guild_id),
                )
                for lang, data in config.langs_data.items()
            ],
        )

    async def callback(self, interaction: nextcord.Interaction):
        self.config.update_allowed_langs(self.guild_id, self.values)
        await interaction.send(
            "Languages have been successfully changed.", ephemeral=True
        )
