# Unsourced queue

Schemes that belong in this knowledge base but are **not in it**, because their source
would not retrieve.

They are listed rather than omitted for the same reason the KB keeps a discontinued scheme
and marks it: an absence that is recorded can be worked through, and an absence that is
not looks identical to a scheme that does not exist. A reader can tell from this file
exactly what the KB's coverage gap is and why.

Drafts, where written, live under `kb/staging/<code>/` — a sibling of `kb/schemes/`, so the
loader never sees them.

| scheme | jurisdiction | attempted source(s) | outcome | date |
|---|---|---|---|---|
| Sukanya Samriddhi Yojana | central | india.gov.in/spotlight/sukanya-samriddhi-yojana (403); en.wikipedia.org/wiki/Sukanya_Samriddhi_Account (200, content usable) | **Sourced, but blocked on vocabulary.** The rule needs the youngest daughter's age; the vocabulary has `daughters_count` but no age. Encoding it without that clause would admit every family with an adult daughter — an inclusion over-reach producing false positives. Held until a second girl-child scheme needs the same attribute, which makes the back-fill across 247 personas worth paying. | 2026-09-08 |
| PM Awas Yojana – Gramin | central | en.wikipedia.org/wiki/Pradhan_Mantri_Awas_Yojana (200) | Article covers the **urban** component only, which `pmay-clss` already encodes. No rural eligibility wording was retrieved, so the rural scheme is not encoded rather than being inferred from the urban one. | 2026-09-08 |
| PM Jan Dhan Yojana | central | en.wikipedia.org/wiki/Pradhan_Mantri_Jan_Dhan_Yojana (200) | Retrieved successfully but states only "open to Indian citizens, minors of 10 and older with a guardian". A single trivial age clause is not a rule worth adding — it would inflate every gold set while testing nothing. The overdraft and insurance benefits are described as discretionary and unquantified. | 2026-09-08 |
| Deendayal Antyodaya Yojana (NRLM/NULM) | central | en.wikipedia.org/wiki/Deendayal_Antyodaya_Yojana (404) | Article title does not exist under that name; not retrieved. | 2026-09-08 |
| PM Kisan Maandhan Yojana | central | en.wikipedia.org/wiki/Pradhan_Mantri_Kisan_Maandhan_Yojana (404) | Article title does not exist under that name; not retrieved. | 2026-09-08 |
| Rashtriya Vayoshri Yojana | central | en.wikipedia.org/wiki/Rashtriya_Vayoshri_Yojana (404) | Article title does not exist under that name; not retrieved. | 2026-09-08 |
