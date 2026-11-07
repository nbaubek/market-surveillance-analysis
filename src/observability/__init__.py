"""Soda-based data observability: payload (ingestion), silver, gold.

Three observation planes, one tool:

- PAYLOAD   programmatic Soda scans over each converted chunk at ingestion
            time (the Databento API payload, post-contract-validation).
            Fails closed: a failed check aborts the append.
- SILVER    SodaCL scans on Athena after dbt merges — the cleaning
            guarantees hold (no R, no burst rows, key integrity).
- GOLD      SodaCL scans on Athena after gold rebuilds — reconciliation
            invariants re-checked independently of dbt tests (defense in
            depth: a broken build path should be caught by a plane that
            does not share it).

Run from the repo root:
    AWS_PROFILE=my-dev-profile uv run python -m src.observability.scan silver
    AWS_PROFILE=my-dev-profile uv run python -m src.observability.scan gold

Exit code 1 on any failed check (CI/Dagster-friendly).
"""
