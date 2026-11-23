"""Long-term, per-principal shopping preferences (minimal, non-sensitive, user-removable)."""
from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import UserMemory
from . import catalog

ALLOWED_KEYS = {"preferred_categories", "preferred_colors", "preferred_sizes", "budget_max", "notes"}
LIST_KEYS = {"preferred_categories", "preferred_colors", "preferred_sizes"}
MAX_LIST = 5


def load(db: Session, principal: str) -> dict:
    rows = db.scalars(select(UserMemory).where(UserMemory.principal == principal))
    return {r.key: r.value for r in rows}


def _upsert(db: Session, principal: str, key: str, value: str) -> None:
    row = db.scalars(select(UserMemory).where(UserMemory.principal == principal, UserMemory.key == key)).first()
    if row:
        row.value = value[:500]
    else:
        db.add(UserMemory(principal=principal, key=key, value=value[:500]))


def remember(db: Session, principal: str, key: str, value: str, *, replace: bool = False) -> dict:
    if key not in ALLOWED_KEYS:
        raise ValueError(f"Unsupported memory key: {key}")
    value = re.sub(r"\s+", " ", str(value)).strip()
    if not value:
        raise ValueError("Empty value")
    current = load(db, principal)
    if key in LIST_KEYS and not replace:
        items = [v for v in current.get(key, "").split(",") if v]
        v = value.upper() if key == "preferred_sizes" else value.lower()
        if v in items:
            items.remove(v)
        items.insert(0, v)  # most recent first
        value = ",".join(items[:MAX_LIST])
    elif key == "notes" and not replace:
        notes = [n for n in current.get("notes", "").split(" | ") if n]
        if value not in notes:
            notes.append(value[:120])
        value = " | ".join(notes[-5:])
    _upsert(db, principal, key, value)
    db.commit()
    return load(db, principal)


def forget(db: Session, principal: str, key: str | None = None) -> None:
    stmt = delete(UserMemory).where(UserMemory.principal == principal)
    if key:
        stmt = stmt.where(UserMemory.key == key)
    db.execute(stmt)
    db.commit()


PREF_RE = re.compile(r"\b(?:i (?:usually |normally |always )?(?:prefer|like|love|wear|want)|my (?:favou?rite|preferred)"
                     r"(?: colou?r| size)?(?: is)?|i(?:'m| am) (?:a )?size|remember (?:that )?i)\b", re.I)
BUDGET_RE = re.compile(r"\bmy (?:usual |typical )?budget (?:is|of)\s*(?:around |about )?(?:rs\.?|pkr)?\s*([\d,]+)\s*(k)?",
                       re.I)


def extract_preferences(text: str) -> dict:
    """Deterministic extraction of *explicitly stated* preferences ("I prefer black", "I wear size M")."""
    found: dict = {}
    if not text:
        return found
    if m := BUDGET_RE.search(text):
        n = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        found["budget_max"] = str(int(n))
    if PREF_RE.search(text):
        parsed = catalog.parse_free_text(text)
        if parsed.get("color"):
            found["preferred_colors"] = parsed["color"]
        if parsed.get("size"):
            found["preferred_sizes"] = catalog.display_size(parsed["size"])
        cats = re.findall(r"\b(shirts?|t-?shirts?|jeans|trousers|pants|dress(?:es)?|shoes|sneakers|kurtas?|"
                          r"jackets?|hoodies?|bags?|watches|watch|scarf|scarves|shalwar kameez|abayas?|caps?)\b",
                          text, re.I)
        if cats:
            found["preferred_categories"] = catalog.stem(cats[0].lower().replace("-", ""))
    return found


def profile_text(profile: dict) -> str:
    if not profile:
        return "No saved preferences yet."
    labels = {"preferred_categories": "Preferred categories", "preferred_colors": "Preferred colors",
              "preferred_sizes": "Preferred sizes", "budget_max": "Typical max budget (PKR)", "notes": "Notes"}
    return "; ".join(f"{labels.get(k, k)}: {v}" for k, v in profile.items() if k in labels)
