# Public AI News

A standard-library-only pipeline that collects deliberately public AI news
metadata, removes identity-bearing fields and URL query data, applies a narrow
AI-engineering relevance gate, and can deliver a bounded HTML digest by SMTP.

This repository contains no social tokens, cookies, browser profiles,
followed-account lists, personal handles, recipient details, mail credentials,
private source configuration, state databases, or generated reports.

## Privacy boundary

The accepted input schema is intentionally narrow: title, canonical public
article/discussion URLs, generic source label, bounded public source extract,
publication timestamp, and numeric engagement counts. All other keys are
dropped. Handles and secret-shaped assignments in text are redacted, URL
queries/fragments are removed, and private/following source labels become
`private-bridge`.

An authenticated followed-account collector belongs in a private repository.
It may pass only these sanitized generic facts to this engine. Do not send a
follow graph, private timeline URL, author identity, token, raw response, or
personal state to a public workflow.

## Run

    PYTHONPATH=src python -m unittest discover -s tests -v
    PYTHONPATH=src python -m public_ai_news --input examples/news.json --max-items 5
    PYTHONPATH=src python -m public_ai_news --hacker-news --max-items 5

The public collector is unauthenticated and time-bounded. Configured production
runs accept 1–20 bounded public sources through `NEWS_SOURCE_CONFIG_JSON` and
write structural counts only to Actions logs. Report contents, source choices
and recipient details are never committed, printed or uploaded as artifacts.

RSS/Atom, Hacker News Algolia, and Hacker News Firebase collectors preserve
source-provided dates and extracts. After ranking, at most 15 missing extracts
are filled from bounded public article metadata in four worker threads. No
article body is copied and no model-written claim is presented as a summary.

Ranking requires a technical signal beyond a company name or the word “AI,”
rejects recurring chatty/education-marketing patterns, excludes stale dated
items, prioritizes engineering sources, limits source concentration, and
clusters near-duplicate cross-source titles. Reports identify every extract as
source material and provide direct article/discussion actions.

## GitHub Actions

`ci.yml` has read-only permissions, pinned actions, a five-minute timeout, no
secrets or artifacts, and runs only for code events/manual checks. The separate
`news-digest.yml` production workflow runs daily only when
`ENABLE_NEWS_DIGEST=true`. Its manual dispatch defaults to dry-run.

Production requires encrypted secrets named `NEWS_SOURCE_CONFIG_JSON`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and
`REPORT_RECIPIENT`. Invalid source JSON or incomplete live SMTP configuration
fails closed instead of silently falling back or reporting success.

The digest ranks up to the requested maximum; it does not promise a minimum
story count when public sources are unavailable or no titles pass relevance.

## License

MIT
