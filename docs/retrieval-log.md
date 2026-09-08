# Retrieval log

Every source cited by a scheme added on or after **2026-09-08** has a row here, recording
that the page was actually fetched rather than recalled.

This exists because the provenance test that guards the KB
(`tests/test_kb_and_personas.py::test_every_scheme_cites_a_dated_source`) can only check
that a URL is a string beginning with `http`. That is unfalsifiable: a citation invented
from memory passes it exactly as well as one that was read. The log makes "cited" mean
something a reader can check, and
`test_sources_from_the_fetch_era_have_a_retrieval_record` enforces that every new citation
appears here.

Schemes whose sources would not retrieve are **not in the KB**. They are listed in
[unsourced-queue.md](unsourced-queue.md) with the reason, so the coverage gap is visible
rather than silently absent.

The two earlier batches (`retrieved: 2026-08-15`, `retrieved: 2026-09-04`) predate this
log and are exempt; their provenance is recorded in
[verification-log.md](verification-log.md).

| date | url | outcome | scheme(s) |
|---|---|---|---|
