import asyncio
import logging

import discord

from paperbot.commands import Command, parse_message
from paperbot.dispatcher import Dispatcher, Reply, chunk_message

log = logging.getLogger(__name__)

WAITING = "⏳"


class PaperBot(discord.Client):
    def __init__(self, channel_id: int, dispatcher: Dispatcher) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._channel_id = channel_id
        self._dispatcher = dispatcher
        self._jobs: asyncio.Queue[tuple[discord.Message, Command]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())

    async def on_ready(self) -> None:
        log.info("Logged in as %s; listening in channel %s", self.user, self._channel_id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.channel.id != self._channel_id:
            return
        cmd = parse_message(message.content)
        if cmd is None:
            return
        await message.add_reaction(WAITING)
        await self._jobs.put((message, cmd))

    async def _worker(self) -> None:
        while True:
            message, cmd = await self._jobs.get()
            try:
                reply = await asyncio.to_thread(self._dispatcher.handle, cmd)
            except Exception:
                log.exception("Job failed: %r", cmd)
                reply = Reply(False, "❌ Unexpected error. See logs/paperbot.log")
            try:
                for chunk in chunk_message(reply.text):
                    await message.reply(chunk, mention_author=False, suppress_embeds=True)
                await message.add_reaction("✅" if reply.ok else "❌")
                await message.remove_reaction(WAITING, self.user)
            except discord.DiscordException:
                log.exception("Could not reply in Discord")
            finally:
                self._jobs.task_done()
