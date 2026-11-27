"""Match displayed wording when searching titles from earlier revisions."""
from pathlib import Path
import json
import re

WORDS = json.loads((Path(__file__).resolve().parents[1] / 'display_labels.json').read_text(encoding='utf-8'))
ZH = re.compile('|'.join(sorted(map(re.escape, WORDS['zh']), key=len, reverse=True)))
EN = re.compile(r'(?<![\w.-])(?:' + '|'.join(map(re.escape, WORDS['en'])) + r')(?![\w-]|\.\w)', re.I | re.A)


def display_text(value: str) -> str:
    def english(match):
        old = match[0]
        new = WORDS['en'][old.lower()]
        return new.upper() if old.isupper() else new.capitalize() if old[0].isupper() else new

    return EN.sub(english, ZH.sub(lambda match: WORDS['zh'][match[0]], value))


def matches_display_text(value: str, query: str) -> bool:
    return query in value.casefold() or query in display_text(value).casefold()
