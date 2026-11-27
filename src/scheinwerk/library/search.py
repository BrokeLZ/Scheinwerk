"""Finding items: type, category, tags and free text (spec §17.9). No index: a fresh scan."""

from __future__ import annotations

from collections import Counter

from scheinwerk.library.ids import clean_category, clean_tag, with_parents
from scheinwerk.library.items import Item
from scheinwerk.library.root import Library


def search(
    library: Library,
    type_: str | None = None,
    category: str | None = None,
    tags: list[str] = (),
    text: str | None = None,
) -> list[Item]:
    """Items matching every given filter, by display name then id.

    `category` also finds items in its sub-categories; `tags` must all be present; every word
    of `text` must appear (any case) in the display name, id, variant names of the latest
    version, categories, tags, description or credits."""
    wanted_cat = clean_category(category) if category else None
    wanted_tags = {clean_tag(t) for t in tags}
    words = (text or "").casefold().split()
    found = []
    for item in library.items(type_):
        if wanted_cat and not any(wanted_cat in with_parents(c) for c in item.categories):
            continue
        if not wanted_tags <= set(item.tags):
            continue
        if words:
            haystack = _search_text(item)
            if not all(w in haystack for w in words):
                continue
        found.append(item)
    return sorted(found, key=lambda i: (i.name.casefold(), i.id))


def _search_text(item: Item) -> str:
    meta = item.meta
    latest = item.latest()
    variants = list(latest.variants()) if latest else []
    parts = [
        item.name,
        item.id,
        *variants,
        *item.categories,
        *item.tags,
        str(meta.get("description") or ""),
        str(meta.get("credits") or ""),
    ]
    return "\n".join(parts).casefold()


def category_counts(items: list[Item]) -> dict[str, int]:
    """Every category (parents included) -> how many of `items` are in it. Sorted."""
    counts: Counter[str] = Counter()
    for item in items:
        counts.update({p for c in item.categories for p in with_parents(c)})
    return dict(sorted(counts.items()))


def tag_counts(items: list[Item]) -> dict[str, int]:
    counts: Counter[str] = Counter(t for item in items for t in set(item.tags))
    return dict(sorted(counts.items()))
