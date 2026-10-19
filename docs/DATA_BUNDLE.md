# Stapfer installation data bundle

`dataset-challenge3.tar.gz` is a fixed, gzip-compressed bootstrap tar for collaborators with access to this private repository. The accompanying `dataset-challenge3.manifest.json` records the archive hash, each file's hash/size, scope and validation results. It is not a backup of the server, an automatic update channel or a new benchmark result.

## Included data

- The complete public-field J2 projection under `data/derived/j2-full/`: JSONL/TSV exports, SQLite FTS index, transformation/source/policy records and completion checksums. It preserves 2,250 transcriptions, 92,524 answer rows and 60 questionnaire fields, including null/blank rows and historical editorial markup. These units are not interchangeable with documents/pages.
- The four unchanged `j4-bound-{apertus,qwen}-{development,evaluation}-03` saved runs under `runs/`, including their original seals, responses, delivered evidence, draft references and recorded source snapshots. Historical absolute paths inside audit records remain historical text, not this installation's configuration. Bundled source snapshots are not executed by installation.
- Original review exports under `runs/review-exports/`, preserving Jean/Jeni attribution, earlier exports and the explicitly identified Jean/assistant amendments. Human suggestions remain separate from model answers and expert transcriptions. Historical judgments are not retroactively HF-authenticated or independent expert gold.

## Excluded data

The archive excludes the raw SQL dump and its modern-contributor/internal fields, private `.env`/OAuth settings, tokens, model weights/caches, new account-specific `runs/reviewer-exports/`, old experiment archives, server logs and unrelated projects. New users generate their own session secrets and export their own reviews separately. Credential-pattern/field checks and the explicit public-field allowlist are safeguards, not an independent privacy certification of every historical sentence.

## Installation

Run `uv run --locked python -m scripts.setup` from a fresh clone. It detects the archive and places the data in the standard folders before configuring Docker. For an explicit import use `--data-archive dataset-challenge3.tar.gz`; it must match the trusted manifest in this checkout. A new install needs roughly 1 GiB free for unpacked files and temporary verification, plus separate Docker/model storage.

The importer accepts only regular files in the allowed dataset/run/export paths. It rejects traversal, absolute paths, Windows-special names, links/devices, duplicates, unexpected entries and checksum mismatches. It stages and validates the data before checking all existing-file conflicts. Matching files are reused; conflicting files are never replaced. A different existing dataset or saved run should be kept in another checkout rather than overwritten.

The existing corpus verifier, saved-run seals and response-bound review validator run offline. No model, SQL dump execution, benchmark acquisition or human judgment is produced by unpacking. The archive stays out of Docker's build context; runtime inputs use read-only mounts.

## Source and rights

The scholarly source is the Stapfer edition compiled by the University of Bern and published by the Swiss Federal Archives: [official catalogue](https://opendata.swiss/en/dataset/stapfer-enquete-schule-in-der-schweiz-1799), [source terms](https://opendata.swiss/terms-of-use#terms_open). Original IDs, source fingerprints, attribution and archival references remain in the projection. Only source rows marked `Internet` and the project's documented public-field allowlist are used.

The repository's MIT licence covers project code; it does not relicense the archival edition, model outputs, human review prose or model weights. Preserve their provenance and applicable source terms when sharing. Access to this private bootstrap bundle is not permission to publish an unreviewed server dump or private reviewer credentials. Model outputs and draft reference answers may be wrong; a citation or a human suggestion does not make them source facts.

## Maintainer packaging

To intentionally create a new archive in a fresh output directory:

```bash
uv run --locked python -m scripts.package_data --data-dir data/derived/j2-full --runs-dir runs --original-reviews-dir runs/review-exports --out-dir /path/to/new-bundle
```

The packager selects only the known corpus files, four frozen runs and original export collection, scans for credential-like fields/tokens and validates source artifacts before packaging. It refuses existing archive/manifest outputs. Review the archive before a deliberate release; do not repeatedly add changing runtime backups to Git history. The single compressed bootstrap is tracked explicitly, while unpacked folders remain ignored.
