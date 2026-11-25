"""Table 1 and Table 2 — the shape a methods section prints.

The renderer's job is to make a hierarchy readable, so what these tests pin is
the hierarchy and the denominators rather than the wording.
"""

from __future__ import annotations

import io

from robustehr import report


def _payload() -> dict[str, object]:
    """A minimal but realistic payload: the fields the renderer keys on."""
    return {
        "corpus": "notes.csv",
        "notes": 10,
        "by_level": {
            "document": {"n": {"total": 10, "median": 1, "p25": 1, "p75": 1}},
            "token": {
                "n": {"total": 1000, "median": 100, "p25": 90, "p75": 110},
                "content": {"total": 400, "median": 40, "p25": 36, "p75": 44},
                "word": {"total": 300, "median": 30, "p25": 27, "p75": 33},
                "word_min3": {"total": 200, "median": 20, "p25": 18, "p75": 22},
                "punctuation": {"total": 600, "median": 60, "p25": 54, "p75": 66},
                "concept_covered": {
                    "total": 160,
                    "share_of_content": 0.4,
                    "median": 16,
                    "p25": 14,
                    "p75": 18,
                },
                "concept_covered_by_category": {
                    "disorder": {"tokens": 100, "share_of_content": 0.25}
                },
                "abbreviation_sense_bands": {
                    "10+": {"n": 5, "share": 0.05},
                    "1": {"n": 40, "share": 0.4},
                    "2-4": {"n": 30, "share": 0.3},
                    "0": {"n": 20, "share": 0.2},
                    "5-9": {"n": 5, "share": 0.05},
                },
                "abbreviations": {
                    "total": 100,
                    "share_of_content": 0.25,
                    "median": 10,
                    "p25": 9,
                    "p75": 11,
                },
                "abbreviations_ambiguous": {
                    "total": 40,
                    "share_of_abbreviations": 0.4,
                    "median": 4,
                    "p25": 3,
                    "p75": 5,
                },
                "abbreviations_highly_ambiguous": {
                    "total": 10,
                    "share_of_abbreviations": 0.1,
                    "median": 1,
                    "p25": 1,
                    "p75": 1,
                },
            },
        },
        "unavailable": {"span": "no UMLS index"},
    }


def _render(payload: dict[str, object]) -> str:
    buffer = io.StringIO()
    report.table1(payload, lambda line="": print(line, file=buffer))
    return buffer.getvalue()


def test_punctuation_is_a_share_of_all_tokens_not_of_content():
    """The two denominators must not be mixed.

    `word`, `numeric` and `punctuation` partition ALL tokens, while
    `concept_covered` and `abbreviations` are shares of CONTENT tokens. A first
    version divided everything by content and printed punctuation at 1.469 of
    the note — a number a reader notices and a reviewer does not.
    """
    text = _render(_payload())
    punctuation = next(line for line in text.splitlines() if "Punctuation" in line)
    assert "0.600" in punctuation, "600 of 1000 tokens, not 600 of 400 content tokens"
    covered = next(line for line in text.splitlines() if "Inside a UMLS concept" in line)
    assert "0.400" in covered, "160 of 400 content tokens"
    # No share anywhere may exceed 1: that is what a mixed denominator looks
    # like, and it is the only symptom the bug had.
    checked = 0
    for line in text.splitlines():
        if line.count("|") < 4:
            continue
        share = line.rsplit("|", 2)[-2].strip()
        if not share or not share[0].isdigit():
            continue
        checked += 1
        assert float(share) <= 1.0, f"a share above 1 means the wrong denominator: {line}"
    assert checked > 5, "the sweep found nothing to check, so it proves nothing"


def test_indentation_marks_decomposition_not_adjacency():
    """A sub-row decomposes the row above it, and depth says so.

    `word_min3` IS a subset of `word` which IS a subset of all tokens, so it
    sits two levels in. Flattening them would put an operator's denominator
    beside a total it is a fraction of.
    """
    text = _render(_payload())
    depth = {
        "Words": 1,
        "`input.typo` acts here": 2,
        "Content tokens": 1,
        "Inside a UMLS concept": 2,
        "disorder": 3,
    }
    for label, expected in depth.items():
        line = next(line for line in text.splitlines() if label in line)
        assert line.count(report.INDENT) == expected, f"{label}: {line}"
    # A level heading is bold and never indented.
    assert "| **Tokens** |" in text


def test_sense_bands_render_in_measurement_order_not_string_order():
    """`json.dumps(sort_keys=True)` sorts them as STRINGS.

    That puts `10+` between `1` and `2-4` and makes a monotone distribution
    look like noise. The payload here is deliberately shuffled.
    """
    text = _render(_payload())
    order = [b for b in report.SENSE_BANDS if f"{b} UMLS senses" in text]
    positions = [text.index(f"{b} UMLS senses") for b in order]
    assert positions == sorted(positions)
    assert order == ["0", "1", "2-4", "5-9", "10+"]


def test_what_was_not_measured_is_listed_with_its_reason():
    text = _render(_payload())
    assert "**Not measured**" in text
    assert "`span` — no UMLS index" in text


def test_table2_separates_the_runtime_set_from_the_declared_one():
    """Three numbers, and the first two are DIFFERENT SETS.

    `build()` expands seeds through the hierarchy and does not load the
    medication, finding or proposed facets, so hfpef carries 8 concepts at
    runtime against 199 declared. Printing `declared` beside `found` alone
    reads as "the set is huge and finds nothing", which blames the concept set
    when the fault is that most of it was never loaded.
    """
    payload = {
        "corpus": "notes.csv",
        "notes": 300,
        "by_group": {
            "hfpef": {
                "notes": 217,
                "phenotypes": ["hfpef"],
                "by_level": {
                    "span": {
                        "by_phenotype": {
                            "hfpef": {
                                "evidence_spans": 0,
                                "notes_with_any": 0,
                                "measured_set_recall": 0.0,
                                "by_category": {},
                            }
                        }
                    }
                },
            },
            "_coverage": {},
        },
    }
    buffer = io.StringIO()
    report.table2(
        payload,
        {"hfpef": {"medication": 53, "disorder": 36}},
        lambda x="": print(x, file=buffer),
        {"hfpef": 8},
    )
    text = buffer.getvalue()
    assert "217 positive notes" in text
    assert "8 concepts at runtime of 89 declared" in text
    assert "0 evidence spans found in 0 of these 217 notes" in text
    assert "(set recall 0.000)" in text
    # Every declared category appears even with nothing found, because a
    # missing row would read as "not looked for".
    assert "| medication | 53 | 0 | 0.00 |" in text
    assert "| disorder | 36 | 0 | 0.00 |" in text
    # And the gap is named under the table it affects, not once at the top
    # where a reader scrolling to one phenotype would miss it.
    assert "Only 8 of these 89 concepts are loaded at runtime" in text


def test_table2_without_runtime_sizes_still_renders():
    """`--from-table` may run where the hierarchy artifacts are absent. The
    runtime column degrades to an em dash rather than silently claiming the
    declared set is what looked."""
    payload = {
        "corpus": "n.csv",
        "notes": 10,
        "by_group": {
            "x": {
                "notes": 5,
                "phenotypes": ["x"],
                "by_level": {"span": {"by_phenotype": {"x": {"evidence_spans": 3}}}},
            }
        },
    }
    buffer = io.StringIO()
    report.table2(payload, {"x": {"disorder": 9}}, lambda s="": print(s, file=buffer))
    text = buffer.getvalue()
    assert "— concepts at runtime of 9 declared" in text
    assert "loaded at runtime" not in text, "no claim without the number"
