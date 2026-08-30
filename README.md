# Public AI News

A stdlib-only pipeline that collects deliberately public Hacker News story
metadata, removes identity-bearing fields and URL query data, applies a narrow
AI-engineering relevance gate, and prints a bounded digest.

This fresh repository contains no social tokens, cookies, browser profiles,
followed-account lists, personal handles, raw responses, query URLs, recipient
details, state databases, or history from another repository.

## Privacy boundary

The accepted input schema is intentionally narrow: title, canonical public
url, generic source, and numeric score. All other keys are dropped.
Handles in titles are replaced, URL queries/fragments are removed, and
private/following source labels become private-bridge.

An authenticated followed-account collector belongs in a private repository.
It may pass only these sanitized generic facts to this engine. Do not send a
follow graph, private timeline URL, author identity, token, raw response, or
personal state to a public workflow.

## Run

    PYTHONPATH=src python -m unittest discover -s tests -v
    PYTHONPATH=src python -m public_ai_news --input examples/news.json --max-items 5
    PYTHONPATH=src python -m public_ai_news --hacker-news --max-items 5

The public collector is unauthenticated, time-bounded, and capped at 50 source
items. Output is ephemeral and is not committed or uploaded as an artifact.

## GitHub Actions

The workflow has read-only permissions, pinned actions, a five-minute timeout,
no secrets, no artifacts, and one concurrency slot. Pull requests and pushes
run tests plus a synthetic smoke. Scheduled/manual runs also call the public
Hacker News API.

## License

MIT
