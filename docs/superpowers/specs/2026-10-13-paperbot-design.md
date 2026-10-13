# Paperbot — Design Spec

Date: 2026-10-13
Status: Draft for review

## 1. Purpose

A personal Discord bot that turns pasted paper links into a curated research
knowledge base, replacing the current manual loop of "download PDF → put it in
`raw/` → ask Claude Code to update the wiki → ask Claude Code to summarize".

Three independent tasks, each triggered from Discord:

1. **Add paper** — paste an ACL Anthology or arXiv link → paper row in Notion + PDF in the wiki repo.
2. **Update wiki** — `update the <category> wiki` → a DeepSeek agent ingests all pending papers of that category into the wiki, commits and pushes.
3. **Summarize** — `summarize <notion page link>` → a 7-section summary written into that Notion page.

Success criteria:
- Pasting a link produces a correct Notion row (title, first author, year, link, category) and a local PDF within ~30 s.
- `update the argumentation wiki` ingests every Pending argumentation paper following the category's `CLAUDE.md` workflow, without Claude Code running, with live progress in Discord.
- `summarize …` fills the page with the 7 sections, warning when the paper is not yet in the wiki.
- The wiki stays usable by Claude Code exactly as today.

## 2. Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Hosting | Local Windows laptop first; designed to move to a server later (wiki in git from day one). |
| LLM | DeepSeek API (OpenAI-compatible), for classification, summarization and the wiki agent. |
| Sources | arXiv and ACL Anthology only (v1). |
| Discord UX | Dedicated `#papers` channel; links auto-detected; plain-text commands. |
| Wiki layout | One wiki per category: `argumentation/`, `visual/`, `other/`. No project subfolders in v1. |
| Existing wikis | The two existing wikis are merged into `argumentation/` once, during setup, with Claude Code (not by the bot). |
| PDFs | Downloaded into `<category>/raw/` at add time and committed to git. |
| Wiki edit trust | Fully automatic commit + push, with guardrails (see §6.3). |
| Summary source | Full PDF text, plus wiki context; never edits the wiki. |
| Pending papers | Summarizing allowed, with a warning in Discord and a callout on the Notion page. |

## 3. Categories

- **visual** — image-related research: image reasoning, image captioning, meme understanding/interpretation, anything involving images.
- **argumentation** — logical reasoning, logical structure, argument mining, argumentation schemes, fallacy classification, fallacious argument understanding, argument parsing, and similar.
- **other** — anything related to neither.

Cross-cutting papers (e.g. meme fallacies) are assigned the single category the LLM judges dominant; the user can change it in Notion.

## 4. Architecture

Two git repositories:

- **`paperbot`** (this repo) — the bot's code.
- **`paper-wiki`** — the knowledge base, cloned at `C:\Users\Irfan Robbani\Documents\paper-wiki`.

```
paper-wiki/
  argumentation/  raw/  templates/  wiki/  CLAUDE.md
  visual/         raw/  templates/  wiki/  CLAUDE.md
  other/          raw/  templates/  wiki/  CLAUDE.md
```

Each category's `wiki/` follows the existing convention: `index.md`, `log.md`,
`sources/`, `concepts/`, `datasets/`, `methods/`, `synthesis/`. Each
`CLAUDE.md` defines the ingest workflow and is the wiki agent's instruction set.

One Python process (`python -m paperbot`):

```
Discord listener ──> job queue (asyncio, one job at a time) ──> task handlers
```

All jobs are processed sequentially so git and Notion writes never race.
A message arriving while a job runs gets a ⏳ reaction until its turn.

### Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `discord_bot` | Listen in `#papers`, parse messages into jobs, reactions, replies, live progress message (edits throttled to ≥2 s). | `queue`, `commands` |
| `commands` | Classify a message: links (→ Add), `update the <cat> wiki` (→ Update), `summarize <url>` (→ Summarize), else ignore. Fuzzy-matches category names (e.g. "argumenation"). | — |
| `sources` | Resolve URL → canonical `PaperRef{source, id}`; fetch metadata (`title, authors, year, abs_url, pdf_url`). arXiv via `arxiv` package; ACL via `<id>.bib`. | `httpx`, `arxiv` |
| `pdf` | Download PDF; extract text with `pymupdf`. | `httpx`, `pymupdf` |
| `llm` | Thin DeepSeek client (OpenAI SDK, `base_url=https://api.deepseek.com`); classify; summarize; agent loop with tool calls and reasoning stream. | `openai` |
| `notion_store` | Schema check, find-by-link, create row, query Pending by category, update properties, replace page body. | `notion-client` |
| `wiki_repo` | Paths per category, file tools with path sandboxing, git checkpoint / rollback / commit / push. | `git` CLI |
| `citations` | Semantic Scholar "cited by" + references lookup for the Connections section. | `httpx` |
| `tasks/add`, `tasks/update_wiki`, `tasks/summarize` | Orchestrate each task. | all of the above |

## 5. Notion schema

Existing database: `208048b5cde180678e68d1f18fff76f0`.

| Property | Type | Values / notes |
|---|---|---|
| Paper | title | Paper title |
| Author | rich_text | First author |
| Year | number | Publication year |
| Link | url | Canonical abstract page URL |
| Category | select | `visual`, `argumentation`, `other` |
| Wiki | select | `Pending`, `Ingested`, `Failed` (new) |
| Summarized | checkbox | (new) |

On startup the bot validates the schema and exits with a clear message naming
any missing or mistyped property. The Notion integration must be shared with
the database.

**Notion's Category is the source of truth.** If the user changes it, task 2
moves the PDF to the matching `raw/` before ingesting.

## 6. Tasks

### 6.1 Task 1 — Add paper

Trigger: message in `#papers` containing one or more arXiv / ACL Anthology URLs.

1. **Resolve** each URL to a canonical ID:
   - arXiv: `arxiv.org/abs/2401.12345[vN]`, `arxiv.org/pdf/2401.12345[vN][.pdf]` → `2401.12345` (version stripped; canonical link `https://arxiv.org/abs/2401.12345`).
   - ACL: `aclanthology.org/2024.emnlp-main.1142/` or `…/2024.emnlp-main.1142.pdf` → `2024.emnlp-main.1142` (canonical link `https://aclanthology.org/2024.emnlp-main.1142/`).
   - Unsupported URLs → reply "unsupported source".
2. **Dedupe**: if a Notion row with the canonical Link exists → reply "already added" + page link; stop.
3. **Fetch metadata**: title, first author, year, PDF URL.
4. **Classify** with DeepSeek using title + abstract (arXiv metadata, or the ACL abstract page) and the §3 definitions. Output constrained to JSON `{category, reason}`.
5. **Download PDF** to `<category>/raw/<sanitized title>.pdf`. Not committed here. If the download fails, continue and warn; task 2/3 retry.
6. **Create Notion row**: Paper, Author, Year, Link, Category, Wiki=`Pending`, Summarized=false.
7. **Reply**: ✅ `<title>` · `<category>` · Notion link.

### 6.2 Task 3 — Summarize

Trigger: `summarize <notion page url>`. The page ID is the `p=` query
parameter (or the trailing 32-hex ID of a direct page URL).

1. Read the page properties (title, link, category, Wiki status).
2. Get the PDF from `<category>/raw/` (download if missing); extract text.
3. **Wiki context** (read-only): the category's `wiki/index.md`, the paper's source page if it exists, and up to N pages linked from it or matched by title keywords against the index. Bounded by a token budget.
4. **Citations**: Semantic Scholar lookup by arXiv ID / ACL ID / title → top references and citing papers (titles + years). Optional; skipped on failure.
5. **Summarize** with DeepSeek: paper text + wiki context + citations → JSON with exactly these keys:
   Motivation, Research question, Contribution, Method, Evidence and findings, Limitations, Connections.
   Prompt definitions:
   - Motivation — the background that led to this research.
   - Research question — the question the research tries to answer.
   - Contribution — what they propose (usually answering the research question).
   - Method — how their contribution works.
   - Evidence and findings — experimental results and their analysis.
   - Limitations — what they could not do (resources, scope, etc.).
   - Connections — which work it continues and which work continues it.
6. **Write the page body**: replace existing blocks with one heading + paragraph(s) per section. If Wiki ≠ `Ingested`, prepend a ⚠️ callout: "This paper is not in the wiki yet; Connections may be incomplete or misleading."
7. Set Summarized = true. Reply ✅ with the page link (plus the same ⚠️ warning if applicable).

If the paper is too long for the model context, the methods/experiments
sections are truncated first; abstract, introduction and conclusion are kept.

### 6.3 Task 2 — Update wiki

Trigger: `update the <category> wiki`.

1. Query Notion: Category = `<category>` and Wiki ∈ {`Pending`, `Failed`}. If none → "nothing to ingest".
2. Post a progress message in Discord; edit it as the run proceeds.
3. For each paper, in order:
   1. Ensure the PDF is in `<category>/raw/` (move if misfiled, download if missing).
   2. **Checkpoint**: record the clean git state of `<category>/`.
   3. Run the **wiki agent** (below) for this paper.
   4. On success → Notion Wiki = `Ingested`. On failure or step-limit hit → roll back `<category>/wiki/` to the checkpoint, Wiki = `Failed`, record the error, continue with the next paper.
4. Commit everything (PDFs + wiki changes) as one commit: `ingest(<category>): <title>, <title>, …`; push to GitHub. A push failure is reported but not fatal (commit stays local; next run pushes).
5. Final message: per paper ✅/❌, pages created/updated, commit hash.

**Wiki agent** (DeepSeek tool-calling loop):
- System prompt: the category's `CLAUDE.md` + contents of `templates/` + the instruction "ingest exactly this one paper, then call `finish`".
- Tools:
  - `list_files(dir)` — under `<category>/`.
  - `read_file(path)` — under `<category>/`.
  - `read_pdf_text(page_from, page_to)` — the current paper's extracted text, paged.
  - `write_file(path, content)` — only under `<category>/wiki/`; creates or overwrites.
  - `finish(summary)` — ends the loop with a short change summary.
- Guardrails: path sandboxing (no `..`, no absolute paths, no writes to `raw/`, `templates/` or `CLAUDE.md`); no delete tool; max 40 tool calls per paper; max output size per write.
- Progress: each tool call is shown as a line (`📖 read concepts/abduction.md`, `✏️ wrote sources/zebralogic.md`); the latest reasoning snippet (from DeepSeek's reasoning output, first ~150 chars) is shown as `💭 …`.

Example progress message:
```
📚 Updating argumentation wiki — 2/3 papers
✅ Flee the Flaw
⏳ ZebraLogic
   💭 "This extends the synthetic logic corpus idea to grid puzzles…"
   📖 read concepts/synthetic-logic-corpus.md
   ✏️ wrote sources/zebralogic.md
⬜ LogicPro
```

## 7. Error handling summary

| Failure | Behaviour |
|---|---|
| Unsupported / malformed URL | ❌ reply, nothing written. |
| Metadata fetch fails | ❌ reply, nothing written. |
| PDF download fails (task 1) | Row created, ⚠️ warning; task 2/3 retry download. |
| Classification fails / invalid JSON | One retry; then default `other` with ⚠️ "category guessed, please check". |
| Notion API error | ❌ reply with the error message. |
| Wiki agent error / step limit | Roll back that paper, mark `Failed`, continue. |
| Git push fails | Report; commit kept locally. |
| DeepSeek unavailable | ❌ reply; job not retried automatically. |

Every job logs to `paperbot/logs/paperbot.log`.

## 8. Configuration

`.env` (git-ignored):
```
DISCORD_TOKEN=
DISCORD_CHANNEL_ID=
NOTION_TOKEN=
NOTION_DATABASE_ID=208048b5cde180678e68d1f18fff76f0
DEEPSEEK_API_KEY=
DEEPSEEK_CHAT_MODEL=deepseek-chat
DEEPSEEK_AGENT_MODEL=deepseek-reasoner
WIKI_REPO_PATH=C:\Users\Irfan Robbani\Documents\paper-wiki
SEMANTIC_SCHOLAR_API_KEY=   # optional
```
Model names are configurable because DeepSeek's lineup changes; the
implementation must confirm the current model supports tool calling.

## 9. Setup (one-time, done with Claude Code, not the bot)

1. Create the `paperbot` and `paper-wiki` GitHub repos (private).
2. Scaffold `paper-wiki` with the three categories, each with `raw/`, `templates/`, `wiki/` skeleton, `CLAUDE.md`.
3. **Merge existing wikis into `argumentation/`**, copying (originals in `Documents\papers\` stay untouched):
   - Copy both `raw/` folders; deduplicate shared PDFs ("Flee the Flaw", "Logical Reasoning in Large Language Models A Survey").
   - Merge both `wiki/` trees: unify duplicate source/concept pages, resolve page-name collisions, rebuild `index.md`, merge `log.md` chronologically.
   - Merge both `CLAUDE.md` files and `templates/` into one argumentation version.
   - User reviews the merged wiki before the bot is enabled.
4. Write `CLAUDE.md` for `visual/` and `other/` (same conventions, category-specific scope).
5. Create the Discord bot application and `#papers` channel; create the Notion integration, share the database, add the `Wiki` and `Summarized` properties.
6. Backfill: existing Notion rows get Wiki = `Ingested` if already in the merged wiki, else `Pending`.

## 10. Testing

- Unit tests (pytest), offline with saved fixtures:
  - URL resolution: abs/pdf forms, arXiv versions, trailing slashes, unsupported hosts.
  - Metadata parsing for arXiv and ACL `.bib`.
  - Notion page-ID extraction from `?v=…&p=…` URLs.
  - Command parsing including fuzzy category matching.
  - Wiki tool sandboxing (path escapes rejected).
  - Notion payload building.
- Smoke test end-to-end against a **test Notion database** and a **scratch copy of `paper-wiki`** before pointing at the real ones.

## 11. Build order

1. Setup (§9).
2. Task 1 — Add paper.
3. Task 3 — Summarize.
4. Task 2 — Update wiki.

Each stage is usable on its own.

## 12. Out of scope (v1)

- Sources other than arXiv and ACL Anthology.
- Project subfolders inside categories.
- Multi-user use, server deployment (designed for, not done).
- Slash commands, recategorize command (change Category in Notion directly).
- Automatic retries of failed jobs.
