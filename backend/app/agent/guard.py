"""Deterministic safety screen + confirmation parsing. Runs before any LLM call."""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instruction|instructions|rules|prompt|prompts|guidelines|policy|policies|system)\b",
    r"\b(system|developer|hidden|initial|original)\s+(prompt|message|instructions?)\b",
    r"\byou are (now|no longer)\b",
    r"\b(act|behave|respond) as (an? )?(unrestricted|unfiltered|admin|administrator|developer|root|dan|different)\b",
    r"\b(developer|admin|god|debug|jailbreak|dan)\s*mode\b",
    r"\bjailbreak\b",
    r"\b(reveal|print|show|repeat|output|leak)\b.{0,30}\b(your|the)\s+(instructions|prompt|rules|configuration|system)\b",
    r"\bnew (instructions|rules|persona)\b",
    r"\bpretend (to be|you are)\b",
    r"<\s*/?\s*(system|tool_data|instructions?)\s*>",
    r"\b(drop|truncate|delete)\s+table\b|;\s*--|\bunion\s+select\b",
    r"\b(api[_ ]?keys?|jwt|env(ironment)? variables?|database (url|credentials|password))\b",
]

DATA_ACCESS_PATTERNS = [
    r"\b(other|another|all|every|someone else'?s?|different)\s+(customers?|users?|buyers?|people|accounts?)\b",
    r"\b(customers?|users?)'?\s+(list|data|details|emails?|phones?|addresses|orders)\b",
    r"\b(orders?|cart|address|details|history|data)\s+(of|for|from)\s+(user|customer|account|seller)\b",
    r"\buser[_\s]?id\s*[:=]?\s*\w+",
    r"\b(seller|store|vendor)'?s?\s+(dashboard|revenue|sales figures|earnings|private|customer list|orders)\b",
    r"\b(switch|change|log ?in as|impersonate)\b.{0,20}\b(user|account|seller|customer|admin)\b",
    r"\b(all|every)\s+orders\b(?!.*\bmy\b)",
]

OFF_TOPIC_PATTERNS = [
    r"\b(write|generate|create|fix|debug)\b.{0,30}\b(code|program|script|function|essay|poem|story|song|letter|homework|assignment)\b",
    r"\b(python|javascript|java|c\+\+|sql)\s+(code|program|script|function)\b",
    r"\b(weather|forecast|stock market|crypto|bitcoin|election|president|prime minister|politics|religion)\b",
    r"\b(solve|calculate|integrate|differentiate)\b.{0,30}\b(equation|integral|math|problem)\b",
    r"\b(capital of|who (won|invented|discovered)|history of|translate)\b",
    r"\b(recipe|medical advice|diagnos|legal advice|tell me a joke)\b",
]

_inj = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
_data = [re.compile(p, re.I) for p in DATA_ACCESS_PATTERNS]
_off = [re.compile(p, re.I) for p in OFF_TOPIC_PATTERNS]

REFUSALS = {
    "injection": ("I can't follow instructions that try to change how I work. I'm OneSeller's shopping "
                  "assistant — I can help you find products, compare options, manage your cart and place orders."),
    "data_access": ("I can't access or share other people's accounts, orders or store data. I can only help "
                    "with your own shopping — searching products, your cart and your orders."),
    "off_topic": ("I'm OneSeller's shopping assistant, so I can only help with shopping on OneSeller — finding "
                  "products, comparing prices, sizes and colors, your cart and placing orders. What are you looking for?"),
    "too_long": "That message is too long. Please send a shorter question about products, your cart or orders.",
}


def screen(message: str, max_chars: int = 2000) -> str | None:
    """Return a block reason or None."""
    if len(message) > max_chars:
        return "too_long"
    if any(p.search(message) for p in _inj):
        return "injection"
    if any(p.search(message) for p in _data):
        return "data_access"
    if any(p.search(message) for p in _off):
        return "off_topic"
    return None


AFFIRM_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|y|sure|ok|okay|confirm|confirmed|i confirm|go ahead|proceed|place (it|the order|my order)|"
    r"do it|please do|yes please|absolutely|correct|that'?s right|haan|ji|jee)\b", re.I)
NEGATION_RE = re.compile(r"\b(no|not|don'?t|do not|cancel|stop|wait|hold on|never|nahi|nope|change)\b", re.I)
NEGATIVE_RE = re.compile(r"^\s*(no|nope|nah|cancel|don'?t|do not|stop|wait|not now|never ?mind|nahi)\b", re.I)


def is_affirmative(message: str) -> bool:
    """Explicit confirmation: starts with an affirmation and contains no negation/hedge."""
    m = message.strip()
    if len(m) > 120:
        return False
    if not AFFIRM_RE.search(m):
        return False
    rest = AFFIRM_RE.sub("", m, count=1)
    return not NEGATION_RE.search(rest)


def is_negative(message: str) -> bool:
    return bool(NEGATIVE_RE.search(message.strip()))
