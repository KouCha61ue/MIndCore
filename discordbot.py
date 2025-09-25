import discord
from discord import app_commands
from discord.abc import Messageable
import google.generativeai as genai

import asyncio
import logging
from typing import Dict

import config


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mindcare")

SYSTEM_PROMPT = (
    "あなたは心のケアに寄り添うカウンセラーAIです。"
    "利用者の感情や状況を丁寧に読み取って、やさしく共感しながら"
    "長文は控えてください"
    "回答は友達感覚で、安心感のあるトーンにしてください。"
    "医学的診断や投薬の指示は行わず、必要に応じて専門家への相談を勧めてください。"
)


GENERATION_CONFIG = {
    "temperature": 0.8,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 1024,
}


class CounselingAgent:
    def __init__(self, model_name: str = "gemini-2.5-flash") -> None:
        if not config.GEMINI:
            raise RuntimeError("GEMINI_KEY is not set. Please check your .env file.")

        genai.configure(api_key=config.GEMINI)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
        )
        self._sessions: Dict[str, genai.ChatSession] = {}

    def _get_session(self, session_id: str) -> genai.ChatSession:
        chat = self._sessions.get(session_id)
        if chat is None:
            chat = self.model.start_chat(history=[])
            self._sessions[session_id] = chat
        return chat

    def reset(self, session_id: str) -> None:
        if session_id in self._sessions:
            del self._sessions[session_id]

    async def generate(self, session_id: str, prompt: str) -> str:
        chat = self._get_session(session_id)

        def _invoke() -> str:
            response = chat.send_message(prompt, generation_config=GENERATION_CONFIG)
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Empty response from Gemini")
            return text

        try:
            text = await asyncio.to_thread(_invoke)
        except Exception as exc:
            logger.exception("Gemini request failed: %s", exc)
            raise

        return text


if not config.TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Please check your .env file.")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
assistant = CounselingAgent()
tree = app_commands.CommandTree(client)
allowed_channel_ids = set(config.ALLOWED_CHANNEL_IDS)
_tree_synced = False


def _has_manage_channels(actor: object) -> bool:
    permissions = getattr(actor, "guild_permissions", None)
    return bool(permissions and permissions.manage_channels)


def _is_allowed_channel(channel: Messageable) -> bool:
    if isinstance(channel, discord.DMChannel):
        return True
    return getattr(channel, "id", None) in allowed_channel_ids


def _should_respond(message: discord.Message) -> bool:
    if isinstance(message.channel, discord.DMChannel):
        return True
    if not _is_allowed_channel(message.channel):
        return False
    return True


def _clean_prompt(message: discord.Message) -> str:
    prompt = message.content.strip()
    if client.user is None:
        return prompt
    for mention in message.mentions:
        if mention == client.user:
            prompt = prompt.replace(mention.mention, "").strip()
            prompt = prompt.replace(f"@{client.user.name}", "").strip()
    return prompt


@client.event
async def on_ready() -> None:
    global _tree_synced
    assert client.user is not None
    if not _tree_synced:
        try:
            await tree.sync()
            for guild in client.guilds:
                try:
                    await tree.sync(guild=guild)
                except Exception:
                    logger.exception("Failed to sync commands for guild %s", guild.id)
        except Exception:
            logger.exception("Failed to sync application commands")
        else:
            _tree_synced = True
    logger.info("Logged in as %s (%s)", client.user.name, client.user.id)


@tree.command(name="join", description="指定したチャンネルでBotの応答を有効にします")
@app_commands.default_permissions(manage_channels=True)
async def register_channel(interaction: discord.Interaction) -> None:
    channel = interaction.channel
    if channel is None or isinstance(channel, discord.DMChannel):
        await interaction.response.send_message(
            "このコマンドはサーバー内のテキストチャンネルで実行してください。",
            ephemeral=True,
        )
        return

    if not _has_manage_channels(interaction.user):
        await interaction.response.send_message(
            "チャンネルを登録する権限がありません。サーバー管理者に相談してください。",
            ephemeral=True,
        )
        return

    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        await interaction.response.send_message(
            "このチャンネルを登録できませんでした。別のチャンネルでお試しください。",
            ephemeral=True,
        )
        return

    if channel_id in allowed_channel_ids:
        await interaction.response.send_message(
            "すでにこのチャンネルでお話しできるようになっています。",
            ephemeral=True,
        )
        return

    allowed_channel_ids.add(channel_id)
    await interaction.response.send_message(
        "このチャンネルでやり取りするように設定しました。よろしくお願いします。",
        ephemeral=True,
    )


@tree.command(name="leave", description="指定したチャンネルでのBot応答を無効にします")
@app_commands.default_permissions(manage_channels=True)
async def unregister_channel(interaction: discord.Interaction) -> None:
    channel = interaction.channel
    if channel is None or isinstance(channel, discord.DMChannel):
        await interaction.response.send_message(
            "このコマンドはサーバー内のテキストチャンネルで実行してください。",
            ephemeral=True,
        )
        return

    if not _has_manage_channels(interaction.user):
        await interaction.response.send_message(
            "チャンネルの登録解除権限がありません。サーバー管理者に相談してください。",
            ephemeral=True,
        )
        return

    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        await interaction.response.send_message(
            "このチャンネルの登録を解除できませんでした。別のチャンネルでお試しください。",
            ephemeral=True,
        )
        return

    if channel_id not in allowed_channel_ids:
        await interaction.response.send_message(
            "このチャンネルはもともと登録されていませんでした。",
            ephemeral=True,
        )
        return

    allowed_channel_ids.discard(channel_id)
    await interaction.response.send_message(
        "このチャンネルでの応答を停止しました。必要になったらまた /join してくださいね。",
        ephemeral=True,
    )


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    raw_prompt = _clean_prompt(message)
    command = raw_prompt.lower()

    if command in {"!join", "/join"}:
        if isinstance(message.channel, discord.DMChannel):
            await message.channel.send("このコマンドはサーバー内のテキストチャンネルで使ってください。")
            return
        if message.guild is None or not _has_manage_channels(message.author):
            await message.channel.send("権限を確認できなかったため、このチャンネルを登録できませんでした。")
            return
        if message.channel.id in allowed_channel_ids:
            await message.channel.send("すでにこのチャンネルでお話しできます。")
            return
        allowed_channel_ids.add(message.channel.id)
        await message.channel.send("このチャンネルでやり取りするように設定しました。よろしくお願いします。")
        return

    if command in {"!leave", "/leave"}:
        if isinstance(message.channel, discord.DMChannel):
            await message.channel.send("このコマンドはサーバー内のテキストチャンネルで使ってください。")
            return
        if message.guild is None or not _has_manage_channels(message.author):
            await message.channel.send("権限を確認できなかったため、このチャンネルの登録を解除できませんでした。")
            return
        if message.channel.id not in allowed_channel_ids:
            await message.channel.send("このチャンネルはもともと登録されていませんでした。")
            return
        allowed_channel_ids.discard(message.channel.id)
        await message.channel.send("このチャンネルでの応答を停止しました。必要になったらまた /join してくださいね。")
        return

    if not _should_respond(message):
        return

    prompt = raw_prompt
    if not prompt:
        await message.channel.send("何についてお話ししますか？遠慮なく教えてくださいね。")
        return

    session_id = (
        f"dm:{message.author.id}"
        if isinstance(message.channel, discord.DMChannel)
        else f"guild:{message.guild.id}:channel:{message.channel.id}:user:{message.author.id}"
    )

    if prompt.lower() in {"!reset", "reset", "リセット"}:
        assistant.reset(session_id)
        await message.channel.send("会話履歴をリセットしました。いつでもお話しくださいね。")
        return

    async with message.channel.typing():
        try:
            reply = await assistant.generate(session_id, prompt)
        except Exception:
            await message.channel.send(
                "ごめんなさい、今はお手伝いができないみたいです。少し時間を置いてから"
                "もう一度試してもらえると嬉しいです。"
            )
            return

    if isinstance(message.channel, discord.DMChannel):
        await message.channel.send(reply)
    else:
        await message.reply(reply, mention_author=False)


if __name__ == "__main__":
    client.run(config.TOKEN)
