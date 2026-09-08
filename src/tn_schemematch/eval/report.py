"""Markdown report generation.

Produces the tables that go into the paper, plus the per-persona error listing that error
analysis actually runs on. Written as Markdown rather than LaTeX so the same artifact is
readable in a pull request, in a notebook, and pasted into a draft.

Two formatting conventions are deliberate. Metrics that can be undefined print ``—``
rather than ``0.00``, with the count of scored runs beside them, so a reader can never
mistake "did not answer" for "answered badly". And the false-positive column is placed
immediately after F1, because the whole argument of this project is that reading one
without the other is misleading.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .runner import PersonaScore, rq2_report, summarize

__all__ = ["markdown_report", "results_table", "rq2_table", "error_listing"]


def _fmt(value: Any, places: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value:.{places}f}"


def _cell(block: dict[str, Any], metric: str, places: int = 3) -> str:
    """Format an aggregate as ``mean`` or ``mean (n scored)`` when some runs were skipped."""
    stats = block.get(metric) or {}
    text = _fmt(stats.get("mean"), places)
    skipped = stats.get("n_skipped", 0)
    if skipped:
        text += f" ({stats.get('n_scored', 0)}/{stats.get('n_scored', 0) + skipped})"
    return text


def results_table(scores: Sequence[PersonaScore]) -> str:
    """Main results: one row per system and language condition."""
    summary = summarize(scores)
    header = (
        "| System | Condition | P | R | F1 | **FP rate** | Harmful FP | Exact | "
        "Retr. recall | Match recall | Gap | Questions | Q-precision | Errors |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for key, block in summary.items():
        system, condition = key.split("|")
        rows.append(
            f"| `{system}` | {condition} | "
            f"{_cell(block, 'precision')} | {_cell(block, 'recall')} | {_cell(block, 'f1')} | "
            f"**{_cell(block, 'fpr')}** | {_cell(block, 'harmful_fpr')} | "
            f"{_cell(block, 'exact_match', 2)} | "
            f"{_cell(block, 'retrieval_recall')} | {_cell(block, 'matching_recall')} | "
            f"{_cell(block, 'retrieval_gap')} | {_cell(block, 'n_questions', 1)} | "
            f"{_cell(block, 'question_precision')} | {block.get('n_errors', 0)} |"
        )
    return header + "\n".join(rows)


def rq2_table(scores: Sequence[PersonaScore], n_boot: int = 10000) -> str:
    """RQ2: code-mixed minus English, paired by persona."""
    report = rq2_report(scores, n_boot=n_boot)
    header = (
        "| System | Metric | Code-mixed | English | Δ | 95% CI | p | Pairs |\n"
        "|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for system, deltas in report.items():
        for row in deltas:
            marker = " **" if row["significant"] else " "
            rows.append(
                f"| `{system}` | {row['metric']} | {_fmt(row['mean_code_mixed'])} | "
                f"{_fmt(row['mean_english'])} |{marker}{_fmt(row['delta'])}{marker.strip()} | "
                f"[{_fmt(row['ci95'][0])}, {_fmt(row['ci95'][1])}] | "
                f"{_fmt(row['p_two_sided'])} | {row['n_pairs']} |"
            )
    if not rows:
        return "_No paired observations — RQ2 cannot be computed on this run._"
    return header + "\n".join(rows) + "\n\n**bold** = 95% interval excludes zero."


def error_listing(scores: Sequence[PersonaScore], limit: int = 40) -> str:
    """Every wrong answer, named. This is what error analysis is done from."""
    wrong = [s for s in scores if s.false_positives or s.false_negatives or s.error]
    if not wrong:
        return "_No errors._"
    lines = []
    for score in wrong[:limit]:
        parts = [f"- `{score.system}` / **{score.persona_id}** / {score.condition}:"]
        if score.error:
            parts.append(f" RUN FAILED — {score.error}")
        if score.false_positives:
            parts.append(f" wrongly offered {score.false_positives}")
        if score.false_negatives:
            parts.append(f" missed {score.false_negatives}")
        lines.append("".join(parts))
    if len(wrong) > limit:
        lines.append(f"- _... and {len(wrong) - limit} more_")
    return "\n".join(lines)


def _harm_ranking(scores: Sequence[PersonaScore]) -> str:
    """Which schemes get wrongly offered most often, across all systems."""
    counts: dict[str, int] = {}
    for score in scores:
        for scheme_id in score.false_positives:
            counts[scheme_id] = counts.get(scheme_id, 0) + 1
    if not counts:
        return "_No false positives in this run._"
    lines = ["| Scheme | Times wrongly offered |", "|---|---|"]
    for scheme_id, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{scheme_id}` | {count} |")
    return "\n".join(lines)


def markdown_report(
    scores: Sequence[PersonaScore],
    *,
    title: str = "TN-SchemeMatch run",
    metadata: dict[str, Any] | None = None,
    notes: Iterable[str] = (),
    n_boot: int = 10000,
) -> str:
    """Assemble the full report."""
    meta = metadata or {}
    lines = [f"# {title}", ""]

    if not meta.get("kb_verified", False):
        lines += [
            "> **These numbers must not be reported.** No scheme in this KB has been",
            "> verified against a primary source, so the ground truth they are scored",
            "> against is provisional. See `docs/verification-protocol.md`.",
            "",
        ]
    if not meta.get("personas_validated", True):
        lines += [
            "> **Personas are not natively validated.** Any code-mixing effect below is",
            "> diagnostic only — the queries have not been checked by a native speaker,",
            "> so a measured gap could be an artefact of unnatural phrasing.",
            "",
        ]

    if meta:
        lines += ["## Run configuration", ""]
        lines += [f"- **{k}**: `{v}`" for k, v in meta.items()]
        lines += [""]

    lines += ["## Results", "", results_table(scores), ""]
    lines += ["## RQ2 — degradation under code-mixing", "", rq2_table(scores, n_boot), ""]
    lines += ["## Most-often wrongly offered schemes", "", _harm_ranking(scores), ""]
    lines += ["## Errors", "", error_listing(scores), ""]

    notes = list(notes)
    if notes:
        lines += ["## Reading these numbers", ""] + [f"- {n}" for n in notes] + [""]

    return "\n".join(lines)
