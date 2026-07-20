# Backlink Hunter
A modern, local, unlimited backlink discovery and verification tool. It finds
**real, verified** backlinks to a target domain from live pages and from
Common Crawl archived records — and never invents data.
## What it does
- Discovers backlinks via: a candidate **URL list**, a **direct site crawl**
  (robots-respecting), and **Common Crawl** archived pages of seed domains.
- Builds an optional **local reverse link index** from Common Crawl for
  arbitrary "who links to me" queries.
- Verifies each backlink by parsing real HTML and confirming an actual hyperlink.
- Persists to SQLite (WAL). Exports CSV / JSON / TXT.
- Streamlit UI with real counters, Stop / Pause / Resume, filters, and
  factual local statistics.
## What it does NOT guarantee
- It does **not** cover 100% of the internet.
- It does **not** fabricate backlinks, progress, or authority scores.
- Common Crawl's CDX index is a **forward** index (URL → record). It cannot
  answer arbitrary reverse "who links to X" queries. True reverse lookups
  require the **Link Index Mode** (`--index`) which builds a local index.
- If nothing is found you will see exactly:
  `No verified backlinks were found from the selected data sources.`
## Verification labels
- `LIVE_CONFIRMED` — the hyperlink exists on the current live page.
- `ARCHIVED_CONFIRMED` — the hyperlink exists in the retrieved Common Crawl HTML.
- `ARCHIVED_ONLY` — archived evidence exists but the live page is unreachable or
  no longer contains the link. An unreachable page is **never** labeled live.
## Install (Windows PowerShell)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item config.example.json config.jsonRunPowershellCopied!Copypython tests\build_fixtures.py         # create binary fixtures (once)
python backlink_hunter.py --selftest   # local, offline verification
streamlit run backlink_hunter.py       # launch the UI
pytest -q                              # run the test suiteLink Index Mode (reverse lookups)PowershellCopied!Copypython backlink_hunter.py --index --collection CC-MAIN-2024-33 --seed example.org --max 2000 --index-db linkindex.db
python backlink_hunter.py --query example.com --index-db linkindex.dbIndexing streams WARC byte-ranges, checkpoints progress (resumable), and never
loads full datasets into memory.Storage & bandwidth warningIndexing large Common Crawl data can require substantial storage, bandwidth and
time. The tool prints an estimate before processing. Start with a small --max.Common Crawl explanationCommon Crawl publishes petabytes of web crawl data. This tool queries the public
CDX index to locate WARC records for seed domains, then fetches only the required
byte range of each WARC record and parses the archived HTML.Troubleshooting
PowerShell blocks venv activation → run the Set-ExecutionPolicy line above.
selectolax build issues → ensure Python 3.11+ and an up-to-date pip.
Common Crawl 404 on a collection → the collection name is wrong; check
https://index.commoncrawl.org/collinfo.json for valid names.
SQLite locked → WAL is enabled; retry, or ensure only one writer at a time.
ExportsCSV includes source/target URLs, anchor, rel, link type, verification status,
Common Crawl provenance (collection, WARC filename/offset/length), redirect chain.
TXT variants: source URLs, target URLs, unique source domains, URL pairs, full TSV.
Exports contain only real database rows.Legal & ethical crawling
Respects robots.txt for live crawling.
SSRF-guarded: blocks localhost, private/link-local/loopback/reserved ranges and
cloud metadata IPs; only http/https allowed.
Does not bypass authentication, CAPTCHAs, paywalls, DRM, or bot protection.
Does not execute downloaded JavaScript. TLS verification stays on.
Uses a single honest User-Agent; no identity rotation or rate-limit evasion.
TextUnwrapCopied!Copy
---
## Honest verification status (Phases 3–6)
I did **not** run this in-chat (no execution environment here), so I'm not claiming green test output I didn't see. Here's exactly what to run and what to expect:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # only if activation blocked
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item config.example.json config.json
python tests\build_fixtures.py        # writes tests/fixtures/sample_record.warc.gz
python backlink_hunter.py --selftest  # offline proof: detects 2 real backlinks, no fake data
pytest -q                             # unit tests (all offline/mocked)
streamlit run backlink_hunter.py      # launch UIExpected --selftest output:TextUnwrapCopied!CopyParsed title='Test Post', links=5, backlinks to example.com=2
  -> https://example.com/pr   [FOLLOW]  anchor='protocol relative'
  -> https://www.example.com/product   [NOFOLLOW]  anchor='this product'
SELFTEST OK: real backlink detected from fixture (no fabricated data).Live integration test: In the UI, pick "URL list", enter the target and a couple of real public URLs you know link to it → you'll get LIVE_CONFIRMED rows, or the exact No verified backlinks… message if none exist. For Common Crawl, use a real collection from collinfo.json.Two things I want to be straight about
I can't assert "tests pass" from my side — run pytest -q. If anything fails on your machine, paste the traceback and I'll fix it immediately.
selectolax ships prebuilt wheels for CPython 3.11/3.12 on Windows; if pip tries to build from source and fails, tell me and I'll swap the parser to BeautifulSoup + lxml (drop-in; I'll rewrite htmlparse.py).
Want me to also add the PostgreSQL optional backend for the link index, or a pytest integration marker that hits a harmless live endpoint? Say the word
