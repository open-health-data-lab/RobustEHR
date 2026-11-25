"""Generative phonetic confusion for clinical vocabulary.

The obvious way to model speech-recognition errors is a list of confusable word
pairs. It does not work: a curated list covers the few dozen words somebody
thought to write down, so eligibility is near zero on most notes, it cannot
follow the vocabulary into a new specialty, and it has to be rebuilt from
scratch for another language.

The generative alternative works because clinical vocabulary is morphologically
compositional. Terms are assembled from affixes, and the affixes that carry the
entire clinical meaning — ``hyper``/``hypo``, ``inter``/``intra``,
``-emia``/``-uria``, ``-ectomy``/``-ostomy`` — are precisely the ones that are
acoustically near-identical. That is *why* dictation confuses them, and it means
a handful of morpheme rules generates confusions across the whole lexicon,
including terms no curator would have listed.

One rule, ``hyper ↔ hypo``, yields hypertension/hypotension,
hyperglycaemia/hypoglycaemia, hyperkalemia/hypokalemia, hypernatremia/
hyponatremia, hyperthyroidism/hypothyroidism and every other member of the
family, present and future.

A phonetic key backs this up. Rule output is accepted only when the substitute
is *acoustically close* to the original, which is what stops a morphological
coincidence from producing a substitution no speech recogniser would ever make.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

from robustehr.phonotactics import is_pronounceable
from robustehr.resources import load_yaml

PHONETIC_RESOURCE = "phonetic_rules.yaml"

_VOWELS = frozenset("aeiouy")

#: Consonant groups that sound alike and are routinely interchanged by speech
#: recognition. Applied longest-first so digraphs win over single letters.
_SOUND_GROUPS: tuple[tuple[str, str], ...] = (
    ("ph", "F"),
    ("gh", "F"),
    ("ck", "K"),
    ("ch", "X"),
    ("sh", "X"),
    ("th", "0"),
    ("qu", "K"),
    ("wr", "R"),
    ("kn", "N"),
    ("ps", "S"),
    ("c", "K"),
    ("q", "K"),
    ("k", "K"),
    ("x", "K"),
    ("z", "S"),
    ("s", "S"),
    ("f", "F"),
    ("v", "F"),
    ("b", "B"),
    ("p", "B"),
    ("d", "T"),
    ("t", "T"),
    ("g", "K"),
    ("j", "J"),
    ("m", "M"),
    ("n", "M"),
    ("l", "L"),
    ("r", "R"),
    ("w", "W"),
    ("h", ""),
)

_NON_ALPHA = re.compile("[^a-z]+")


@lru_cache(maxsize=8192)
def phonetic_key(word: str) -> str:
    """A deterministic acoustic reduction of a word.

    Soundex-family in spirit but tuned for the confusions that matter here:
    homophonic consonant groups collapse, interior vowels are dropped, and
    doubled sounds reduce. Hand-written rather than pulled from a library
    because the mapping is part of the operator's published contract — its
    content hash goes into the operator version, and a library upgrade must not
    silently change which substitutions a corpus receives.
    """
    text = _NON_ALPHA.sub("", word.lower())
    if not text:
        return ""

    first = text[0]
    encoded: list[str] = []
    index = 0
    while index < len(text):
        for group, code in _SOUND_GROUPS:
            if text.startswith(group, index):
                if code and (not encoded or encoded[-1] != code):
                    encoded.append(code)
                index += len(group)
                break
        else:
            index += 1  # a vowel: dropped after the first character
    return first.upper() + "".join(encoded)


def sounds_alike(left: str, right: str) -> bool:
    """Are two words acoustically confusable?

    Equal phonetic keys, or keys within one edit — the second case covers
    ``hyper``/``hypo``, where the vowel difference survives the reduction but
    the words remain a plausible mishearing.
    """
    a, b = phonetic_key(left), phonetic_key(right)
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    # One insertion, deletion or substitution.
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return any(longer[:cut] + longer[cut + 1 :] == shorter for cut in range(len(longer)))


class Tier(StrEnum):
    """What evidence licenses a rule's output.

    Not a confidence ranking — a statement about which gate does the work.
    """

    INTRINSIC = "intrinsic"
    """The affix is unambiguously a clinical morpheme wherever it appears, so
    phonotactics and acoustic proximity are sufficient. No vocabulary needed."""
    ATTESTED = "attested"
    """The affix collides with ordinary English, so the output must be a real
    word.

    This is a property of the error being modelled, not a workaround: a speech
    recogniser decodes to its lexicon and can only emit words it knows, so
    ``dyscharge`` is not a possible ASR output however plausible it looks. A
    typo has no such constraint, which is why the typo operator needs no
    vocabulary at all.
    """


@dataclass(frozen=True, slots=True)
class AffixRule:
    a: str
    b: str
    min_stem: int
    is_suffix: bool
    tier: Tier = Tier.INTRINSIC

    def apply(self, word: str) -> str | None:
        """Swap this rule's affix, or return ``None`` if it does not match."""
        lowered = word.lower()
        for source, target in ((self.a, self.b), (self.b, self.a)):
            # When one affix is a prefix of the other — `uret` and `ureth` —
            # the shorter also matches every word carrying the longer, and
            # applying it produces nonsense ("urethra" -> "urethhra"). The
            # longer form always wins.
            other = target if target.startswith(source) else None
            if self.is_suffix:
                if lowered.endswith(source) and len(lowered) - len(source) >= self.min_stem:
                    return word[: len(word) - len(source)] + target
            elif lowered.startswith(source) and len(lowered) - len(source) >= self.min_stem:
                if other is not None and lowered.startswith(other):
                    continue
                return target + word[len(source) :]
        return None


@dataclass(frozen=True, slots=True)
class PhoneticRules:
    affixes: tuple[AffixRule, ...]
    teen_suffix: str
    ty_suffix: str
    irregular_stems: dict[str, str]
    number_stems: frozenset[str]
    teen_range: tuple[int, int]

    def substitute(self, word: str, lexicon: frozenset[str] | None = None) -> str | None:
        """The confusable form of a word, or ``None`` if there is none.

        Rules are tried in declaration order and the first match wins, so the
        result is a pure function of the word, the resource and the lexicon —
        no sampling, no ordering surprise.

        Three independent gates, in increasing order of what they require:

        1. **Phonotactics** — is the output pronounceable? Pure algorithm, no
           data. Rejects ``prednisone`` -> ``postdnisone``.
        2. **Acoustic proximity** — is it a plausible mis-hearing? Pure
           algorithm. Rejects ``hemiplegia`` -> ``hemiparesis``, which is
           semantically related but not confusable.
        3. **Attestation** — is the output a real word? Needs ``lexicon``, and
           only for rules whose affix collides with ordinary English. A speech
           recogniser decodes to its lexicon, so ``dyscharge`` is not a possible
           output however plausible it looks.
        """
        number = self._number_word(word)
        if number is not None:
            return number
        for rule in self.affixes:
            candidate = rule.apply(word)
            if not candidate or candidate.lower() == word.lower():
                continue
            if not sounds_alike(word, candidate):
                continue
            if not is_pronounceable(candidate):
                # The splice produced a sound sequence English does not permit:
                # `post` + `dnisone`. Rejected without reference to any
                # vocabulary, because the string is impossible rather than
                # merely unattested.
                continue
            if rule.tier is Tier.ATTESTED:
                if lexicon is None:
                    continue
                if word.lower() not in lexicon or candidate.lower() not in lexicon:
                    continue
            return candidate
        return None

    def skipped_for_lack_of_lexicon(self, word: str) -> bool:
        """Would a lexical-tier rule have fired here, given a vocabulary?

        Reported by the operator so that reduced coverage is visible rather than
        looking like the corpus simply containing fewer confusable terms.
        """
        if self._number_word(word) is not None:
            return False
        for rule in self.affixes:
            if rule.tier is not Tier.ATTESTED:
                continue
            candidate = rule.apply(word)
            if (
                candidate
                and candidate.lower() != word.lower()
                and sounds_alike(word, candidate)
                and is_pronounceable(candidate)
            ):
                return True
        return False

    def substitute_digits(self, digits: str) -> str | None:
        """``15`` ↔ ``50``: the written form of the teen/ty mishearing."""
        if not digits.isdigit():
            return None
        value = int(digits)
        low, high = self.teen_range
        if low <= value <= high:
            return str((value - 10) * 10)
        if value % 10 == 0 and low <= (value // 10) + 10 <= high:
            return str((value // 10) + 10)
        return None

    def _number_word(self, word: str) -> str | None:
        """The teen/ty mishearing, bounded to actual number stems.

        The suffix alone is not enough: English is full of ``-ty`` words, and
        an unguarded rule turns "angioplasty" into "angioplasteen". The stem
        set is small and closed, so bounding it costs no generality.
        """
        lowered = word.lower()
        if lowered.endswith(self.teen_suffix):
            stem = lowered[: -len(self.teen_suffix)]
            if stem in self.number_stems:
                return self.irregular_stems.get(stem, stem) + self.ty_suffix
        if lowered.endswith(self.ty_suffix):
            stem = lowered[: -len(self.ty_suffix)]
            inverse = {v: k for k, v in self.irregular_stems.items()}
            original = inverse.get(stem, stem)
            if original in self.number_stems:
                return original + self.teen_suffix
        return None


@lru_cache(maxsize=1)
def load_rules() -> PhoneticRules:
    raw: dict[str, Any] = load_yaml(PHONETIC_RESOURCE)
    affixes = [
        AffixRule(
            entry["a"],
            entry["b"],
            int(entry["min_stem"]),
            is_suffix=is_suffix,
            tier=Tier(entry.get("tier", "intrinsic")),
        )
        for key, is_suffix in (("prefixes", False), ("suffixes", True))
        for entry in raw[key]
    ]
    numbers = raw["number_words"]
    digits = raw["digit_pairs"]["teen_range"]
    return PhoneticRules(
        affixes=tuple(affixes),
        teen_suffix=str(numbers["teen_suffix"]),
        ty_suffix=str(numbers["ty_suffix"]),
        irregular_stems={str(k): str(v) for k, v in numbers["irregular_stems"].items()},
        number_stems=frozenset(str(x) for x in numbers["stems"]),
        teen_range=(int(digits[0]), int(digits[1])),
    )


__all__ = [
    "PHONETIC_RESOURCE",
    "AffixRule",
    "PhoneticRules",
    "Tier",
    "load_rules",
    "phonetic_key",
    "sounds_alike",
]
