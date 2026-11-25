#!/usr/bin/env python
"""What is each of stage 8's five attributes actually made of?

`concepts.context.ATTRIBUTES` is a flat five-tuple, which reads as five
comparable signals. They are not — they differ in how much lexical coverage
stands behind them, and in whether any gold has ever been run against them.
Every stage-8 number should be read against the table this produces.

**Count triggers, not rules.** Counting rules gets the story materially
wrong. A medspaCy rule may carry a spaCy token
pattern, and one whose pattern is ``{"LOWER": {"IN": [...]}}`` fires on every
member of that list. FAMILY is **1 rule and 51 triggers** — the rule *named*
``family`` carries a kinship list running from ``aunt`` to ``wife``.

That mistake propagated into four files as the claim that *"Father with
myocardial infarction"* goes undetected because it contains no ``family``
token. It does not go undetected: ``father`` is in the list, and on the
development corpus this category fires 3.7 times per note in 100% of notes with
``family``/``father``/``brother``/``mother`` the commonest triggers. By trigger
count the spread is 145 / 51 / 48 / 17 / 10, so the imbalance is real but about
14x rather than the 69x a rule count implies, and FAMILY is the second best
resourced category rather than the worst.

What survives unchanged is the *validation* status, which is the column that
actually governs what may be claimed: only negation has in-domain gold.

Generated from the installed rule file rather than transcribed, so the counts
track whichever medspaCy is actually in the environment.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter
from pathlib import Path
from typing import Any

from robustehr.concepts.context import _NAMES, ATTRIBUTES
from robustehr.concepts.matcher import _neutral_cwd


def triggers_in(rule: dict[str, Any]) -> int:
    """How many distinct surface forms a rule can fire on.

    **Rule count is the wrong unit.** medspaCy rules carry an optional spaCy
    token `pattern`, and a single
    rule whose pattern is ``{"LOWER": {"IN": [...]}}`` fires on every member of
    that list. The FAMILY category is one rule and **fifty-one** triggers — the
    rule named ``family`` carries a kinship list from ``aunt`` to ``wife``. A
    disclosure counting rules therefore understated it by a factor of fifty and
    supported the false claim that *"Father with myocardial infarction"* is not
    detected. It is.
    """
    pattern = rule.get("pattern")
    if not pattern:
        return 1
    widest = 1
    for token in pattern:
        if not isinstance(token, dict):
            continue
        for value in token.values():
            if isinstance(value, dict) and "IN" in value:
                widest = max(widest, len(value["IN"]))
    return widest


CATEGORY_ATTRIBUTE = {
    "NEGATED_EXISTENCE": "is_negated",
    "POSSIBLE_EXISTENCE": "is_uncertain",
    "HISTORICAL": "is_historical",
    "HYPOTHETICAL": "is_hypothetical",
    "FAMILY": "is_family",
}

#: medspaCy's category → attribute map, mirrored from `DEFAULT_ATTRIBUTES` in
#: `medspacy/context/context.py`. Mirrored rather than imported because it is a
#: private constant, and the mirror is checked against `ATTRIBUTES` below.
#:
#: What each attribute has behind it, and how far it may be trusted. Only
#: `is_negated` has in-domain gold; the rest are disclosed rather than claimed.
STATUS = {
    "is_negated": (
        "validated",
        "assertion_accuracy.json, NegEx gold: 0.9289 negated-class F1 against a "
        "0.0000 majority-class floor.",
    ),
    "is_uncertain": (
        "measured-out-of-domain",
        "scope_accuracy.json, BioScope abstracts: F1 0.2511 at precision 0.855 "
        "and recall 0.147 — precise where it fires, blind to six hedges in "
        "seven. Read against negation on the same sentences (0.6111, versus "
        "0.9289 on clinical gold), which prices the genre shift at 0.318 F1. "
        "BioScope's clinical subcorpus is de-worded and needs the 2007 CMC text "
        "to reconstitute, so no in-domain uncertainty gold exists here. Not "
        "promoted to validated: these 18 rules are clinical hedges and the "
        "corpus is scientific writing.",
    ),
    "is_hypothetical": (
        "disclosed-unvalidated",
        "9 rules, 17 triggers, no gold. Corpus rate 6.2 cues per note, dominated "
        "by `as needed` (PRN instructions) and `if` — so most of what it fires "
        "on is discharge instructions rather than hedged findings.",
    ),
    "is_historical": (
        "disclosed-unvalidated",
        "5 rules, 10 triggers, no gold. `Hx` is covered: the `history` rule's "
        "pattern is [history, hx, hist, ho]. `status post` is absent, and it is "
        "ordinary clinical usage. Corpus rate 5.0 cues per note.",
    ),
    "is_family": (
        "disclosed-unvalidated",
        "one rule but FIFTY-ONE triggers — the rule named `family` carries a "
        "kinship list from `aunt` to `wife`, so `Father with myocardial "
        "infarction` does fire it. Measured on corpus: 3.7 cues per note in "
        "100% of notes, the commonest being family/father/brother/mother. No "
        "gold in or out of domain, so the rate is disclosed, not claimed.",
    ),
}


def rules_path() -> pathlib.Path:
    with _neutral_cwd():
        import medspacy

    # Resources sit beside the package in site-packages, not inside it.
    return pathlib.Path(medspacy.__file__).resolve().parents[1] / "resources"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    with _neutral_cwd():
        import medspacy

    root = rules_path()
    rules = json.loads((root / "en" / "context_rules.json").read_text(encoding="utf-8"))[
        "context_rules"
    ]

    by_category = Counter(r.get("category") for r in rules)
    by_triggers: Counter[str] = Counter()
    for rule in rules:
        by_triggers[rule.get("category", "")] += triggers_in(rule)
    cross = Counter((r.get("category"), r.get("direction")) for r in rules)

    attributes = {}
    for attribute in ATTRIBUTES:
        category = next(c for c, a in CATEGORY_ATTRIBUTE.items() if a == attribute)
        status, why = STATUS[attribute]
        attributes[attribute] = {
            "reported_as": _NAMES[attribute],
            "context_category": category,
            "rules": by_category.get(category, 0),
            "triggers": by_triggers.get(category, 0),
            "directions": {
                direction: n for (cat, direction), n in sorted(cross.items()) if cat == category
            },
            "status": status,
            "basis": why,
            "literals": sorted(
                r["literal"] for r in rules if r.get("category") == category and "literal" in r
            )
            if by_category.get(category, 0) <= 10
            else None,
        }

    # Other shipped languages, because the corpus carries fr-CA fixtures and the
    # French set is two orders of magnitude larger than the English one.
    languages = {}
    for path in sorted(root.glob("*/context_rules.json")):
        payload = json.loads(path.read_text(encoding="utf-8")).get("context_rules", [])
        languages[path.parent.name] = {
            "rules": len(payload),
            "categories": dict(sorted(Counter(r.get("category") for r in payload).items())),
        }

    payload = {
        "question": "What is each of stage 8's five attributes made of?",
        "why": (
            "concepts.context.ATTRIBUTES is a flat five-tuple, which reads as "
            "five comparable signals. They are not: they differ in how much "
            "lexical coverage stands behind them and in whether any gold has "
            "been run. Every stage-8 number should be read against this table."
        ),
        "count_rules_or_triggers": (
            "**triggers, not rules.** A medspaCy rule may carry a spaCy token "
            "pattern, and one whose pattern is {'LOWER': {'IN': [...]}} fires on "
            "every member of that list. FAMILY is 1 rule and 51 triggers. "
            "Counting rules understates it fifty-fold and would suggest that "
            "`Father with myocardial infarction` is undetected, which it is "
            "not. By triggers the spread is 145 / 51 / 48 "
            "/ 17 / 10, so the imbalance is real but roughly 14x rather than the "
            "69x a rule count suggests, and FAMILY is the second best resourced "
            "category rather than the worst."
        ),
        "medspacy_version": medspacy.__version__,
        "english_rules_total": len(rules),
        "english_triggers_total": sum(by_triggers.values()),
        "attributes": dict(sorted(attributes.items())),
        "missing_categories": {
            "PSEUDONEGATION": (
                "absent from the English set. `no change` and `not only` are "
                "handled implicitly by longest-match pruning "
                "(prune_on_modifier_overlap), not by explicit pseudo rules. The "
                "Dutch set is the only shipped one that uses PSEUDO."
            ),
            "CONDITIONAL": (
                "absent from the English set, and conditionality is one of the "
                "six macro-F1 metrics ShARe/CLEF 2014 asks for. It is not "
                "producible by this instrument."
            ),
        },
        "other_languages": languages,
        "how_to_read": (
            "`validated` means in-domain gold exists in this repository and the "
            "number is in validation/measurements. `measured-out-of-domain` means gold "
            "exists but in the wrong genre, so the figure bounds the attribute "
            "rather than scoring it. `disclosed-unvalidated` means the attribute "
            "is emitted and may be wrong in ways nothing here has measured. Do "
            "not aggregate across the five, and do not report a non-affirmed "
            "rate as though its components were equally reliable."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
