import asyncio

from paperbot.commands import AddPapers
from paperbot.discord_bot import PaperBot
from paperbot.dispatcher import Reply


class FakeDispatcher:
    def handle(self, cmd):
        return Reply(True, f"done {cmd.urls[0]}")


class FakeMessage:
    def __init__(self, fail_reply=False):
        self.fail_reply = fail_reply
        self.replies: list[str] = []
        self.reactions: list[str] = []

    async def reply(self, text, **kwargs):
        if self.fail_reply:
            raise OSError("connection reset by peer")
        self.replies.append(text)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def remove_reaction(self, emoji, user):
        pass


def test_worker_survives_a_network_error_while_replying():
    async def scenario():
        bot = PaperBot(channel_id=1, dispatcher=FakeDispatcher())
        worker = asyncio.create_task(bot._worker())
        broken, healthy = FakeMessage(fail_reply=True), FakeMessage()
        await bot._jobs.put((broken, AddPapers(("a",))))
        await bot._jobs.put((healthy, AddPapers(("b",))))
        await asyncio.wait_for(bot._jobs.join(), timeout=5)
        alive = not worker.done()
        worker.cancel()
        return healthy, alive

    healthy, alive = asyncio.run(scenario())
    assert alive
    assert healthy.replies == ["done b"]
    assert "✅" in healthy.reactions
