"""Runtime toggles stored in ``app_settings``.

USE_LEARNED_ALIASES — whether reviewer-confirmed shorthand (``product_aliases``)
is used at all: in the LLM prompt catalog, as a post-extraction override, and
in the per-line confidence dictionary. Off exists for demos: the same receipt
read with and without the learned dictionary shows what the corrections buy.
Learning itself (recording confirmations) is never switched off.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AppSetting

USE_LEARNED_ALIASES = "use_learned_aliases"


def get_bool(db: Session, key: str, default: bool) -> bool:
    row = db.get(AppSetting, key)
    if row is None:
        return default
    return row.value == "1"


def set_bool(db: Session, key: str, value: bool) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value="1" if value else "0"))
    else:
        row.value = "1" if value else "0"
    db.commit()


def use_learned_aliases(db: Session) -> bool:
    return get_bool(db, USE_LEARNED_ALIASES, True)
