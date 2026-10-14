import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from openai import OpenAI

from paperbot.models import CATEGORIES

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
ChatJSON = Callable[[str, str], str]


def deepseek_chat_json(api_key: str, model: str) -> ChatJSON:
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=60)

    def chat(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return chat


@dataclass(frozen=True)
class Classification:
    category: str
    reason: str
    guessed: bool = False


CLASSIFY_SYSTEM = """You classify research papers into exactly one category.

Categories:
- visual: research involving images, e.g. image reasoning, image captioning, visual question answering, meme understanding or interpretation, anything related to images.
- argumentation: research on logical reasoning, logical structure, argument mining, argumentation schemes, fallacy classification, fallacious argument understanding, argument parsing, and similar.
- other: anything related to neither visual nor argumentation.

If a paper fits both visual and argumentation, choose the one that is its main focus.

Answer with a JSON object: {"category": "visual" | "argumentation" | "other", "reason": "<one short sentence>"}"""

_MAX_ABSTRACT = 3000


def classify_paper(chat: ChatJSON, title: str, abstract: str) -> Classification:
    user = f"Title: {title}\n\nAbstract: {abstract[:_MAX_ABSTRACT] or '(not available)'}"
    for attempt in (1, 2):
        try:
            data = json.loads(chat(CLASSIFY_SYSTEM, user))
            category = str(data.get("category", "")).strip().lower()
            if category in CATEGORIES:
                return Classification(category, str(data.get("reason", "")).strip())
            log.warning("Classifier attempt %d returned unknown category %r", attempt, category)
        except Exception:
            log.exception("Classifier attempt %d failed", attempt)
    return Classification("other", "Classifier failed; defaulted to other.", guessed=True)
