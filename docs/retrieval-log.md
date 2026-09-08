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
| 2026-09-08 | https://en.wikipedia.org/wiki/Rashtriya_Swasthya_Bima_Yojana | 200 OK — eligibility + discontinuation extracted | rsby |
| 2026-09-08 | https://en.wikipedia.org/wiki/Kasturba_Gandhi_Balika_Vidyalaya | 200 OK — eligibility extracted | kgbv |
| 2026-09-08 | https://en.wikipedia.org/wiki/Stand-Up_India | 200 OK — eligibility extracted | stand-up-india |
| 2026-09-08 | https://en.wikipedia.org/wiki/Pradhan_Mantri_Awas_Yojana | 200 OK — urban only; duplicates pmay-clss, not added | (pmay-g) |
| 2026-09-08 | https://en.wikipedia.org/wiki/Pradhan_Mantri_Jan_Dhan_Yojana | 200 OK — too thin to encode, not added | (pmjdy) |
| 2026-09-08 | https://en.wikipedia.org/wiki/List_of_schemes_of_the_government_of_India | 200 OK — used to find correct article titles | (index) |
| 2026-09-08 | https://en.wikipedia.org/wiki/Deendayal_Antyodaya_Yojana | HTTP 404 | (day-nrlm) |
| 2026-09-08 | https://en.wikipedia.org/wiki/Pradhan_Mantri_Kisan_Maandhan_Yojana | HTTP 404 | (pm-kisan-maandhan) |
| 2026-09-08 | https://en.wikipedia.org/wiki/Rashtriya_Vayoshri_Yojana | HTTP 404 | (rvy) |
| 2026-09-08 | https://pmaymis.gov.in/ | 200 OK — woman-ownership clause only, no income thresholds | (pmay-u probe) |
| 2026-09-08 | https://pmvishwakarma.gov.in/ | 200 OK — confirms the existing pm-vishwakarma encoding | (pm-vishwakarma) |
| 2026-09-08 | https://pmkisan.gov.in/ | 200 OK — confirms the existing pm-kisan exclusions | (pm-kisan) |
