import nextcord
from nextcord.ext.commands import Bot, Cog
from nextcord import Interaction, Embed, slash_command
import asyncio

from quiz_manager import QuizManager, ConfigurationManager, Question, MissingConfiguration
from metin2_api import M2Wiki


CONFIGURATION_MANAGER = ConfigurationManager()


class QuizCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.quiz_manager = QuizManager(m2_wiki=M2Wiki())

    @slash_command(name="quiz")
    async def quiz(self, interaction: Interaction):
        pass

    @slash_command(name="configuration")
    async def configuration(self, interaction: Interaction):
        pass

    @quiz.subcommand(name="lancer")
    async def start_quiz(
        self,
        interaction: Interaction,
        number_of_question: int = nextcord.SlashOption(
            name="questions",
            description="Choisir le nombre de questions à poser.",
            choices=[1, 5, 10, 20, 40],
            required=True,
        ),
        config_name: str = nextcord.SlashOption(
            name="configuration",
            description="Configuration du quiz. Utiliser `/quiz configuration` pour en créer une nouvelle.",
            autocomplete_callback=CONFIGURATION_MANAGER.autocomplete_configuration,
            required=False,
        ),
    ):
        """Lance un quiz."""
        if self.quiz_manager.quiz_is_running():
            await interaction.send("Un quiz est déjà en cours.")
            return

        channel = interaction.channel
        CONFIGURATION_MANAGER.set_config(config_name)

        self.quiz_manager.start_quiz(config_manager=CONFIGURATION_MANAGER)

        await interaction.send("Lancement du quiz !")
        questions = self.quiz_manager.get_questions(number_of_question)

        for question_index, question in enumerate(questions):
            if not self.quiz_manager.quiz_is_running():
                break

            message = await self.ask_question(
                channel, question_index, question, number_of_question
            )

            while self.quiz_manager.waiting_for_answer():
                await self.wait_for_answer(message, channel, question)

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
            title=f"Question {question_index + 1} sur {number_of_question}",
            description=f"Quel est le nom de cet objet ?",
            color=0x7AFF33,
        )
        embed.set_image(url=question.image_url)

        message = await channel.send(embed=embed)
        self.quiz_manager.start_question()

        return message

    async def wait_for_answer(
        self,
        message: nextcord.message.Message,
        channel: nextcord.channel.TextChannel,
        question: Question,
    ):
        await asyncio.sleep(CONFIGURATION_MANAGER.CHECK_ANSWER_PERIOD)

        async for message in channel.history(
            limit=None, after=message, oldest_first=True
        ):
            if question.is_correct_answer(message.content):
                self.quiz_manager.end_question()
                await message.reply(
                    f"Bien joué ! La réponse exacte est **{question.answer}**."
                )
                self.quiz_manager.leaderboard.increment_score(message.author.name)
                break

        if question.show_hint():
            if question.exceed_max_hint():
                question.get_hint()
                embed = Embed(
                    title=f"Indice {question.hint_shown} sur {CONFIGURATION_MANAGER.config[CONFIGURATION_MANAGER.MAX_HINT]}",
                    description=" ".join(question.hint),
                    color=0xEDF02A,
                )
                await channel.send(embed=embed)
            else:
                self.quiz_manager.end_question()
                await channel.send(
                    f"Trop tard ! La réponse était : **{question.answer}**."
                )

    async def show_ranking(self, channel: nextcord.channel.TextChannel):
        await channel.send("Le quiz est terminé, merci d'avoir joué !")
        ranking = "\n".join(
            f"{self.quiz_manager.leaderboard.convert_rank(rank + 1)} : **{name}** ({score} point{'s' * (score > 1)})"
            for rank, (name, score) in enumerate(self.quiz_manager.leaderboard)
        )
        embed = Embed(title="Classemenet", description=ranking, color=0x33A5FF)
        await channel.send(embed=embed)

    @quiz.subcommand(name="stop")
    async def stop_quiz(self, interaction: Interaction):
        """Arrête brusquement le quiz en cours."""
        if not self.quiz_manager.quiz_is_running():
            await interaction.send("Il n'y a pas de quiz en cours.")
            return

        self.quiz_manager.end_quiz()
        await interaction.send("Le quiz a été arrêté.")

    @quiz.subcommand(name="skip")
    async def skip_question(self, interaction: Interaction):
        """Permet d'annuler la question en cours et de passer à la suivante."""
        if not self.quiz_manager.quiz_is_running():
            await interaction.send("Il n'y a pas de quiz en cours.")
            return

        if not self.quiz_manager.waiting_for_answer():
            await interaction.send("Il n'y a pas de question en cours.")
            return

        self.quiz_manager.end_question()
        await interaction.send("La question a été annulée.")

    @configuration.subcommand(name="créer")
    async def create_configuration(
        self,
        interaction: Interaction,
        config_name: str = nextcord.SlashOption(
            name="nom",
            description="Nom de la configuration.",
            required=True,
        ),
        mode: str = nextcord.SlashOption(
            name="mode",
            description="Liberté de réponse.",
            choices=CONFIGURATION_MANAGER.get_mode_choices(),
            required=True,
        ),
        time_between_hint: int = nextcord.SlashOption(
            name="temps_indice",
            description="Temps en secondes entre les indices.",
            required=True,
        ),
        max_hint: int = nextcord.SlashOption(
            name="nombre_indice",
            description="Nombre maximum d'indice.",
            required=True,
        ),
    ):
        """Permet de créer une nouvelle configuration."""
        config_name = config_name.lower()

        try:
            CONFIGURATION_MANAGER.create_new_config(config_name, mode, time_between_hint, max_hint)

        except MissingConfiguration:
            embed = Embed(
                title="Erreur",
                description=f"Le nom de configuration **{config_name}** est déjà utilisé. Veuillez en choisir un autre.",
                color=0xC02020,
            )
            await interaction.send(embed=embed)

        else:
            embed = Embed(
                title="Nouvelle configuration",
                description=f"La configuration **{config_name}** a été créé",
                color=0x7AFF33,
            )
            embed.add_field(name="Mode", value=mode, inline=False)
            embed.add_field(name="Temps entre les indices", value=time_between_hint, inline=False)
            embed.add_field(name="Nombre maximum d'indice", value=max_hint, inline=False)
            await interaction.send(embed=embed)

    @configuration.subcommand(name="supprimer")
    async def delete_configuration(
        self,
        interaction: Interaction,
        config_name: str = nextcord.SlashOption(
            name="configuration",
            description="Non de la configuration à supprimer.",
            autocomplete_callback=CONFIGURATION_MANAGER.autocomplete_configuration_delete,
            required=True,
        ),
    ):
        """Permet de supprimer une configuration."""
        if config_name == CONFIGURATION_MANAGER.DEFAULT:
            await interaction.send("Vous ne pouvez pas supprimer la configuration par défaut.")
            return
        
        try:
            CONFIGURATION_MANAGER.delete_config(config_name)

        except MissingConfiguration:
            embed = Embed(
                title="Erreur",
                description=f"Le nom de configuration **{config_name}** n'existe pas.",
                color=0xC02020,
            )
            await interaction.send(embed=embed)

        else:
            await interaction.send(
                f"La configuration **{config_name}** a été supprimée avec succès."
            )

    @configuration.subcommand(name="liste")
    async def configuration_list(
        self,
        interaction: Interaction,
    ):
        """Liste des configurations ajoutés."""
        embed = Embed(
            title="Liste des configurations",
            color=0x7AFF33,
            description="* "
            + "\n* ".join(
                config_name for config_name in CONFIGURATION_MANAGER.saved_config.keys()
            ),
        )

        await interaction.send(embed=embed)

    @configuration.subcommand(name="détails")
    async def configuration_info(
        self,
        interaction: Interaction,
        config_name: str = nextcord.SlashOption(
            name="configuration",
            description="Non de la configuration.",
            autocomplete_callback=CONFIGURATION_MANAGER.autocomplete_configuration,
            required=True,
        ),
    ):
        """Affiche les paramètres d'une configuration."""
        try:
            config = CONFIGURATION_MANAGER.get_config(config_name)

        except MissingConfiguration:
            embed = Embed(
                title="Erreur",
                description=f"Le nom de configuration **{config_name}** n'existe pas.",
                color=0xC02020,
            )
            await interaction.send(embed=embed)

        else:
            embed = Embed(
                title="Détails de la configuration",
                description=f"La configuration **{config_name}** possède les paramètres suivants.",
                color=0x7AFF33,
            )

            for key, value in config.items():
                embed.add_field(
                    name=CONFIGURATION_MANAGER.convert(key).capitalize(),
                    value=CONFIGURATION_MANAGER.convert(value),
                    inline=False,
                )

            await interaction.send(embed=embed)


def setup(bot: Bot):
    bot.add_cog(QuizCog(bot))
