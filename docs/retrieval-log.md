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
| 2026-09-08 | https://en.wikipedia.org/wiki/National_Social_Assistance_Scheme | 200 OK — eligibility extracted | nsap-ignoaps |
| 2026-09-08 | https://en.wikipedia.org/wiki/Pradhan_Mantri_Suraksha_Bima_Yojana | 200 OK — eligibility extracted | pmsby |
| 2026-09-08 | https://en.wikipedia.org/wiki/Janani_Suraksha_Yojana | 200 OK — eligibility extracted | jsy |
| 2026-09-08 | https://en.wikipedia.org/wiki/National_Rural_Employment_Guarantee_Act,_2005 | 200 OK — eligibility extracted | mgnrega |
| 2026-09-08 | https://nsap.nic.in/circular.do?method=aboutus | DNS failure (ENOTFOUND) — fell back to secondary | nsap-ignoaps |
| 2026-09-08 | https://www.jansuraksha.gov.in/ | TLS: unable to verify first certificate — fell back to secondary | pmsby |
| 2026-09-08 | https://nrega.nic.in/MGNREGA_new/Nrega_home.aspx | HTTP 404 — fell back to secondary | mgnrega |
| 2026-09-08 | https://www.india.gov.in/spotlight/sukanya-samriddhi-yojana | HTTP 403 — not added, see unsourced-queue.md | (sukanya-samriddhi) |
| 2026-09-08 | https://www.pib.gov.in/PressReleasePage.aspx?PRID=1946976 | HTTP 403 | (probe) |
| 2026-09-08 | https://www.myscheme.gov.in/schemes/gls | 200 but client-rendered; no scheme content in HTML | (probe) |
| 2026-09-08 | https://sevasindhuservices.karnataka.gov.in/ | TLS: unable to verify first certificate | (probe) |
