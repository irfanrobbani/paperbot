import json

from paperbot.llm import CLASSIFY_SYSTEM, classify_paper


class FakeChat:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_classify_returns_category_and_reason():
    chat = FakeChat(json.dumps({"category": "argumentation", "reason": "About fallacies."}))
    result = classify_paper(chat, "Flee the Flaw", "fallacy templates")
    assert (result.category, result.reason, result.guessed) == ("argumentation", "About fallacies.", False)
    system, user = chat.calls[0]
    assert system == CLASSIFY_SYSTEM
    assert "Flee the Flaw" in user and "fallacy templates" in user


def test_classify_normalizes_case():
    chat = FakeChat('{"category": " Visual ", "reason": "memes"}')
    assert classify_paper(chat, "MemeCap", "").category == "visual"


def test_classify_retries_once_after_bad_output():
    chat = FakeChat("not json", '{"category": "other", "reason": "speech"}')
    result = classify_paper(chat, "T", "A")
    assert result.category == "other" and not result.guessed
    assert len(chat.calls) == 2


def test_classify_unknown_category_then_failure_defaults_to_guessed_other():
    chat = FakeChat('{"category": "nlp"}', RuntimeError("API down"))
    result = classify_paper(chat, "T", "A")
    assert result.category == "other"
    assert result.guessed is True


def test_classify_non_object_json_is_a_failure():
    chat = FakeChat("[1, 2]", "[]")
    assert classify_paper(chat, "T", "A").guessed is True


def test_classify_truncates_long_abstract_and_marks_missing_one():
    chat = FakeChat('{"category": "other", "reason": ""}', '{"category": "other", "reason": ""}')
    classify_paper(chat, "T", "x" * 10_000)
    assert len(chat.calls[0][1]) < 3_200
    classify_paper(chat, "T", "")
    assert "(not available)" in chat.calls[1][1]


def test_system_prompt_mentions_json_and_all_categories():
    # DeepSeek JSON mode requires the word "json" in the prompt.
    assert "json" in CLASSIFY_SYSTEM.lower()
    for category in ("visual", "argumentation", "other"):
        assert category in CLASSIFY_SYSTEM
