# paperbot

Discord bot that files research papers into Notion and a research wiki.
Design: `docs/superpowers/specs/2026-10-13-paperbot-design.md`.

## What works now

Paste an arXiv or ACL Anthology link (abstract page or PDF) in `#papers`.
The bot adds a row to the Notion paper database (Paper, Author, Year, Link,
Category, Wiki = Pending) and saves the PDF to `<WIKI_REPO_PATH>/<category>/raw/`.

## Setup

1. **Install**: `uv sync`
2. **Discord bot**
   - https://discord.com/developers/applications → New Application → Bot.
   - Bot page: Reset Token (this is `DISCORD_TOKEN`); enable **Message Content Intent**.
   - OAuth2 → URL Generator: scope `bot`; permissions *View Channels*, *Send Messages*,
     *Read Message History*, *Add Reactions*. Open the URL and add the bot to your server.
   - Create a `#papers` channel. Discord Settings → Advanced → Developer Mode on;
     right-click the channel → Copy Channel ID (`DISCORD_CHANNEL_ID`).
3. **Notion**
   - https://www.notion.so/my-integrations → New integration (internal) → copy the secret (`NOTION_TOKEN`).
   - Open the paper database → `•••` → Connections → add the integration.
   - Columns needed: Paper (title), Author (text), Year (number), Link (URL), Category (select or multi-select).
     The bot adds Wiki and Summarized itself if they are missing.
4. **DeepSeek**: create an API key at https://platform.deepseek.com (`DEEPSEEK_API_KEY`).
5. Copy `.env.example` to `.env` and fill it in.

## Run

```
uv run python -m paperbot
```

Logs go to `logs/paperbot.log`. Tests: `uv run pytest`.
