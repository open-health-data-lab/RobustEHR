"""The ``robustehr`` command line.

Written against ``argparse`` rather than a CLI framework on purpose: the package
already asks users to install a terminology and a corpus, and every dependency
added to the core is one more thing that can differ between the machine that
produced a result and the machine trying to reproduce it.

Commands are grouped by what they need:

* ``taxonomy``, ``segment`` — nothing beyond the package.
* ``applicability`` — a corpus. Answers "does this operator apply here at all",
  which must be settled before any dose is interpretable.
* ``concepts`` — a local UMLS installation, used once at build time to produce a
  vocabulary artifact that runtime then reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any, TextIO

from robustehr import taxonomy as taxonomy_module
from robustehr.types import PhenotypeScope
from robustehr.version import SCHEMA_VERSION, __version__

DEFAULT_LEXICON_PATH = Path("data/lexicon/clinical_tokens.txt")


def _emit(payload: object, *, path: Path | None = None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if path is None:
        print(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)


# -- taxonomy ---------------------------------------------------------------


def cmd_taxonomy(args: argparse.Namespace) -> int:
    from robustehr.ops import registry

    registry.register_builtins()
    if args.phenotypes:
        from robustehr.concepts.phenotype import load_definitions

        definitions = load_definitions()
        width = max(len(n) for n in definitions)
        print(f"{'name':<{width}}  {'set recall':>10}  {'gold spans':>10}  seeds")
        for name, d in definitions.items():
            recall = "—" if d.measured_set_recall is None else f"{d.measured_set_recall:.3f}"
            spans = "—" if d.gold_evidence_spans is None else str(d.gold_evidence_spans)
            print(f"{name:<{width}}  {recall:>10}  {spans:>10}  {','.join(d.seeds)}")
            if d.note:
                print(f"{'':<{width}}  {d.note}")
        print(
            "\nset recall is the fraction of expert-annotated evidence the matcher\n"
            "recovers with a concept inside the set. Every protect-mode result is\n"
            "conditional on it: evidence never found is evidence never protected,\n"
            "and the run still reports evidence_touch = 0."
        )
        return 0
    if args.describe:
        entries = [e for e in taxonomy_module.build()["operators"] if e["id"] == args.describe]
        if not entries:
            print(f"unknown operator {args.describe!r}", file=sys.stderr)
            return 2
        _emit(entries[0])
        return 0
    if args.yaml:
        # `write`, not `print`. `to_yaml()` already ends in a newline, and the
        # documented way to regenerate the committed lockfile is to redirect this
        # into it — so an extra trailing newline here makes the command produce a
        # file that fails the drift test it exists to satisfy.
        sys.stdout.write(taxonomy_module.to_yaml())
        return 0
    rows = taxonomy_module.summary_rows()
    width = max(len(r["id"]) for r in rows)
    for row in rows:
        print(f"{row['id']:<{width}}  {row['channel']:<10} {row['contract']}")
    return 0


# -- segment ----------------------------------------------------------------


def cmd_segment(args: argparse.Namespace) -> int:
    from robustehr.document import Document

    text = Path(args.path).read_text(encoding="utf-8")
    doc = Document.from_text(text, uid=Path(args.path).stem)
    _emit({"provenance": doc.provenance(), "units": doc.unit_counts()})
    return 0


# -- applicability ----------------------------------------------------------


def cmd_applicability(args: argparse.Namespace) -> int:
    """How many units of each kind does this corpus actually contain?

    The honest "does this even apply here" table. An operator with a median of
    zero eligible units on a corpus is not a weak operator on that corpus, it is
    an inapplicable one, and a severity sweep over it produces a row of nulls
    that must not be averaged into anything.
    """
    from robustehr.corpus import read_documents

    per_kind: dict[str, list[int]] = {}
    notes = 0
    for doc in read_documents(Path(args.corpus), limit=args.limit):
        notes += 1
        for kind, count in doc.unit_counts().items():
            per_kind.setdefault(kind, []).append(count)

    if notes == 0:
        print("corpus contained no readable notes", file=sys.stderr)
        return 1

    summary = []
    for kind, counts in sorted(per_kind.items()):
        counts.sort()
        summary.append(
            {
                "unit_kind": kind,
                "median": counts[len(counts) // 2],
                "p25": counts[len(counts) // 4],
                "p75": counts[(3 * len(counts)) // 4],
                "notes_with_any": round(sum(1 for c in counts if c) / len(counts), 4),
                "total": sum(counts),
            }
        )
    _emit({"notes": notes, "units": summary}, path=args.out)
    return 0


# -- concepts ---------------------------------------------------------------


def cmd_concepts_build_lexicon(args: argparse.Namespace) -> int:
    """Derive the clinical vocabulary from a local UMLS installation.

    Runs once. The artifact it writes is what runtime reads, so no user needs
    DuckDB or 43 GB of RRF files to *apply* corruption — only to rebuild the
    vocabulary, or to verify that the shipped manifest hash matches what their
    own copy of the same release produces.
    """
    import duckdb

    from robustehr.concepts.umls import UmlsRelease, build_clinical_lexicon, export_lexicon
    from robustehr.lexicon import load_morphology

    release = UmlsRelease.discover(Path(args.umls))
    con = duckdb.connect(str(args.db) if args.db else ":memory:")
    counts = build_clinical_lexicon(
        release,
        con=con,
        closed_class=load_morphology().closed_class,
    )
    manifest = export_lexicon(con, Path(args.out), release)
    _emit({"build": counts, "manifest": manifest})
    return 0


def cmd_concepts_validate(args: argparse.Namespace) -> int:
    """Measure the morphological fallback against the terminology.

    This is a reportable result, not a self-check: it quantifies what a run
    without a terminology costs, which is the number that belongs next to any
    clinical-hit rate produced in that mode.
    """
    from robustehr.concepts.validate import measure_fallback
    from robustehr.corpus import read_documents
    from robustehr.lexicon import load_clinical_lexicon

    reference = load_clinical_lexicon(Path(args.lexicon))
    documents = list(read_documents(Path(args.corpus), limit=args.limit))
    report = measure_fallback(documents, reference)
    _emit({"notes": len(documents), **report.to_dict()}, path=args.out)
    return 0


def cmd_concepts_classify(args: argparse.Namespace) -> int:
    """Show how a corpus's tokens classify, and by which method.

    The evidence breakdown is the useful half. A result resting mostly on
    ``morphology`` evidence means the terminology was not installed, and should
    be read with the numbers from ``concepts validate`` in hand.
    """
    from robustehr.corpus import read_documents
    from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
    from robustehr.segment.tokens import TokenKind

    lexicon = (
        load_clinical_lexicon(Path(args.lexicon))
        if args.lexicon and Path(args.lexicon).exists()
        else DEFAULT_LEXICON
    )
    classes: Counter[str] = Counter()
    evidence: Counter[str] = Counter()
    examples: dict[str, set[str]] = {}
    for doc in read_documents(Path(args.corpus), limit=args.limit):
        for token in doc.tokens:
            result = lexicon.classify(token)
            classes[result.token_class.value] += 1
            evidence[result.evidence.value] += 1
            if token.kind is TokenKind.WORD:
                bucket = examples.setdefault(result.token_class.value, set())
                if len(bucket) < 15:
                    bucket.add(token.lower)
    _emit(
        {
            "lexicon_source": lexicon.source,
            "token_class": dict(classes.most_common()),
            "evidence": dict(evidence.most_common()),
            "examples": {k: sorted(v) for k, v in sorted(examples.items())},
        },
        path=args.out,
    )
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Profile how degraded a corpus already is, before any corruption.

    The other half of the dose story. A robustness result that ignores baseline
    attributes to the operator whatever the notes brought with them, and the
    profile is what lets results be stratified instead.
    """
    from robustehr.corpus import read_documents
    from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
    from robustehr.metrics.dqp import corpus_frequencies, profile, tertiles

    lexicon = (
        load_clinical_lexicon(Path(args.lexicon))
        if args.lexicon and Path(args.lexicon).exists()
        else DEFAULT_LEXICON
    )
    docs = list(read_documents(Path(args.corpus), limit=args.limit))
    if not docs:
        print("corpus contained no readable notes", file=sys.stderr)
        return 1
    frequencies = corpus_frequencies(docs, lexicon)
    profiles = [profile(d, lexicon, frequencies) for d in docs]

    def summary(name: str, values: Sequence[Fraction | None]) -> dict[str, object]:
        present = sorted(v for v in values if v is not None)
        if not present:
            return {"metric": name, "status": "not_measured"}
        return {
            "metric": name,
            "min": round(float(present[0]), 5),
            "median": round(float(present[len(present) // 2]), 5),
            "max": round(float(present[-1]), 5),
            "n": len(present),
        }

    metrics: dict[str, list[Fraction | None]] = {
        "misspelling_rate": [p.misspelling_rate for p in profiles],
        "unrecognized_rate": [p.unrecognized_rate for p in profiles],
        "whitespace_noise_rate": [p.whitespace_noise_rate for p in profiles],
        "deid_density": [p.deid_density for p in profiles],
    }
    strata: dict[str, list[float]] = {}
    for name, values in metrics.items():
        present = [v for v in values if v is not None]
        if present:
            lo, hi = tertiles(present)
            strata[name] = [round(float(lo), 5), round(float(hi), 5)]

    payload: dict[str, object] = {
        "notes": len(profiles),
        "lexicon_source": lexicon.source,
        "lexical_dimension_measured": profiles[0].is_measured,
        "distributions": [summary(n, v) for n, v in metrics.items()],
        "tertile_cuts": strata,
        "hard_wrapped_notes": sum(1 for p in profiles if p.is_hard_wrapped),
        "notes_with_mixed_header_styles": sum(1 for p in profiles if p.header_styles > 1),
        "notes_with_mixed_deid_schemes": sum(1 for p in profiles if p.deid_schemes > 1),
    }
    if args.per_note:
        payload["profiles"] = [p.to_row() for p in profiles]
    _emit(payload, path=args.out)
    return 0


def cmd_run(  # noqa: PLR0911,PLR0912,PLR0915 - one guard per misconfiguration, each named
    args: argparse.Namespace,
) -> int:
    """Apply a severity sweep and persist edit scripts, doses and a manifest.

    Writes no note text — see :mod:`robustehr.store` for why that is enforced
    rather than trusted.
    """
    from robustehr.config import ConfigError, Recipe
    from robustehr.corpus import read_records, select_records
    from robustehr.document import Document
    from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
    from robustehr.ops import registry
    from robustehr.ops.base import Scope
    from robustehr.runner import apply_operator, compose_operators, severity_ladder
    from robustehr.store import write_run
    from robustehr.target import parse_all as parse_targets
    from robustehr.target import phenotypes_named, wants_any_phenotype

    registry.register_builtins()

    recipe = None
    if getattr(args, "config", None):
        try:
            recipe = Recipe.load(Path(args.config))
            recipe.check()
        except (ConfigError, FileNotFoundError) as exc:
            print(f"cannot load recipe: {exc}", file=sys.stderr)
            return 2
        # The recipe owns what the flags would otherwise set. Applied onto the
        # namespace rather than threaded separately so that every downstream
        # read — the target check below, the manifest, `_wants_concepts` —
        # sees one configuration rather than two that might disagree.
        args.operators = list(recipe.operators())
        args.salt = recipe.seed
        if recipe.target.phenotype:
            args.phenotype = sorted({*(args.phenotype or []), recipe.target.phenotype})
        if recipe.target.mode != "random":
            args.target = [recipe.target.to_target().canon()]

    op_ids = args.operators or list(registry.all_ids())
    unknown = [o for o in op_ids if o not in registry.all_ids()]
    if unknown:
        print(f"unknown operator(s): {unknown}", file=sys.stderr)
        return 2

    lexicon = (
        load_clinical_lexicon(Path(args.lexicon))
        if args.lexicon and Path(args.lexicon).exists()
        else DEFAULT_LEXICON
    )
    target = parse_targets(args.target or ["all"])
    # A target naming a phenotype must have that phenotype declared, or
    # `PhenotypeEvidence` consults an empty index and admits nothing — a
    # configuration error that reads as an empty corpus. Naming it in the target
    # IS the declaration; `--phenotype` stays available for `--phenotype-scope`.
    named = phenotypes_named(target)
    args.phenotype = sorted(set(args.phenotype or []) | named)
    if wants_any_phenotype(target) and not args.phenotype:
        print(
            "--target pheno=* means 'any declared phenotype' and none was "
            "declared. Name one with --phenotype, or target a phenotype by "
            "name with --target pheno=NAME",
            file=sys.stderr,
        )
        return 2
    scope = Scope(target=target)
    ladder = severity_ladder(*args.severities)
    try:
        params_by_op = _operator_params(
            args.param or [], recipe.params if recipe is not None else {}, op_ids
        )
    except ValueError as exc:
        print(f"cannot read operator parameters: {exc}", file=sys.stderr)
        return 2

    phenotype_scope = PhenotypeScope(args.phenotype_scope)
    if phenotype_scope is not PhenotypeScope.AGNOSTIC and not args.phenotype:
        print(
            f"--phenotype-scope {phenotype_scope.value} needs at least one "
            "--phenotype, or it would silently degrade to agnostic",
            file=sys.stderr,
        )
        return 2
    try:
        declared = _load_phenotypes(args)
    except (FileNotFoundError, KeyError) as exc:
        print(f"cannot build phenotypes: {exc}", file=sys.stderr)
        return 2

    doses, edit_groups = [], []
    corrupted: dict[tuple[str, str, str], str] = {}
    records, column_map = read_records(Path(args.corpus), limit=args.limit)
    selected = (
        select_records(
            records,
            n=recipe.documents.n,
            fraction=recipe.documents.fraction,
            salt=args.salt,
        )
        if recipe is not None
        else tuple(records)
    )
    docs = [Document.from_text(r.text, uid=r.note_id) for r in selected]
    for doc in docs:
        evidence = _document_evidence(doc, declared, args)
        # The swap the span-based target design existed for. Without it every
        # `cat=` / `tui=` / `concept` target silently falls back to per-token
        # lookup, so `chest pain` resolves as an anatomy token beside a symptom
        # token rather than as one Sign or Symptom. Built once per note and
        # shared across every operator and severity cell.
        mentions = _document_mentions(doc, args)
        common = {
            "lexicon": lexicon,
            "run_id": args.run_id,
            "salt": args.salt,
            "phenotypes": evidence,
            "phenotype_scope": phenotype_scope,
            "mentions": mentions,
            # Proportional allocation across semantic categories, when the
            # recipe asked for it. Only reaches word/char operators, since a
            # structural unit belongs to no category.
            "stratify_by": recipe.target.stratify_by if recipe is not None else None,
        }
        # A recipe may give this note a subset of the operators, and may give
        # each of them a different severity — "medium" is 10% of words for a
        # typo and 50% of headers for a deletion. Flag-driven runs keep the
        # single ladder they always had.
        note_ops = recipe.operators_for(doc.uid) if recipe is not None else op_ids
        for severity in ladder:
            cells = [
                (op_id, recipe.severity_for(op_id) if recipe is not None else severity)
                for op_id in note_ops
            ]
            if args.compose:
                # One cell per severity, every operator merged onto the same
                # note. Each still proposes against the pristine document, so
                # the stored edit script references original offsets and replay
                # is unchanged — see runner.compose_operators.
                built = [(registry.get(op_id)(), registry.get(op_id)().meta) for op_id, _ in cells]
                results = [
                    compose_operators(
                        doc, built, severity, scope=scope, params_by_op=params_by_op, **common
                    )
                ]
            else:
                results = [
                    apply_operator(
                        doc,
                        registry.get(op_id)(),
                        registry.get(op_id)().meta,
                        cell_severity,
                        scope=_scope_for(scope, recipe, op_id),
                        params=params_by_op.get(op_id),
                        **common,
                    )
                    for op_id, cell_severity in cells
                ]
            for result in results:
                doses.append(result.dose)
                edit_groups.append(result.apply_result.applied)
                if args.emit_text:
                    corrupted[(doc.uid, result.dose.op_id, result.dose.severity_canon)] = (
                        result.text
                    )
            if recipe is not None:
                # A recipe fixes one severity per operator, so iterating the
                # ladder would re-run identical cells and write each edit twice.
                break

    _warn_empty_aim(doses, scope.resolved_target().canon(), _document_mentions_available(args))

    if args.emit_text:
        written = _emit_corrupted(Path(args.emit_text), corrupted, args.i_understand_the_licence)
        if written is None:
            return 2

    manifest = write_run(
        Path(args.out),
        run_id=args.run_id,
        doses=doses,
        edits=edit_groups,
        corpus=Path(args.corpus).name,
        texts={doc.uid: doc.text for doc in docs},
        extra={
            "operators": sorted(op_ids),
            "operator_params": {
                op: dict(sorted(p.items())) for op, p in sorted(params_by_op.items())
            },
            "severities": list(args.severities),
            "target": scope.resolved_target().canon(),
            "salt": args.salt,
            "lexicon_source": lexicon.source,
            "phenotype_scope": phenotype_scope.value,
            "phenotypes": sorted(args.phenotype or []),
            # The conditionality travels with the artifact. A protect-mode run
            # is only as strong as the matcher's recall of that phenotype's
            # evidence, and a reader of the manifest must not have to go looking.
            "phenotype_measured_set_recall": _declared_recall(args.phenotype or []),
            # Everything a phenotype target was built from, or null for an
            # agnostic run. No operator version covers these resources, and two
            # runs built under different targets select different units.
            "targeting": _targeting_manifest(args),
            # Each of these changes what a run selected: the column mapping
            # decides which field was read as text, `--limit` decides how much
            # of the file was seen at all, and the matcher config decides what
            # a `cat=` target could even match.
            "column_map": column_map.to_dict(),
            "limit": args.limit,
            "document_selection": {
                "selected": len(docs),
                "of": len(records),
            },
            "recipe": recipe.to_manifest() if recipe is not None else None,
            "matcher": _matcher_manifest(args),
        },
    )
    _emit(manifest)
    return 0


def _document_mentions_available(args: argparse.Namespace) -> bool:
    from robustehr.concepts.matcher import index_present

    index = getattr(args, "index", None)
    return index is not None and index_present(Path(str(index)))


def _warn_empty_aim(doses: Sequence[Any], target: str, has_index: bool) -> None:
    """Say so on stderr when an aim admitted nothing, per operator.

    The dose table already records ``na_scope_empty`` for each such cell, and a
    reader of the table can see it. A user at a terminal sees exit code 0 and an
    edit count of zero, which reads as a result. The usual causes are named
    because each has a different fix.
    """
    if target == "all":
        return
    by_op: dict[str, list[Any]] = {}
    for dose in doses:
        by_op.setdefault(dose.op_id, []).append(dose)
    for op_id, cells in sorted(by_op.items()):
        if not any(d.total_n for d in cells) or any(d.scope_n for d in cells):
            continue
        reasons = [
            "the operator acts on structure (headers, lists, lines), which an aim at "
            "words cannot select",
            "the notes hold nothing the target matches",
        ]
        if not has_index:
            reasons.insert(
                0,
                "no QuickUMLS index was found, and `cat=`, `tui=`, `concept` and "
                "`uncategorized` need one (see data/quickumls_index/README.md)",
            )
        print(
            f"warning: target {target!r} admitted no unit for {op_id} in any note, so it "
            "made no edit. Possible causes: " + "; ".join(reasons) + ".",
            file=sys.stderr,
        )


def _param_value(literal: str) -> object:
    """``true``/``false`` is a flag, digits are a count, anything else a string.

    The types matter: an operator reads a flag only from a real bool and a count
    only from a real int, and the canonical string that feeds the seed is built
    from the value, so ``1`` typed here seeds exactly as ``1`` passed in Python.
    """
    if literal in ("true", "false"):
        return literal == "true"
    if literal.lstrip("-").isdigit():
        return int(literal)
    return literal


def _operator_params(
    flags: Sequence[str], from_recipe: Mapping[str, Mapping[str, object]], op_ids: Sequence[str]
) -> dict[str, dict[str, object]]:
    """Per-operator parameters from ``--param OP:KEY=VALUE`` and a recipe.

    A flag overrides the recipe for the same operator and key. An operator that
    is not part of the run is refused: a parameter nobody reads changes nothing,
    and a typo in the operator id would otherwise pass in silence.
    """
    out: dict[str, dict[str, object]] = {op: dict(p) for op, p in from_recipe.items()}
    for item in flags:
        head, sep, literal = item.partition("=")
        op_id, colon, key = head.partition(":")
        if not sep or not colon or not op_id or not key:
            raise ValueError(f"{item!r} is not OPERATOR:KEY=VALUE")
        out.setdefault(op_id, {})[key] = _param_value(literal)
    strangers = sorted(set(out) - set(op_ids))
    if strangers:
        raise ValueError(f"parameters given for operator(s) not in this run: {strangers}")
    return out


def _scope_for(scope: Any, recipe: Any, op_id: str) -> Any:
    """The scope for one operator, folding in a recipe's per-operator target.

    Structural operators keep `Everything` even under `target: {mode: umls}` —
    see `config.Recipe.target_for`. `Recipe.check` refuses that combination
    outright, so this is the second line rather than the first.
    """
    from dataclasses import replace as _replace

    if recipe is None:
        return scope
    return _replace(scope, target=recipe.target_for(op_id))


def _document_mentions(doc: Any, args: argparse.Namespace) -> Any:
    """Concept-match one note, or ``None`` when no index is configured.

    ``None`` is not a failure mode — it is the agnostic run, where targeting
    resolves per token and `dose.target_resolution` records that it did.
    """
    index = getattr(args, "index", None)
    from robustehr.concepts.matcher import index_present

    if not index or not index_present(Path(index)):
        return None
    if not _wants_concepts(args):
        return None
    from robustehr.concepts.matcher import ConceptMatcher
    from robustehr.concepts.pipeline import annotate_document

    return annotate_document(doc, ConceptMatcher(Path(index)))


def _wants_concepts(args: argparse.Namespace) -> bool:
    """Does anything in this run actually need a matcher?

    Loading a QuickUMLS index costs seconds and gigabytes, so it happens only
    when a target names concepts or a phenotype was declared. A run of pure
    RENDER operators over `--target all` must stay as cheap as it was.
    """
    from robustehr.target import parse_all

    if getattr(args, "phenotype", None):
        return True
    canon = parse_all(getattr(args, "target", None) or ["all"]).canon()
    return any(marker in canon for marker in ("cat=", "tui=", "concept", "uncategorized"))


def _matcher_manifest(args: argparse.Namespace) -> dict[str, Any] | None:
    """The matcher's pinned configuration, which decides what `cat=` can match."""
    if not _wants_concepts(args):
        return None
    try:
        from robustehr.concepts.matcher import MatcherConfig
    except ImportError:  # pragma: no cover - terminology extra not installed
        return None
    config = MatcherConfig()
    return {"index": str(getattr(args, "index", "")), "config": config.canon()}


def _load_phenotypes(args: argparse.Namespace) -> list[Any]:
    """Expand the named definitions, or return nothing for an agnostic run.

    Nothing here is imported unless a phenotype was asked for: ``agnostic`` runs
    must not require a UMLS release, an index, or the terminology extras.
    """
    if not args.phenotype:
        return []
    if _surface_only(args):
        from robustehr.concepts.phenotype import surface_only

        print(
            "phenotype target: no licensed terminology found (--isa/--crosswalk), so "
            "evidence is the diagnosis as written (surface warrant) only; the manifest "
            "records warrants: [surface]",
            file=sys.stderr,
        )
        return surface_only(args.phenotype)
    from robustehr.concepts import hierarchy
    from robustehr.concepts.phenotype import build, load_maps

    isa = hierarchy.load(Path(args.isa))
    code_to_cuis, cui_to_codes = load_maps(Path(args.crosswalk))
    return build(args.phenotype, isa, code_to_cuis, cui_to_codes)


def _surface_only(args: argparse.Namespace) -> bool:
    """Is the concept warrant unavailable on this machine?

    The hierarchy and the crosswalk are built from a licensed UMLS release and
    never ship. Without them a ``pheno=`` target can still be built from the
    declared surface forms, which is a weaker target and is recorded as such.
    """
    isa = getattr(args, "isa", None)
    crosswalk = getattr(args, "crosswalk", None)
    return not (isa and Path(isa).exists() and crosswalk and Path(crosswalk).exists())


def _evidence_index(doc: Any, mentions: Any, declared: list[Any], assertions: Any) -> Any:
    """Phenotype evidence on both warrants, always.

    Concept-set membership over the mentions and the declared surface forms
    over the document text are one method (methodology chapter 17): a span is
    evidence when its concept is in the set *or* when it literally spells the
    diagnosis. Every command that builds evidence goes through here so that no
    call site can compute one warrant and report the other. An install without
    the anchor resource degrades to concept membership alone, and the manifest's
    ``targeting`` block records that state.
    """
    from robustehr.concepts.phenotype import PhenotypeIndex, index_document

    if not declared:
        return PhenotypeIndex()
    return index_document(mentions, declared, assertions=assertions, text=doc.text)


def _document_evidence(doc: Any, declared: list[Any], args: argparse.Namespace) -> Any:
    """Concept-match one document and keep the spans that are phenotype evidence."""
    from robustehr.concepts.phenotype import PhenotypeIndex

    if not declared:
        return PhenotypeIndex()
    from robustehr.concepts.matcher import ConceptMatcher, MentionIndex, index_present

    index = Path(args.index) if getattr(args, "index", None) else None
    if index is None or not index_present(index):
        # No licensed index on this machine: the concept warrant finds nothing,
        # the surface warrant still finds the diagnosis as written, and the
        # manifest's `targeting.warrants` says so. Assertions need mentions to
        # qualify, so there are none to record either.
        return _evidence_index(doc, MentionIndex(()), declared, None)
    from robustehr.concepts.pipeline import annotate_document, qualify_document

    # The full pipeline, not bare matcher output: evidence is built with the
    # stage-3 recovery that every measurement quotes.
    matcher = ConceptMatcher(index)
    mentions = annotate_document(doc, matcher)
    # Stage 8. Without the map every `Evidence.assertion` is empty and
    # `evidence_touch_affirmed` reads 100% affirmed.
    assertions = None
    if not getattr(args, "no_assertions", False):
        assertions = qualify_document(doc, mentions).as_map() or None
    return _evidence_index(doc, mentions, declared, assertions)


def _targeting_manifest(args: argparse.Namespace) -> dict[str, Any] | None:
    """What the phenotype target was built from; ``None`` for an agnostic run."""
    if not getattr(args, "phenotype", None):
        return None
    from robustehr.concepts.phenotype import targeting_manifest

    return targeting_manifest(
        isa=Path(args.isa) if getattr(args, "isa", None) else None,
        crosswalk=Path(args.crosswalk) if getattr(args, "crosswalk", None) else None,
        warrants=("surface",) if _surface_only(args) else ("concept", "surface"),
    )


def _declared_recall(names: list[str]) -> dict[str, float | None]:
    from robustehr.concepts.phenotype import load_definitions

    definitions = load_definitions()
    return {n: definitions[n].measured_set_recall for n in sorted(names) if n in definitions}


def cmd_concept_profile(args: argparse.Namespace) -> int:
    """What each note *contains* — concepts, categories, phenotype evidence.

    A baseline-quality measurement in the same sense as ``baseline`` and
    ``ambiguity``: a property of the notes before any operator runs. It lives in
    its own command for the reason ``ambiguity`` does — it needs a terminology
    index, and ``baseline`` must stay runnable without one.

    **This is the denominator a robustness result needs.** "30% of medications
    were corrupted" is unreadable without knowing whether the note had three
    medications or three hundred, and until now nothing reported that: every
    artifact in this package was corpus-aggregated and `dose.jsonl` records only
    where edits *landed*.

    ``--per-note`` emits a row per note. Those rows carry `note_uid`, so on a
    restricted corpus they are note-derived and belong in ``data/``; the default
    corpus summary carries counts only and is safe to publish.
    """
    from robustehr.concepts.matcher import ConceptMatcher
    from robustehr.concepts.pipeline import annotate_document, qualify_document
    from robustehr.corpus import read_documents
    from robustehr.metrics.concepts import profile_concepts, summarise

    try:
        declared = _load_phenotypes(args)
    except (FileNotFoundError, KeyError) as exc:
        print(f"cannot build phenotypes: {exc}", file=sys.stderr)
        return 2

    # Built once, not per document. `_document_evidence` constructs a matcher
    # inside its loop, which is a real cost on any corpus worth profiling.
    matcher = ConceptMatcher(Path(args.index))
    profiles = []
    for doc in read_documents(Path(args.corpus), limit=args.limit):
        mentions = annotate_document(doc, matcher)
        assertions = None
        if not args.no_assertions:
            assertions = qualify_document(doc, mentions).as_map() or None
        evidence = _evidence_index(doc, mentions, declared, assertions)
        profiles.append(profile_concepts(doc, mentions, evidence, assertions))

    payload: dict[str, Any] = {
        "what": "concepts present in each note, before any operator runs",
        "corpus": Path(args.corpus).name,
        "assertions": not args.no_assertions,
        "phenotypes": sorted(args.phenotype or []),
        "phenotype_measured_set_recall": _declared_recall(list(args.phenotype or [])),
        "targeting": _targeting_manifest(args),
        **summarise(profiles),
    }
    if args.per_note:
        payload["profiles"] = [p.to_row() for p in profiles]
    _emit(payload, path=args.out)
    return 0


def _describe_concepts(
    doc: Any, matcher: Any, declared: list[Any], args: argparse.Namespace
) -> tuple[Any, Any, list[Any]]:
    """The terminology-dependent half of one note's row.

    Split out of `cmd_describe` so the structural half stays readable: this is
    everything that needs a UMLS index, and it is called only when there is one.
    """
    from robustehr.concepts.pipeline import annotate_document, qualify_document
    from robustehr.metrics.ambiguity import profile_ambiguity
    from robustehr.metrics.concepts import profile_concepts

    mentions = annotate_document(doc, matcher)
    assertions = None
    if not args.no_assertions:
        assertions = qualify_document(doc, mentions).as_map() or None
    evidence = _evidence_index(doc, mentions, declared, assertions)
    profile = profile_concepts(doc, mentions, evidence, assertions)
    # Counts only. The per-token occurrences carry surfaces and offsets, which
    # are note content and have no place in a corpus summary.
    ambiguity = profile_ambiguity(doc, matcher, keep_occurrences=False)
    return profile, ambiguity, list(mentions.mentions)


def _attach_groups(
    payload: dict[str, Any],
    rows: list[Any],
    groups: dict[str, list[str]],
    phenotypes: dict[str, list[str]],
) -> None:
    """One Table 1 per cohort, beside the corpus-wide one."""
    if not groups:
        return
    payload["by_group"] = _describe_groups(rows, groups, phenotypes)
    payload["by_group_note"] = (
        "groups OVERLAP — a note positive for hypertension is often positive "
        "for depression too — so they are cohorts, not a partition, and the "
        "group sizes sum to more than the corpus. `phenotypes` names the "
        "annotator applied to each group; `span.by_phenotype` inside a group "
        "still reports every declared phenotype, which is how cross-phenotype "
        "contamination becomes visible."
    )


def _attach_per_note(payload: dict[str, Any], rows: list[Any]) -> None:
    """Every note's own row, before aggregation.

    Note-derived: keyed by note_uid, so on a restricted corpus this output
    localises content and belongs under data/. Same convention as
    `concept-profile --per-note`.
    """
    payload["notes_detail"] = [r.to_row() for r in rows]
    payload["notes_detail_note"] = (
        "one row per note, keyed by note_uid. Note-derived: belongs under "
        "data/ on a restricted corpus. The corpus totals above are "
        "aggregates of exactly these rows."
    )


def _attach_cui_map(payload: dict[str, Any], cui_rows: list[dict[str, Any]]) -> None:
    """Every mention as identifiers and offsets, never the matched surface.

    Note-derived: a CUI map is keyed by note_uid and localises content, so it
    belongs under data/ on a restricted corpus. A CUI plus a span is
    reproducible against the reader's own release; the text it matched is not
    ours to ship.
    """
    payload["cui_map"] = cui_rows
    payload["cui_map_note"] = (
        "identifiers and offsets only, no surface text. Keyed by note_uid, "
        "so this is note-derived and belongs under data/ on a restricted corpus."
    )


def _resolve_groups(
    args: argparse.Namespace,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Cohorts and the phenotype annotator each one gets.

    Resolved BEFORE the annotation pass, because a group names the phenotypes
    whose annotator applies to it and those have to be declared before any note
    is indexed. Pointing the wrong annotator at a group produces a table that
    looks right and measures something else, so the correspondence comes from
    `resources/label_groups.yaml` where a reviewer can read it.

    Mutates `args.phenotype` to the union of what the groups need. That is the
    point of the flag: `--groups` alone should not require the caller to also
    list seventeen phenotypes correctly.
    """
    from robustehr.metrics.describe import load_group_map, read_groups

    if not args.groups:
        return {}, {}
    phenotypes = load_group_map(args.group_map) if args.group_map else {}
    groups = read_groups(Path(args.groups), phenotypes or None)
    if not phenotypes:
        # No map named: a column stands for the phenotype of the same name. A
        # column naming none is reported with an empty list rather than dropped.
        phenotypes = {c: [c] for c in groups}
    wanted = {p for names in phenotypes.values() for p in names}
    args.phenotype = sorted(set(args.phenotype or []) | wanted)
    return groups, phenotypes


def _describe_groups(
    rows: list[Any], groups: dict[str, list[str]], phenotypes: dict[str, list[str]]
) -> dict[str, Any]:
    """One Table 1 per group of notes, from the SAME per-note measurements.

    Not a re-run: `assemble` is called again over a subset of the rows already
    measured, so a group's numbers and the corpus numbers cannot disagree. The
    alternative — a describe invocation per group — would annotate every note
    once per group it belongs to, which on the MIPA labels is 4,003 passes over
    1,387 notes.
    """
    from robustehr.metrics.describe import assemble

    by_uid = {r.note_uid: r for r in rows}
    out: dict[str, Any] = {}
    for name in sorted(groups, key=lambda g: (-len(groups[g]), g)):
        members = [by_uid[u] for u in groups[name] if u in by_uid]
        if not members:
            continue
        declared = phenotypes.get(name, [])
        table = assemble(members, _declared_recall(declared))
        out[name] = {
            "notes": len(members),
            "share_of_corpus": round(len(members) / len(rows), 4) if rows else None,
            "phenotypes": declared,
            **table.to_row(),
        }
    covered = {u for members in groups.values() for u in members} & set(by_uid)
    out["_coverage"] = {
        "notes_in_at_least_one_group": len(covered),
        "notes_in_no_group": len(by_uid) - len(covered),
        # Memberships among the notes MEASURED, not among the label file. Under
        # `--limit` the two differ, and reporting the file's total would say the
        # run covered 4,003 memberships when it covered 68.
        "group_memberships": sum(sum(1 for u in v if u in by_uid) for v in groups.values()),
        "note": (
            "memberships exceed notes because groups overlap. A note in NO group "
            "is one the label set marks negative for everything, including its "
            "own `none` column, and it is counted rather than ignored."
        ),
    }
    return out


def _measure_corpus(
    args: argparse.Namespace,
    lexicon: Any,
    spelling_path: Path | None,
    matcher: Any,
    declared: list[Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Measure every note ONCE, and index it against every declared phenotype.

    One pass, not one per cohort. On the MIPA labels a note belongs to 2.9
    cohorts on average, so a pass per cohort would be 4,003 annotations over
    1,387 notes — and would let two cohorts disagree about the same note.
    """
    from robustehr.corpus import read_documents
    from robustehr.metrics.describe import measure_note

    rows = []
    cui_rows: list[dict[str, Any]] = []
    for doc in read_documents(Path(args.corpus), limit=args.limit):
        profile = None
        ambiguity = None
        near_miss = None
        mentions = None
        if spelling_path is not None:
            from robustehr.metrics.spelling import profile_near_miss

            near_miss = profile_near_miss(doc, lexicon, spelling_path)
        if matcher is not None:
            profile, ambiguity, mentions = _describe_concepts(doc, matcher, declared, args)
            if args.cui_map:
                # Identifiers and offsets only — never the matched surface. A
                # CUI plus a span is reproducible against the reader's own
                # release; the text it matched is note content.
                cui_rows.extend(
                    {
                        "note_uid": doc.uid,
                        "cui": m.cui,
                        "start": m.span.start,
                        "end": m.span.end,
                        "tuis": sorted(m.tuis),
                        "categories": sorted(m.categories),
                    }
                    for m in mentions
                )
        rows.append(measure_note(doc, lexicon, profile, ambiguity, near_miss, mentions))
    return rows, cui_rows


def cmd_describe(args: argparse.Namespace) -> int:
    """Table 1: one deterministic characterisation of a clinical-note corpus.

    Five commands already measured pieces of this — `baseline`,
    `applicability`, `concept-profile`, `ambiguity`, `concepts classify` — each
    with its own JSON and its own denominators. Assembling the table a methods
    section opens with meant running all five and reconciling them by hand,
    which is exactly where a transcription error becomes a published number.

    Degrades in blocks: without a UMLS index the concept, assertion and
    phenotype blocks report `null` with the reason, and the structural blocks
    are unaffected.

    With ``--run`` it characterises a **corrupted** corpus instead, one table
    per (operator, severity) cell, using the identical measurement path. That
    symmetry is the point: the level whose count decided an operator's dose is
    the level a reader watches move.
    """
    from robustehr.lexicon import DEFAULT_LEXICON, load_clinical_lexicon
    from robustehr.metrics.describe import assemble

    if not args.corpus and not args.from_table:
        print("describe needs --corpus, or --from-table to re-render", file=sys.stderr)
        return 2
    if args.from_table:
        return _rerender(args)
    if getattr(args, "run", None):
        return _describe_run(args)

    lexicon = DEFAULT_LEXICON
    path = Path(args.lexicon)
    if path.exists():
        lexicon = load_clinical_lexicon(path)
    # The near-miss measure needs a real clinical vocabulary to say what is
    # UNKNOWN. Against the morphology-only fallback every clinical term is
    # unknown, so `furosemide` becomes a candidate and the number stops meaning
    # anything. Better absent with a reason than present and wrong.
    spelling_path = path if lexicon.source != "morphology-only" else None

    try:
        groups, group_phenotypes = _resolve_groups(args)
    except (KeyError, FileNotFoundError) as exc:
        print(f"cannot read groups: {exc}", file=sys.stderr)
        return 2

    matcher = None
    declared: list[Any] = []
    from robustehr.concepts.matcher import index_present, quickumls_available

    if not args.no_concepts and index_present(Path(args.index)) and not quickumls_available():
        # An index without the extra is a specific, fixable situation, and a
        # silent structural-only table would look like a corpus with no concepts.
        print(
            "concept layer unavailable: an index exists at "
            f"{args.index} but the terminology extra is not installed "
            "(pip install 'robustehr[terminology]'). Reporting structural levels only.",
            file=sys.stderr,
        )
    if not args.no_concepts and index_present(Path(args.index)) and quickumls_available():
        from robustehr.concepts.matcher import ConceptMatcher

        matcher = ConceptMatcher(Path(args.index))
        try:
            declared = _load_phenotypes(args)
        except (FileNotFoundError, KeyError) as exc:
            print(f"phenotypes unavailable: {exc}", file=sys.stderr)
            declared = []

    rows, cui_rows = _measure_corpus(args, lexicon, spelling_path, matcher, declared)

    table = assemble(rows, _declared_recall([str(p) for p in (args.phenotype or [])]))
    payload: dict[str, Any] = {
        "what": "Table 1 — a deterministic characterisation of this corpus",
        "corpus": Path(args.corpus).name,
        "lexicon_source": lexicon.source,
        "phenotypes": sorted(args.phenotype or []),
        **table.to_row(),
    }
    if args.cui_map:
        _attach_cui_map(payload, cui_rows)
    _attach_groups(payload, rows, groups, group_phenotypes)
    if args.per_note:
        _attach_per_note(payload, rows)
    _emit_group_documents(payload, args.group_out)
    if args.markdown:
        _render_tables(payload, args)
    else:
        _emit(payload, path=args.out)
    return 0


def _describe_run(args: argparse.Namespace) -> int:
    """Table 1 for a corrupted corpus, one per (operator, severity) cell.

    **Reconstructed from the edit script, not read from disk.** `--emit-text`
    is optional and its output carries the corpus's licence; the edit script is
    the artifact that always exists. Replaying it also proves the table
    describes the run being reported rather than whatever text happens to sit in
    a directory — the same reasoning `compare` follows.

    Structural only, deliberately. The concept blocks would need a matcher pass
    per cell, which is a `compare` at a different granularity and already
    exists; what has been missing is the ability to answer "what did this
    corruption do to the note's *structure*" with the instrument that measured
    the structure in the first place.
    """
    from robustehr.corpus import read_documents
    from robustehr.document import Document
    from robustehr.edits.apply import apply_edits
    from robustehr.metrics.describe import level_characteristics, quantiles
    from robustehr.store import read_doses, read_edits

    originals = {d.uid: d for d in read_documents(Path(args.corpus), limit=args.limit)}
    by_cell: dict[tuple[str, str, str], list[Any]] = {}
    for row in read_edits(Path(args.run)):
        if row.note_uid in originals:
            by_cell.setdefault((row.note_uid, row.cell_id, row.severity), []).append(row)

    # Grouped by cell so each table aggregates across notes exactly as the
    # baseline does across a corpus. A per-note table would answer a different
    # question and could not be compared with Table 1.
    per_cell: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for dose in read_doses(Path(args.run)):
        uid = str(dose["note_uid"])
        if uid not in originals:
            continue
        key = (str(dose["op_id"]), str(dose["severity"]))
        edits = tuple(r.to_edit() for r in by_cell.get((uid, *key), []))
        text = apply_edits(originals[uid].text, edits).text
        per_cell.setdefault(key, []).append(
            level_characteristics(Document.from_text(text, uid=uid))
        )

    baseline = [level_characteristics(doc) for doc in originals.values()]
    payload: dict[str, Any] = {
        "what": "Table 1 for a corrupted corpus, one per (operator, severity) cell",
        "instrument": "metrics.describe.level_characteristics, replayed from the edit script",
        "run": str(args.run),
        "corpus": Path(args.corpus).name,
        "notes": len(originals),
        "baseline": _aggregate_levels(baseline, quantiles),
        "cells": {
            f"{op}@{severity}": {
                "notes": len(measured),
                "by_level": _aggregate_levels(measured, quantiles),
            }
            for (op, severity), measured in sorted(per_cell.items())
        },
    }
    if args.markdown:
        _describe_run_markdown(payload)
    else:
        _emit(payload, path=args.out)
    return 0


#: The rows a reader wants side by side: (label, level, field). The full
#: per-level breakdown is in the JSON; this is the printable half.
_RUN_TABLE_ROWS: tuple[tuple[str, str | None, str | None], ...] = (
    ("**Document**", None, None),
    ("Lines", "document", "lines"),
    ("Characters", "character", "n"),
    ("OCR-confusable characters", "character", "ocr_confusable"),
    ("**Structure**", None, None),
    ("Sections", "section", "n"),
    ("Headers", "header", "n"),
    ("Standalone headers", "header", "standalone"),
    ("Paragraph and line breaks", "break", "n"),
    ("Sentences", "sentence", "n"),
    ("Prose sentences", "sentence", "prose"),
    ("List items", "list_item", "n"),
    ("Aligned blocks (lab tables)", "aligned_block", "n"),
    ("De-identification placeholders", "placeholder", "n"),
    ("**Tokens**", None, None),
    ("Tokens", "token", "n"),
    ("Words", "token", "word"),
    ("Content tokens", "token", "content"),
    ("Numeric values", "numeric_value", "n"),
    ("Word gaps (single spaces)", "word_space", "single_spaces"),
)


def _describe_run_markdown(payload: dict[str, Any]) -> None:
    """Table 1 side by side: the clean corpus, then one column per corrupted cell.

    Same rows, same instrument, same quantiles as the baseline table, so an
    arm's cost is read against its own denominator rather than against a
    number quoted from somewhere else.
    """
    cells = payload["cells"]
    names = list(cells)
    print(f"# Table 1, clean and corrupted — {payload['corpus']}\n")
    print(
        f"**{payload['notes']} notes.** Each corrupted column is reconstructed by replaying "
        "the cell's edit script, then measured with the instrument that measured the clean "
        "corpus. Median [IQR] per note.\n"
    )
    columns = " | ".join(f"`{n}`" for n in names)
    print(f"| Characteristic, per note | Clean corpus | {columns} |")
    print("|---|---:|" + "---:|" * len(names))

    def fmt(stats: dict[str, Any] | None) -> str:
        if not stats:
            return "—"
        return f"{stats['median']:g} [{stats['p25']:g}-{stats['p75']:g}]"

    for label, level, field in _RUN_TABLE_ROWS:
        if level is None:
            print(f"| {label} | " + " | ".join([""] * (len(names) + 1)) + " |")
            continue
        base = payload["baseline"].get(level, {}).get(field)
        row = [fmt(base)] + [fmt(cells[n]["by_level"].get(level, {}).get(field)) for n in names]
        print(f"| {label} | " + " | ".join(row) + " |")


def _aggregate_levels(
    measured: list[dict[str, dict[str, Any]]], quantiles: Any
) -> dict[str, dict[str, Any]]:
    """Median and quartiles per level field, across notes.

    Medians rather than means, matching `assemble`: note length in a clinical
    corpus is heavy-tailed, and one discharge summary of 40,000 characters moves
    a mean in a way it does not move the corpus.
    """
    if not measured:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for level in sorted(measured[0]):
        fields: dict[str, Any] = {}
        for field_name in sorted(measured[0][level]):
            values = [
                m[level][field_name]
                for m in measured
                if isinstance(m.get(level, {}).get(field_name), int)
            ]
            if values:
                fields[field_name] = quantiles(values)
        out[level] = fields
    return out


def _render_tables(payload: dict[str, Any], args: argparse.Namespace) -> None:
    """Table 1 and Table 2, with the per-level audit tables behind `--detail`.

    Two audiences, and one output cannot serve both. A methods section wants one
    indented table it can print; someone checking that `input.typo`'s
    denominator is the number the baseline claims wants the level-by-level
    breakdown. The default is the first, because that is what a corpus
    description is FOR, and the second is a flag away.
    """
    from robustehr import report

    report.render(payload, _concept_set_sizes(), sys.stdout, _runtime_set_sizes())
    if args.detail:
        print("\n---\n")
        _describe_markdown(payload)


def _concept_set_sizes() -> dict[str, dict[str, int | None]]:
    """Concepts per phenotype per category — what each annotator looks FOR.

    Read from the committed audit rather than rebuilt, because expanding 22
    phenotypes needs the UMLS hierarchy and Table 2 must render from a saved
    table on a machine that has none. Absent, the `declared` column is empty and
    Table 2 still reports what was found — degraded, not wrong.
    """
    path = Path("validation/measurements/phenotype_set_audit.json")
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("phenotypes") or {}
    # `by_category` uses the SAME category vocabulary the observed side does,
    # which is what makes the two columns of Table 2 comparable at all. Joining
    # a set counted in one taxonomy to evidence counted in another would give a
    # yield column that means nothing.
    # `_distinct` rides along because the category counts overlap (the taxonomy
    # is a lattice) and their sum exceeds the set size; comparing THAT sum to
    # the runtime count manufactured a phantom gap for every phenotype.
    return {
        name: {
            **dict(row.get("by_category") or {}),
            "_distinct": row.get("total_distinct_cuis"),
        }
        for name, row in rows.items()
        if isinstance(row, dict)
    }


def _runtime_set_sizes() -> dict[str, int]:
    """Concepts each phenotype carries AT RUNTIME, from the published audit.

    Separate from `_concept_set_sizes` because the two have disagreed before
    and the disagreement was the finding Table 2 exists to expose: `build()`
    once expanded only the disorder closure while the audit counted faceted
    sets nothing loaded. Facets now load by default, so the columns agree
    wherever the facet artifacts are installed — and the agreement is
    regenerated, not asserted: `validation/phenotype/scripts/phenotype_runtime_sets.py`.
    """
    path = Path("validation/measurements/phenotype_runtime_sets.json")
    if not path.exists():
        return {}
    sizes = json.loads(path.read_text(encoding="utf-8")).get("runtime_set_size") or {}
    return {k: v for k, v in sizes.items() if isinstance(v, int)}


def _rerender(args: argparse.Namespace) -> int:
    """Re-render an already-written table. Never re-measure.

    The documents are a pure function of the table, and this is what proves it:
    the annotation pass over 1,388 MIMIC-IV notes takes ~76 minutes, so a
    formatting change must not cost one. Nothing here reads the corpus, and a
    table produced by `--from-table` is byte-identical to the one the measuring
    run produced.
    """
    payload = json.loads(Path(args.from_table).read_text(encoding="utf-8"))
    _emit_group_documents(payload, args.group_out)
    if args.markdown:
        _render_tables(payload, args)
    elif args.out:
        _emit(payload, path=args.out)
    return 0


def _emit_group_documents(payload: dict[str, Any], out_dir: str | None) -> None:
    """Write the per-cohort documents, if asked, and say where they went."""
    if not out_dir:
        return
    written = _write_group_documents(payload, Path(out_dir))
    print(
        f"wrote {len(written)} cohort documents to {out_dir} — note-derived, "
        "keep under data/ on a restricted corpus",
        file=sys.stderr,
    )


def _write_group_documents(payload: dict[str, Any], out_dir: Path) -> list[Path]:
    """One self-contained Table 1 per cohort, as markdown beside JSON.

    A cohort document is the SAME payload shape as the corpus-wide one, so the
    renderer is the same function and a reader comparing two phenotypes is
    comparing identically-built tables. What differs is the note set and the
    phenotype whose annotator ran.

    Reproducible by construction: file names come from the cohort names, cohort
    order is fixed, and every number is `assemble` over rows the single
    annotation pass already produced. Re-running the command overwrites the
    same paths with the same bytes.

    Note-derived — a cohort is a set of note_ids — so `out_dir` belongs under
    `data/` on a restricted corpus. The caller is told, not stopped: a cohort
    table carries counts rather than text, and where it may live is a licence
    question the user answers.
    """
    from robustehr import report

    groups = payload.get("by_group") or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, group in groups.items():
        if name.startswith("_"):
            continue
        # Rebuilt rather than sliced: the renderer reads `corpus`, `notes` and
        # `phenotypes` off the top level, so a cohort must present itself the
        # way the corpus does or the header would name the wrong note count.
        document = {
            "what": f"Table 1 — cohort `{name}`",
            "corpus": f"{payload['corpus']} · cohort {name}",
            "notes": group["notes"],
            "lexicon_source": payload.get("lexicon_source", ""),
            "phenotypes": group["phenotypes"],
            "by_level": group["by_level"],
            "unavailable": group.get("unavailable", {}),
        }
        stem = out_dir / name
        with stem.with_suffix(".md").open("w", encoding="utf-8") as handle:
            print(f"<!-- cohort {name} of {payload['corpus']}; ", file=handle, end="")
            print(
                f"{group['notes']} notes, {group['share_of_corpus']:.3f} of corpus; "
                f"annotator: {', '.join(group['phenotypes']) or 'none'} -->",
                file=handle,
            )

            def write(line: str = "", _handle: Any = handle) -> None:
                print(line, file=_handle)

            # The digestible table ONLY. A cohort document is read to compare
            # phenotypes, and twelve audit tables per cohort across seventeen
            # cohorts is not a comparison anyone makes. The audit view is a
            # `--detail` flag away on the corpus table, and the cohort's own
            # JSON sits beside this file.
            report.table1(document, write)
        stem.with_suffix(".json").write_text(
            json.dumps(document, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        written.append(stem.with_suffix(".md"))
    return written


def _describe_markdown(  # noqa: PLR0912,PLR0915
    payload: dict[str, Any], out: TextIO | None = None
) -> None:
    """Table 1, organised by the taxonomy's levels — the view a reader gets.

    The previous version printed six blocks of my own invention and mentioned
    `level`, `operator` or `space_run` exactly zero times, so the taxonomic
    organisation existed only in the JSON where nobody reads it.
    """
    # One writer instead of 122 bare prints, so the same renderer serves
    # stdout and a per-cohort file. Redirecting stdout would have done it in
    # five lines and left a renderer that cannot say where it is writing.
    stream = out or sys.stdout

    def w(line: str = "") -> None:
        print(line, file=stream)

    levels = payload["by_level"]

    def cell(block: dict[str, Any], key: str) -> str:
        value = block.get(key)
        if not isinstance(value, dict):
            return "—"
        if "median" in value:
            if value["median"] is None:
                return "—"
            return f"{value['median']} [{value['p25']}-{value['p75']}]"
        return str(value.get("total", "—"))

    def total(block: dict[str, Any], key: str) -> str:
        value = block.get(key)
        return str(value.get("total", "—")) if isinstance(value, dict) else "—"

    w(f"# Table 1 — {payload['corpus']} (n = {payload['notes']} notes)\n")
    w("Organised by the structural level an operator can target. `median [IQR]`")
    w("is per note; `total` is over the note set named above.\n")
    w("| level | units, median [IQR] | total | corruptible by |")
    w("|---|---:|---:|---|")
    # Ordered as a reader descends a note: whole document down to characters.
    order = [
        "document",
        "section",
        "header",
        "sentence",
        "list_item",
        "aligned_block",
        "space_run",
        "placeholder",
        "span",
        "token",
        "character",
        "assertion",
    ]
    for name in order:
        block = levels.get(name)
        if not block:
            continue
        ops = block.get("operators") or []
        shown = ", ".join(o.split(".", 1)[1] for o in ops) if ops else "—"
        w(f"| **{name}** | {cell(block, 'n')} | {total(block, 'n')} | {shown} |")

    section = levels.get("section", {})
    presence = section.get("canonical_presence")
    if presence:
        present = {k: v for k, v in presence.items() if v["notes_with"]}
        w(f"\n## section — which of the {section['canonical_declared']} canonical sections\n")
        w(
            f"{len(present)} present, {len(section['canonical_absent'])} absent. Absent ones are "
            "listed rather than omitted: a section in 0 of these notes is a fact "
            "about the corpus, and a missing row is not.\n"
        )
        w("| section | kind | notes with | share | body chars (median) |")
        w("|---|---|---:|---:|---:|")
        for name, row in sorted(present.items(), key=lambda kv: (-kv[1]["notes_with"], kv[0])):
            w(
                f"| {name} | {row['kind']} | {row['notes_with']} | "
                f"{row['share_of_notes']:.2f} | {row['body_chars_median'] or 0} |"
            )
        absent_clinical = [
            n for n in section["canonical_absent"] if presence[n]["kind"] == "clinical"
        ]
        if absent_clinical:
            w(f"\n**Absent (clinical):** {', '.join(absent_clinical)}")
        if section.get("non_canonical_ids_seen"):
            w(
                f"\n_Seen but not declared in the lexicon:_ "
                f"{', '.join(section['non_canonical_ids_seen'])}"
            )

    token = levels.get("token", {})
    w("\n## token — composition\n")
    w("Each operator's denominator is derivable from this, which a bare count")
    w("is not: `word_min3` IS `input.typo`'s eligible set, `ocr_confusable` IS")
    w("`input.ocr_confusion`'s.\n")
    w("| field | median [IQR] | total | this is the denominator for |")
    w("|---|---:|---:|---|")
    for key, who in [
        ("word", "—"),
        ("word_min3", "`input.typo`"),
        ("word_min4", "`control.char_shuffle`"),
        ("ocr_confusable", "`input.ocr_confusion`"),
        ("short_form", "— (shape count; see abbreviations)"),
        ("alphanumeric", "—"),
        ("numeric", "—"),
        ("punctuation", "—"),
    ]:
        if key in token:
            w(f"| {key} | {cell(token, key)} | {total(token, key)} | {who} |")
    w(
        "\n`input.phonetic_confusion` is deliberately absent: its eligibility is "
        '"a morpheme rule fires", which depends on the rule file and a vocabulary '
        "gate rather than on token shape. A number that looked like its "
        "denominator would be worse than none."
    )

    partition = token.get("lexical_partition") or []
    if partition:
        w("\n## token — lexical class\n")
        w("| class | total | share of content tokens |")
        w("|---|---:|---:|")
        for name in partition:
            block = token.get(f"lex_{name}")
            if block:
                w(f"| {name} | {block['total']} | {block['share_of_content']:.3f} |")
        extra = sorted(k[4:] for k in token if k.startswith("lex_") and k[4:] not in partition)
        if extra:
            w("\n_Overlapping annotations over the same tokens — do not add to the above:_")
            w("\n| annotation | total | share |")
            w("|---|---:|---:|")
            for name in extra:
                block = token[f"lex_{name}"]
                w(f"| {name} | {block['total']} | {block['share_of_content']:.3f} |")

    if "abbreviations" in token:
        w("\n## token — abbreviation load\n")
        w("How much of the shorthand forces a sense choice. Distinct from the")
        w("free `short_form` shape count above: neither population contains the")
        w("other (`BLOOD` is one and not the other; `HFrEF` is the reverse).\n")
        w("| measure | median [IQR] | total | % of content tokens | % of abbreviations |")
        w("|---|---:|---:|---:|---:|")
        for key, label in [
            ("abbreviations", "abbreviation-shaped tokens"),
            ("abbreviations_ambiguous", "ambiguous (2+ concepts)"),
            ("abbreviations_highly_ambiguous", "highly ambiguous (5+)"),
        ]:
            of_abbr = token[key].get("share_of_abbreviations")
            of_content = token[key].get("share_of_content")
            w(
                f"| {label} | {cell(token, key)} | {total(token, key)} "
                f"| {'—' if of_content is None else f'{of_content:.3f}'} "
                f"| {'—' if of_abbr is None else f'{of_abbr:.3f}'} |"
            )
        bands = token.get("abbreviation_sense_bands", {})
        if bands:
            w("\n**Sense distribution** — what `ambiguous` collapses. Two senses and")
            w("twenty are not the same problem, and one threshold cannot say which")
            w("corpus you have.\n")
            w("| UMLS senses | tokens | share |")
            w("|---|---:|---:|")
            for band, row in bands.items():
                share = row["share"]
                w(f"| {band} | {row['n']} | {'—' if share is None else f'{share:.3f}'} |")
        outcomes = token.get("abbreviation_outcomes", {})
        if outcomes:
            w("\n| outcome | n | share | what can be done |")
            w("|---|---:|---:|---|")
            meaning = {
                "resolved": "one concept; the matcher handles it unaided",
                "ambiguous": "several concepts; a sense must be chosen",
                "expandable": "no concept, but the shipped expansion table knows it",
                "unreachable": "no concept and no table entry",
            }
            for name, row in outcomes.items():
                share = row["share"]
                mark = "—" if share is None else f"{share:.3f}"
                w(f"| {name} | {row['n']} | {mark} | {meaning.get(name, '')} |")

    if "near_miss_edit1" in token:
        near = token["near_miss_edit1"]
        w("\n## token — near-miss (candidate misspellings)\n")
        w("| measure | median [IQR] | total |")
        w("|---|---:|---:|")
        w(
            f"| unrecognised candidates | {cell(token, 'near_miss_candidates')} "
            f"| {total(token, 'near_miss_candidates')} |"
        )
        spread = cell(token, "near_miss_edit1")
        w(f"| within one edit of a known term | {spread} | {near['total']} |")
        w(f"| distinct surfaces | — | {near['distinct_surfaces']} |")
        w(f"| **distinct hapax (use this)** | — | **{near['distinct_hapax']}** |")
        w(
            "\n**Not a misspelling rate.** Adjudicated on 200 MIMIC-IV notes the "
            "filter is right 0.425 of the time by distinct surface and **0.096 by "
            "occurrence** — the total above is roughly nine parts vocabulary and "
            "shorthand to one part error, because the frequent near-misses are "
            "words the lexicons miss and clinical abbreviations. The hapax "
            "subset reaches 0.526. See validation/measurements/spelling_precision.json."
        )

    if "concept_covered" in token:
        cov = token["concept_covered"]
        w("\n## token — how much of the note is inside a concept\n")
        w("Tokens lying inside at least one UMLS mention, counted ONCE each.")
        w("**Not** the span count divided by the token count: mentions overlap and")
        w("run one to six tokens long, so that division answers nothing. Shares are")
        w("of CONTENT tokens — punctuation is ~60% of `token.n` and no concept")
        w("covers it.\n")
        share = cov.get("share_of_content")
        w("| measure | median [IQR] | total | % of content tokens |")
        w("|---|---:|---:|---:|")
        w(
            f"| covered by a concept | {cell(token, 'concept_covered')} | {cov['total']} "
            f"| **{'—' if share is None else f'{share:.3f}'}** |"
        )
        by_cat = token.get("concept_covered_by_category", {})
        if by_cat:
            w("\n| semantic category | tokens | % of content tokens |")
            w("|---|---:|---:|")
            for name, row in by_cat.items():
                s = row["share_of_content"]
                w(f"| {name} | {row['tokens']} | {'—' if s is None else f'{s:.3f}'} |")
            w("\n_Categories overlap — a concept may carry several semantic types —_")
            w("_so these sum to more than the total above._")

    span = levels.get("span") or {}
    if span.get("n"):
        w("\n## span — concept mentions\n")
        w("A mention IS a span, which is why it is a level of its own. `disorder`")
        w("counts here are SPANS; the token coverage above is the same evidence")
        w("counted in tokens, and the two differ because spans overlap and vary in")
        w("length.\n")
        w("| measure | median [IQR] | total |")
        w("|---|---:|---:|")
        for key, label in [
            ("n", "mention spans"),
            ("distinct_cuis_per_note", "distinct CUIs per note"),
            ("per_1k_content_tokens", "mentions per 1k content tokens"),
        ]:
            w(f"| {label} | {cell(span, key)} | {total(span, key)} |")
        lengths = span.get("token_lengths", {})
        if lengths:
            w("\n**Span length in tokens** — the bridge between this level and the")
            w("token level.\n")
            w("| tokens | spans | share |")
            w("|---|---:|---:|")
            for name, row in lengths.items():
                s = row["share"]
                w(f"| {name} | {row['spans']} | {'—' if s is None else f'{s:.3f}'} |")
        w("\n| semantic category | spans | share of spans |")
        w("|---|---:|---:|")
        for name, row in span.get("by_category", {}).items():
            s = row["share_of_spans"]
            w(f"| {name} | {row['spans']} | {'—' if s is None else f'{s:.3f}'} |")

    if span.get("by_phenotype"):
        w("\n## span — phenotype evidence\n")
        w("| phenotype | evidence spans | share of spans | notes with any | set recall |")
        w("|---|---:|---:|---:|---:|")
        for name, row in span["by_phenotype"].items():
            recall = row["measured_set_recall"]
            s = row["share_of_spans"]
            w(
                f"| {name} | {row['evidence_spans']} "
                f"| {'—' if s is None else f'{s:.4f}'} | {row['notes_with_any']} "
                f"| {'—' if recall is None else recall} |"
            )
        w("\n_A phenotype's count is bounded by its measured set recall: evidence_")
        w("_never matched is evidence never counted here._")

    assertion = levels.get("assertion") or {}
    if assertion.get("n"):
        w("\n## assertion — what each SEMANTIC operator is eligible on\n")
        w("`eligible_cues` IS the denominator a severity is a fraction of. The")
        w("attribute counts below are a DIFFERENT population — mentions carrying")
        w("the attribute, which one cue can produce several of — so neither")
        w("predicts the other.\n")
        w("| operator | ConText cue categories | eligible cues | median [IQR] |")
        w("|---|---|---:|---:|")
        for op_id in assertion.get("operators", []):
            row = assertion.get(op_id)
            if not row:
                continue
            cats = ", ".join(c.lower() for c in row["cue_categories"])
            w(f"| `{op_id}` | {cats} | **{row['eligible_cues']}** | {cell(assertion, op_id)} |")

    if assertion.get("by_attribute"):
        w("\n## assertion — attribute by semantic category\n")
        w('Where a flip would land. "355 negated mentions" does not say whether a')
        w("negation flip hits a disorder or an anatomical site, and those are")
        w("different corruptions with different downstream costs.\n")
        attributes = assertion["by_attribute"]
        columns = sorted({c for r in attributes.values() for c in r["by_category"]})
        head = " | ".join(columns)
        w(f"| attribute | mentions | share | flipped by | {head} |")
        w("|---|---:|---:|---|" + "---:|" * len(columns))
        for name, row in attributes.items():
            op = row["flipped_by"]
            cells = " | ".join(str(row["by_category"].get(c, 0)) for c in columns)
            w(
                f"| {name} | {row['mentions']} | {row['share']:.3f} "
                f"| {('`' + op.split('.', 1)[1] + '`') if op else '—'} | {cells} |"
            )
        w(f"\nModified share: **{assertion['modified_share']:.3f}**. ")
        w(assertion.get("note", ""))

    by_group = payload.get("by_group")
    if by_group:
        w("\n## by cohort\n")
        cov = by_group.get("_coverage", {})
        w(
            f"{cov.get('group_memberships', 0)} memberships over "
            f"{cov.get('notes_in_at_least_one_group', 0)} notes — cohorts OVERLAP and "
            f"are not a partition. {cov.get('notes_in_no_group', 0)} notes are in no "
            "cohort. Each cohort is annotated with ITS OWN phenotype; `own evidence`"
            " counts only that phenotype's spans.\n"
        )
        cohorts = [(n, r) for n, r in by_group.items() if not n.startswith("_")]

        w("### Structure — does the note shape vary by phenotype?\n")
        w("| cohort | notes | chars, median | sections | spans | concept cov. | abbrev. |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        for name, row in cohorts:
            lv = row["by_level"]
            sp = lv.get("span") or {}
            tk = lv.get("token") or {}
            cover = (tk.get("concept_covered") or {}).get("share_of_content")
            abbrev = (tk.get("abbreviations") or {}).get("share_of_content")
            w(
                f"| **{name}** | {row['notes']} | {lv['character']['n']['median']} "
                f"| {lv['section']['n']['median']} "
                f"| {(sp.get('n') or {}).get('total', 0)} "
                f"| {'—' if cover is None else f'{cover:.3f}'} "
                f"| {'—' if abbrev is None else f'{abbrev:.3f}'} |"
            )

        w("\n### Phenotype recovery — did the cohort's own annotator find anything?\n")
        w(
            "`notes with` is how many of the cohort's notes carry ANY evidence for "
            "their own phenotype. A cohort is positive by expert annotation, so a "
            "low share is a failure of the concept SET, not of the notes — read it "
            "beside `set recall`, which was measured independently.\n"
        )
        w("| cohort | notes | evidence spans | per note | notes with | share | set recall |")
        w("|---|---:|---:|---:|---:|---:|---:|")
        for name, row in cohorts:
            own = row["phenotypes"]
            by_pheno = ((row["by_level"].get("span") or {}).get("by_phenotype")) or {}
            evidence = sum(by_pheno.get(x, {}).get("evidence_spans", 0) for x in own)
            with_any = max((by_pheno.get(x, {}).get("notes_with_any", 0) for x in own), default=0)
            recalls = [
                by_pheno.get(x, {}).get("measured_set_recall")
                for x in own
                if by_pheno.get(x, {}).get("measured_set_recall") is not None
            ]
            share = with_any / row["notes"] if row["notes"] else 0.0
            label = ", ".join(own) if own else "_negative control_"
            # The WORST of the cohort's phenotypes, and null when none was
            # measurable — not 0.0. A phenotype with too few annotated spans to
            # score is a different fact from one that scored zero, and `hfpef`
            # is genuinely the second.
            recall = f"{min(recalls):.3f}" if recalls else "—"
            w(
                f"| **{name}** ({label}) | {row['notes']} | {evidence} "
                f"| {evidence / max(row['notes'], 1):.2f} | {with_any} | {share:.2f} "
                f"| {recall} |"
            )

    if payload.get("unavailable"):
        # SORTED, not insertion-ordered. `--from-table` re-renders a payload
        # that went through `json.dumps(sort_keys=True)`, so an insertion-order
        # join made the re-rendered document differ from the measuring run's by
        # exactly this line — a reproducibility failure in the one artifact
        # whose whole job is to be reproducible.
        entries = sorted(payload["unavailable"].items())
        w("\n_Unavailable:_ " + "; ".join(f"{k} — {v}" for k, v in entries))


def cmd_compare(
    args: argparse.Namespace,
) -> int:
    """Baseline versus corrupted, measured with the SAME instrument.

    **The output the pipeline was missing.** A run produced a corrupted note and
    a dose ledger saying where edits *landed*. Neither says what the corruption
    did to the note's *content* — how many diseases survived, whether the
    medications a phenotype depends on are still findable. That is the question
    a robustness experiment is actually asking.

    **Both sides go through `metrics.concepts.profile_concepts`.** Not a
    corrupted-specific measure, not a diff of the edit script: literally the
    same function over the pristine text and over the corrupted text. That is
    what makes the delta meaningful — a change in the table is a change the
    baseline instrument can see, so it is a change any downstream model sees
    too.

    **Deltas are negative by convention and that is the interesting direction.**
    A corruption that *adds* concepts (a typo accidentally spelling a drug) is
    reported as a positive delta rather than hidden, because it is a real
    property of the perturbation and one this package can otherwise only
    speculate about.
    """
    from robustehr.corpus import read_documents
    from robustehr.document import Document
    from robustehr.edits.apply import apply_edits
    from robustehr.metrics.describe import level_characteristics
    from robustehr.store import read_doses, read_edits

    try:
        declared = _load_phenotypes(args)
    except (FileNotFoundError, KeyError) as exc:
        print(f"cannot build phenotypes: {exc}", file=sys.stderr)
        return 2

    # The concept half is OPTIONAL: every structural level is measurable with
    # no terminology at all, which is what lets a reader without a UMLS licence
    # reproduce half of Table 1 after corrupting a corpus.
    profile = _concept_profiler(args, declared)

    originals = {d.uid: d for d in read_documents(Path(args.corpus), limit=args.limit)}
    baselines = {uid: profile(doc) for uid, doc in originals.items()} if profile is not None else {}
    structural_before = {uid: level_characteristics(doc) for uid, doc in originals.items()}

    # Rebuild each corrupted note from its edit script rather than reading text
    # from disk: the edit script is the artifact that always exists, and
    # reconstructing from it proves the row describes the run being reported.
    by_cell: dict[tuple[str, str, str], list[Any]] = {}
    for row in read_edits(Path(args.run)):
        if row.note_uid in originals:
            by_cell.setdefault((row.note_uid, row.cell_id, row.severity), []).append(row)

    rows: list[dict[str, Any]] = []
    for dose in read_doses(Path(args.run)):
        uid = str(dose["note_uid"])
        if uid not in originals:
            continue
        cell = (uid, str(dose["op_id"]), str(dose["severity"]))
        edits = tuple(r.to_edit() for r in by_cell.get(cell, []))
        text = apply_edits(originals[uid].text, edits).text
        corrupted_doc = Document.from_text(text, uid=uid)
        out: dict[str, Any] = {
            "note_uid": uid,
            "op_id": dose["op_id"],
            "severity": dose["severity"],
            "target": dose.get("scope", "all"),
            "applied_n": dose["applied_n"],
            "conflicts_dropped": dose.get("conflicts_dropped", 0),
            # The structural half: the SAME `level_characteristics` that built
            # Table 1, run over the corrupted text. This is what makes the
            # baseline framework usable after corruption rather than only
            # before it — an operator's effect shows up as a change in the very
            # level whose count decided its dose.
            "level_delta": _level_delta(
                structural_before[uid], level_characteristics(corrupted_doc)
            ),
        }
        if profile is not None:
            after = profile(corrupted_doc)
            before = baselines[uid]
            categories = sorted(set(before.by_category) | set(after.by_category))
            out |= {
                "concepts_before": before.concepts,
                "concepts_after": after.concepts,
                "concepts_delta": after.concepts - before.concepts,
                "distinct_cuis_delta": after.distinct_cuis - before.distinct_cuis,
                "by_category_delta": {
                    c: after.by_category.get(c, 0) - before.by_category.get(c, 0)
                    for c in categories
                    if after.by_category.get(c, 0) != before.by_category.get(c, 0)
                },
                "phenotype_evidence_before": before.phenotype_evidence,
                "phenotype_evidence_after": after.phenotype_evidence,
                "phenotype_evidence_delta": after.phenotype_evidence - before.phenotype_evidence,
            }
        rows.append(out)

    payload = {
        "what": "the baseline characterisation and the corrupted one, same instrument",
        "instrument": (
            "metrics.describe.level_characteristics over both texts"
            + (", plus metrics.concepts.profile_concepts" if profile is not None else "")
        ),
        "run": str(args.run),
        "corpus": Path(args.corpus).name,
        "phenotypes": sorted(args.phenotype or []),
        "targeting": _targeting_manifest(args),
        "notes": len(originals),
        "cells": len(rows),
        "concepts_measured": profile is not None,
        "rows": rows,
    }
    if profile is None:
        payload["unavailable"] = {
            "concepts": (
                f"no terminology index at {args.index}; structural and character "
                "levels are reported and need none"
            )
        }
    if args.markdown:
        _compare_markdown(rows)
    else:
        _emit(payload, path=args.out)
    return 0


def _concept_profiler(args: argparse.Namespace, declared: list[Any]) -> Callable[[Any], Any] | None:
    """A concept profiler, or ``None`` when no terminology index is available.

    ``None`` is a supported mode rather than a failure: `compare` then reports
    the structural and character deltas, which need no licence, and says so in
    `unavailable` rather than emitting empty concept columns.
    """
    from robustehr.concepts.matcher import index_present, quickumls_available

    if not index_present(Path(args.index)) or not quickumls_available():
        # Index or extra missing: report the structural and character deltas,
        # which need no licence, rather than crashing several frames down in
        # `annotate`. The caller records this in `unavailable`.
        return None
    from robustehr.concepts.matcher import ConceptMatcher
    from robustehr.concepts.pipeline import annotate_document, qualify_document
    from robustehr.metrics.concepts import profile_concepts

    matcher = ConceptMatcher(Path(args.index))

    def profile(doc: Any) -> Any:
        mentions = annotate_document(doc, matcher)
        assertions = None
        if not args.no_assertions:
            assertions = qualify_document(doc, mentions).as_map() or None
        evidence = _evidence_index(doc, mentions, declared, assertions)
        return profile_concepts(doc, mentions, evidence, assertions)

    return profile


def _level_delta(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Per-level, per-field change, omitting everything that did not move.

    Omitting zeros is the point rather than an economy. A run of
    `render.header_delete` changes the header level and nothing else, and a
    table that printed a zero for all twelve other levels would bury that in
    noise. What is left is exactly the corruption's footprint — and where it
    reaches a level the operator does not name, that is a finding: deleting
    headers also merges the sections beneath them.
    """
    out: dict[str, dict[str, int]] = {}
    for level in sorted(set(before) | set(after)):
        fields = {**before.get(level, {}), **after.get(level, {})}
        moved = {}
        for field_name in sorted(fields):
            was = before.get(level, {}).get(field_name)
            now = after.get(level, {}).get(field_name)
            if isinstance(was, int) and isinstance(now, int) and was != now:
                moved[field_name] = now - was
        if moved:
            out[level] = moved
    return out


def _compare_markdown(rows: list[dict[str, Any]]) -> None:
    """One line per cell, deltas only. For pasting into a manuscript."""
    if not rows:
        print("no cells to compare")
        return
    width = max(len(str(r["op_id"])) for r in rows)
    if not any("concepts_before" in r for r in rows):
        # Structure-only: no terminology was available, so print the half that
        # needs none rather than a table of empty concept columns.
        print(f"{'operator':<{width}} {'sev':>8} {'applied':>8}  structural change")
        for r in rows:
            moved = "; ".join(
                f"{level}.{f} {v:+d}"
                for level, fields in sorted(r["level_delta"].items())
                for f, v in sorted(fields.items())
            )
            print(f"{r['op_id']:<{width}} {r['severity']:>8} {r['applied_n']:>8}  {moved or '—'}")
        return
    print(
        f"{'operator':<{width}} {'sev':>8} {'applied':>8} {'concepts':>9} "
        f"{'delta':>7} {'pheno d':>8}  by category"
    )
    for r in rows:
        cats = ", ".join(f"{k} {v:+d}" for k, v in sorted(r["by_category_delta"].items())[:4])
        print(
            f"{r['op_id']:<{width}} {r['severity']:>8} {r['applied_n']:>8} "
            f"{r['concepts_before']:>9} {r['concepts_delta']:>+7} "
            f"{r['phenotype_evidence_delta']:>+8}  {cats}"
        )


def cmd_ambiguity(args: argparse.Namespace) -> int:
    """Count and locate ambiguous abbreviations across a corpus.

    A baseline-quality measurement in the same sense as ``baseline``: a property
    of the notes before any operator runs, and a plausible stratifier for a
    robustness result.
    """
    from robustehr.concepts.matcher import ConceptMatcher
    from robustehr.corpus import read_documents
    from robustehr.metrics.ambiguity import (
        AMBIGUOUS_AT,
        HIGHLY_AMBIGUOUS_AT,
        profile_ambiguity,
    )

    matcher = ConceptMatcher(Path(args.index))
    rows: list[dict[str, object]] = []
    surfaces: Counter[str] = Counter()
    worst: dict[str, int] = {}
    totals: Counter[str] = Counter()
    abbreviations = ambiguous = highly = ambiguous_snomed = 0

    for doc in read_documents(Path(args.corpus), limit=args.limit):
        found = profile_ambiguity(doc, matcher, keep_occurrences=not args.counts_only)
        totals.update(found.counts)
        abbreviations += found.abbreviations
        ambiguous += found.ambiguous
        highly += found.highly_ambiguous
        ambiguous_snomed += found.ambiguous_snomed
        surfaces.update(found.ambiguous_surfaces())
        for surface, senses in found.most_ambiguous(limit=1000):
            worst[surface] = max(worst.get(surface, 0), senses)
        if args.per_note:
            rows.append(found.to_row())

    _emit(
        {
            "what": (
                "abbreviation-shaped tokens and how ambiguous each is, before any operator runs"
            ),
            "bands": (
                f"ambiguous = {AMBIGUOUS_AT}+ UMLS concepts as written; "
                f"highly ambiguous = {HIGHLY_AMBIGUOUS_AT}+. The SNOMED count is "
                "the same question asked of the space a phenotype is declared in."
            ),
            "corpus": Path(args.corpus).name,
            "abbreviations": abbreviations,
            "ambiguous": ambiguous,
            "highly_ambiguous": highly,
            "ambiguous_snomed": ambiguous_snomed,
            "ambiguity_rate": (None if not abbreviations else round(ambiguous / abbreviations, 4)),
            "high_ambiguity_rate": (
                None if not abbreviations else round(highly / abbreviations, 4)
            ),
            "outcomes": dict(sorted(totals.items())),
            "most_frequent_ambiguous": [
                {"surface": s, "occurrences": n, "senses": worst.get(s, 0)}
                for s, n in surfaces.most_common(args.top)
            ],
            "per_note": rows or None,
        }
    )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Reconstruct a stored run from its edit scripts and verify every hash.

    This is the check that makes the released artifact meaningful: a reader with
    their own licensed copy of the corpus reproduces every corrupted byte, or
    finds out precisely which cell disagrees.
    """
    from robustehr.corpus import read_records
    from robustehr.store import iter_texts, replay, verify_note_hashes

    records, _ = read_records(Path(args.corpus), limit=args.limit)
    texts = iter_texts(records)

    mismatched = verify_note_hashes(Path(args.run), texts)
    if mismatched:
        print(
            f"error: {len(mismatched)} note(s) differ from the run's inputs, "
            f"e.g. {mismatched[:3]}. The corpus is not the one this run used.",
            file=sys.stderr,
        )
        return 1

    results = replay(Path(args.run), texts)
    failed = [r for r in results if not r.verified]
    _emit(
        {
            "cells_checked": len(results),
            "verified": len(results) - len(failed),
            "failed": len(failed),
            "failures": [
                {"note_uid": r.note_uid, "op_id": r.op_id, "severity": r.severity}
                for r in failed[:20]
            ],
        },
        path=args.out,
    )
    if not results:
        print("no cells could be checked; is the corpus the right one?", file=sys.stderr)
        return 1
    return 1 if failed else 0


def _coverage_row(counts: tuple[int, int]) -> dict[str, object]:
    covered, total = counts
    return {
        "content_tokens": total,
        "inside_a_gold_span": covered,
        "fraction": round(covered / total, 4) if total else None,
    }


def cmd_eval_crosswalk(args: argparse.Namespace) -> int:
    """Map the challenge's SNOMED concepts to UMLS semantic types. Runs once."""
    from robustehr.eval.snomed_el import build_crosswalk

    mapping = build_crosswalk(Path(args.root), Path(args.umls))
    _emit({"concepts_mapped": len(mapping)})
    return 0


def cmd_eval_snomed(args: argparse.Namespace) -> int:
    """Run the ablation ladder against the SNOMED CT Entity Linking Challenge.

    The run that turns L0-versus-L1 differences into accuracy, and settles
    whether T033 Finding belongs in the default.
    """
    from robustehr.concepts.matcher import ConceptMatcher, MatcherConfig
    from robustehr.eval import snomed_el
    from robustehr.eval.ablation import gold_coverage, report, run, write_report
    from robustehr.lexicon import load_clinical_lexicon

    corpus = snomed_el.load(Path(args.root), limit=args.limit)
    if args.split:
        corpus = corpus.split(args.split)
    lexicon = load_clinical_lexicon(Path(args.lexicon))
    matcher = None if args.no_concepts else ConceptMatcher(Path(args.index))

    results = run(corpus, lexicon, matcher=matcher)
    payload = report(
        results,
        notes=len(corpus.notes),
        config=matcher.config if matcher else MatcherConfig(),
        extra={
            "split": args.split or "all",
            "gold_spans": len(corpus.spans),
            "lexicon_source": lexicon.source,
            "gold_token_coverage": _coverage_row(gold_coverage(corpus)),
        },
    )
    if args.out:
        write_report(Path(args.out), payload)
        print(f"wrote {args.out}", file=sys.stderr)
    _emit(payload)
    return 0


def cmd_target(args: argparse.Namespace) -> int:
    """Resolve a target spec and say what it selects.

    Targets feed the seed, so being able to check one before committing a sweep
    to it is worth a subcommand: a mistyped target that silently selects nothing
    produces a run of legitimate-looking zero doses.
    """
    from robustehr.categories import load_categories
    from robustehr.target import describe, parse

    target = parse(args.spec)
    payload: dict[str, object] = {
        "spec": args.spec,
        "canon": target.canon(),
        "describes": describe(target),
    }
    if args.spec.startswith("cat="):
        names = args.spec.removeprefix("cat=").split(",")
        categories = load_categories()
        payload["categories"] = {
            n: {
                "label": categories[n].label,
                "tier": categories[n].tier.value,
                "semantic_types": sorted(categories[n].tuis),
                "definition": categories[n].definition,
            }
            for n in names
        }
    _emit(payload)
    return 0


# -- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - one block per subcommand
    parser = argparse.ArgumentParser(
        prog="robustehr",
        description="Deterministic, dose-calibrated perturbation of clinical text.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"robustehr {__version__} (schema {SCHEMA_VERSION})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tax = sub.add_parser("taxonomy", help="list or describe the operator taxonomy")
    tax.add_argument(
        "--phenotypes",
        action="store_true",
        help="list the shipped phenotype definitions and their measured recall",
    )
    tax.add_argument("--describe", metavar="OP_ID", help="show one operator's full entry")
    tax.add_argument("--yaml", action="store_true", help="emit the taxonomy as YAML")
    tax.set_defaults(func=cmd_taxonomy)

    seg = sub.add_parser("segment", help="segment one note and report its structure")
    seg.add_argument("path")
    seg.set_defaults(func=cmd_segment)

    app = sub.add_parser("applicability", help="unit counts per note across a corpus")
    app.add_argument("--corpus", required=True)
    app.add_argument("--limit", type=int, default=None)
    app.add_argument("--out", type=Path, default=None)
    app.set_defaults(func=cmd_applicability)

    con = sub.add_parser("concepts", help="terminology-derived resources")
    con_sub = con.add_subparsers(dest="concepts_command", required=True)

    build = con_sub.add_parser("build-lexicon", help="derive the clinical vocabulary from UMLS")
    build.add_argument("--umls", default="data/umls", help="root holding e.g. 2026AA/META/")
    build.add_argument("--out", default=str(DEFAULT_LEXICON_PATH))
    build.add_argument("--db", default=None, help="persist the DuckDB database here")
    build.set_defaults(func=cmd_concepts_build_lexicon)

    val = con_sub.add_parser("validate", help="measure the morphology fallback against UMLS")
    val.add_argument("--corpus", required=True)
    val.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    val.add_argument("--limit", type=int, default=None)
    val.add_argument("--out", type=Path, default=None)
    val.set_defaults(func=cmd_concepts_validate)

    base = sub.add_parser("baseline", help="profile existing degradation in a corpus")
    base.add_argument("--corpus", required=True)
    base.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    base.add_argument("--limit", type=int, default=None)
    base.add_argument("--per-note", action="store_true", help="include every note's row")
    base.add_argument("--out", type=Path, default=None)
    base.set_defaults(func=cmd_baseline)

    amb = sub.add_parser("ambiguity", help="count and locate ambiguous abbreviations in a corpus")
    amb.add_argument("--corpus", required=True)
    amb.add_argument("--index", default="data/quickumls_index")
    amb.add_argument("--limit", type=int, default=None)
    amb.add_argument("--top", type=int, default=30)
    amb.add_argument("--per-note", action="store_true", help="emit a row per note, with spans")
    amb.add_argument(
        "--counts-only",
        action="store_true",
        help="skip per-token detail; faster on a large corpus",
    )
    amb.set_defaults(func=cmd_ambiguity)

    cp = sub.add_parser(
        "concept-profile", help="concepts, categories and phenotype evidence per note"
    )
    cp.add_argument("--corpus", required=True)
    cp.add_argument("--index", default="data/quickumls_index")
    cp.add_argument("--isa", default="data/umls_isa_mth.json")
    cp.add_argument("--crosswalk", default="data/snomed_el")
    cp.add_argument("--limit", type=int, default=None)
    cp.add_argument(
        "--phenotype",
        action="extend",
        nargs="*",
        metavar="NAME",
        default=None,
        help="declared phenotypes to count; see `taxonomy --phenotypes`. "
        "Repeatable, and space-separated names also work",
    )
    cp.add_argument(
        "--no-assertions",
        action="store_true",
        help="skip stage 8. The assertion breakdown is then omitted rather than "
        "reported as fully affirmed",
    )
    cp.add_argument(
        "--per-note",
        action="store_true",
        help="emit a row per note. Rows carry note_uid, so on a restricted "
        "corpus the output is note-derived and belongs in data/",
    )
    cp.add_argument("--out", type=Path, default=None)
    cp.set_defaults(func=cmd_concept_profile)

    run = sub.add_parser("run", help="apply a sweep and persist edit scripts")
    run.add_argument("--corpus", required=True)
    run.add_argument(
        "--config",
        metavar="RECIPE.yaml",
        default=None,
        help="a corruption recipe: which documents, which corruption families or "
        "operators, how many per document, what severity, and where it may land. "
        "Sets --operators, --salt, --target and --phenotype from the file. See "
        "robustehr.config for the schema",
    )
    run.add_argument("--out", required=True, help="directory for the run artifact")
    run.add_argument("--run-id", default="run")
    run.add_argument("--operators", nargs="*", default=None)
    run.add_argument(
        "--compose",
        action="store_true",
        help="merge every operator onto ONE note per severity instead of running "
        "each independently. Each still proposes against the pristine document, "
        "so replay is unchanged; edits lost to another operator are counted in "
        "dose.conflicts_dropped. Order-independent",
    )
    run.add_argument(
        "--emit-text",
        metavar="DIR",
        default=None,
        help="also write the corrupted notes. Corrupted text carries the "
        "corpus's licence, so DIR must be under data/ unless overridden",
    )
    run.add_argument(
        "--i-understand-the-licence",
        action="store_true",
        help="permit --emit-text to write outside data/. A corrupted MIMIC note is still MIMIC",
    )
    run.add_argument("--severities", nargs="*", default=["0.10", "0.30", "0.50"])
    run.add_argument(
        "--target",
        action="append",
        default=None,
        help="what to corrupt, i.e. the level of aim. Atoms: all (no aim), clinical "
        "(the measured clinical-content rule), pheno=NAME (one phenotype's evidence; "
        "pheno=* for any declared), and the finer predicates uncategorized, cat=NAME, "
        "tui=TUI, lex=CLASS, section=NAME, struct=CLASS. Combinators: all(a;b), "
        "any(a;b), not(a). Repeating the "
        "option intersects, so `--target cat=medication --target pheno=X` is "
        "the same target as `--target 'all(cat=medication;pheno=X)'`",
    )
    run.add_argument("--salt", default="rep0")
    run.add_argument(
        "--param",
        action="append",
        default=None,
        metavar="OPERATOR:KEY=VALUE",
        help="set one operator's parameter, e.g. "
        "`input.ocr_confusion:max_edits_per_token=1` or `input.typo:include_mixed=true`. "
        "Repeatable. Parameters feed the seed and are recorded on every dose row; "
        "docs/corruption-catalogue.md lists what each operator accepts",
    )
    run.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    run.add_argument("--limit", type=int, default=None)
    run.add_argument(
        "--phenotype",
        # `extend`, not the plain `nargs="*"` this was. Repeating the option
        # OVERWROTE, so `--phenotype a --phenotype b` declared only `b` — and
        # the loss is invisible: an undeclared phenotype is simply never
        # counted, and the run reports evidence_touch 0 for it exactly as it
        # would for a note that never mentioned it.
        action="extend",
        nargs="*",
        default=None,
        metavar="NAME",
        help="declared phenotypes to protect or target; see `taxonomy "
        "--phenotypes`. Repeatable, and space-separated names also work",
    )
    run.add_argument(
        "--phenotype-scope",
        choices=[s.value for s in PhenotypeScope],
        default=PhenotypeScope.AGNOSTIC.value,
        help="agnostic (default, skips the clinical layer entirely), protect "
        "(evidence withheld from every operator), or target (every operator "
        "restricted to evidence)",
    )
    run.add_argument(
        "--no-assertions",
        action="store_true",
        help="skip stage 8 (ConText). Evidence is then reported as unqualified "
        "rather than affirmed, and evidence_touch_affirmed is omitted rather "
        "than zeroed",
    )
    run.add_argument("--index", default="data/quickumls_index")
    run.add_argument("--isa", default="data/umls_isa_mth.json")
    run.add_argument("--crosswalk", default="data/snomed_el")
    run.set_defaults(func=cmd_run)

    desc = sub.add_parser("describe", help="Table 1: one characterisation of a corpus")
    desc.add_argument(
        "--corpus",
        required=False,
        default=None,
        help="the note corpus. Not needed with --from-table",
    )
    desc.add_argument(
        "--run",
        default=None,
        metavar="RUN_DIR",
        help="characterise the CORRUPTED corpus this run produced, one table per "
        "(operator, severity) cell, reconstructed from the stored edit scripts. "
        "Needs --corpus for the originals. Structural and character levels only",
    )
    desc.add_argument(
        "--from-table",
        default=None,
        metavar="JSON",
        help="re-render an already-written table instead of measuring a corpus. "
        "The documents are a pure function of the table, so a formatting change "
        "costs a second rather than a full annotation pass",
    )
    desc.add_argument("--limit", type=int, default=None)
    desc.add_argument("--index", default="data/quickumls_index")
    desc.add_argument("--isa", default="data/umls_isa_mth.json")
    desc.add_argument("--crosswalk", default="data/snomed_el")
    desc.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    desc.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    desc.add_argument("--no-concepts", action="store_true", help="structural blocks only")
    desc.add_argument("--no-assertions", action="store_true")
    desc.add_argument(
        "--cui-map",
        action="store_true",
        help="also emit every mention as (note_uid, cui, span, tuis). Identifiers "
        "and offsets only, but keyed by note — write it under data/",
    )
    desc.add_argument(
        "--groups",
        default=None,
        metavar="CSV",
        help="a wide CSV of binary label columns keyed by note_id. Each column "
        "becomes a cohort and gets its own Table 1, annotated with that "
        "cohort's phenotype. Cohorts overlap; they are not a partition",
    )
    desc.add_argument(
        "--group-map",
        default=None,
        metavar="NAME|FILE",
        help="which phenotype each label column corresponds to. Either a set "
        "name packaged in resources/label_groups.yaml (e.g. `mipa`), or a path "
        "to a YAML file of the same shape — append #setname if it declares more "
        "than one. Without it, a column stands for the phenotype of the same name",
    )
    desc.add_argument(
        "--group-out",
        default=None,
        metavar="DIR",
        help="write one Table 1 document per cohort into DIR, markdown beside "
        "JSON. Needs --groups. Note-derived: keep under data/",
    )
    desc.add_argument(
        "--per-note",
        action="store_true",
        help="also emit a row per note. Rows carry note_uid, so on a restricted "
        "corpus the output is note-derived and belongs in data/",
    )
    desc.add_argument(
        "--markdown",
        action="store_true",
        help="a digestible Table 1 — one table, indented rows — plus Table 2 "
        "when --groups is given. `--detail` adds the per-level audit tables",
    )
    desc.add_argument(
        "--detail",
        action="store_true",
        help="with --markdown, also print the per-level audit tables: section "
        "presence over the 58 canonical ids, cohort comparison, and each "
        "level's own breakdown",
    )
    desc.add_argument("--out", type=Path, default=None)
    desc.set_defaults(func=cmd_describe)

    cmp_ = sub.add_parser("compare", help="baseline vs corrupted concept profile, same instrument")
    cmp_.add_argument("--run", required=True, help="a directory written by `robustehr run`")
    cmp_.add_argument("--corpus", required=True)
    cmp_.add_argument("--index", default="data/quickumls_index")
    cmp_.add_argument("--isa", default="data/umls_isa_mth.json")
    cmp_.add_argument("--crosswalk", default="data/snomed_el")
    cmp_.add_argument("--limit", type=int, default=None)
    cmp_.add_argument("--phenotype", action="extend", nargs="*", metavar="NAME", default=None)
    cmp_.add_argument("--no-assertions", action="store_true")
    cmp_.add_argument("--markdown", action="store_true", help="print a table instead of JSON")
    cmp_.add_argument("--out", type=Path, default=None)
    cmp_.set_defaults(func=cmd_compare)

    rep = sub.add_parser("replay", help="reproduce a stored run and verify hashes")
    rep.add_argument("--run", required=True, help="directory written by `run`")
    rep.add_argument("--corpus", required=True, help="your own copy of the notes")
    rep.add_argument("--limit", type=int, default=None)
    rep.add_argument("--out", type=Path, default=None)
    rep.set_defaults(func=cmd_replay)

    ev = sub.add_parser("eval", help="validate against a gold-standard corpus")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)

    xw = ev_sub.add_parser("crosswalk", help="map SNOMED concepts to semantic types")
    xw.add_argument("--root", default="data/snomed_el")
    xw.add_argument("--umls", default="data/umls")
    xw.set_defaults(func=cmd_eval_crosswalk)

    sn = ev_sub.add_parser("snomed", help="run the ablation ladder on the challenge")
    sn.add_argument("--root", default="data/snomed_el")
    sn.add_argument("--index", default="data/quickumls_index")
    sn.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    sn.add_argument("--split", default=None, help="e.g. test; omit for all")
    sn.add_argument("--limit", type=int, default=None, help="first N notes")
    sn.add_argument("--no-concepts", action="store_true", help="L0 only")
    sn.add_argument("--out", default=None)
    sn.set_defaults(func=cmd_eval_snomed)

    tgt = sub.add_parser("target", help="explain a target specification")
    tgt.add_argument("spec", help="e.g. cat=medication, uncategorized, tui=T047")
    tgt.set_defaults(func=cmd_target)

    cls = con_sub.add_parser("classify", help="token-class breakdown over a corpus")
    cls.add_argument("--corpus", required=True)
    cls.add_argument("--lexicon", default=str(DEFAULT_LEXICON_PATH))
    cls.add_argument("--limit", type=int, default=None)
    cls.add_argument("--out", type=Path, default=None)
    cls.set_defaults(func=cmd_concepts_classify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _emit_corrupted(
    out: Path, texts: dict[tuple[str, str, str], str], acknowledged: bool
) -> int | None:
    """Write the corrupted notes, or refuse. ``None`` means refused.

    **Why this is opt-in and gated.** Everything else a run persists is offsets,
    counts and hashes — which is exactly why an edit script is redistributable
    while the corpus behind it is not. Corrupted text is not: it is the note,
    with some characters changed, and it inherits every restriction the original
    carried. A MIMIC-derived corrupted note is still MIMIC.

    So the default destination is under ``data/``, which is gitignored
    default-deny, and writing anywhere else requires the caller to say out loud
    that they know what the text is. That is a speed bump, not a security
    control — the point is that nobody emits a licensed corpus to a shared path
    by reflex.
    """
    resolved = out.resolve()
    inside_data = Path("data").resolve() in resolved.parents or resolved == Path("data").resolve()
    if not inside_data and not acknowledged:
        print(
            f"refusing to write corrupted notes to {out}.\n"
            "Corrupted text is derived from the corpus and carries the corpus's "
            "licence — a corrupted MIMIC note is still MIMIC. Write under data/ "
            "(gitignored), or pass --i-understand-the-licence to override.",
            file=sys.stderr,
        )
        return None
    out.mkdir(parents=True, exist_ok=True)
    for (note_uid, op_id, severity), text in sorted(texts.items()):
        stem = f"{note_uid}__{op_id.replace('(', '_').replace(')', '').replace('+', '-')}"
        (out / f"{stem}__{severity.replace('/', '-')}.txt").write_text(text, encoding="utf-8")
    print(f"wrote {len(texts)} corrupted notes to {out}", file=sys.stderr)
    return len(texts)


if __name__ == "__main__":
    raise SystemExit(main())
