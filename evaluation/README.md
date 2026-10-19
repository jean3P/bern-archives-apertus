# Evaluation references

`references/draft-v1/` is a byte-for-byte copy of the source-checked J4 preparation snapshot. It contains public original-text excerpts and evaluator-only facts, not acquired model answers. Human semantic approval is pending. The runner verifies the original manifest and every artifact hash before use.

See [the technical guide, pages 6-7](../docs/stapfer-technical-guide.pdf#page=6) for review, scoring and the recorded results. Both models have saved development/evaluation runs and assisted human reviews; the separate document audit remains pending. Importing the evaluation modules does nothing.

The frozen manifest describes the **earlier preparation state**, including the then-unimplemented runner and then-planned M1 gate. It remains unchanged for provenance, not as a statement of current implementation status. Its `benchmark_execution_authorized: false` records that preparation did not authorize execution; it is not a machine permission grant. The CLI's `run` command actually calls the backend and must be invoked intentionally. The reference answers, expected statuses and known source IDs are evaluator-only; they are never runtime model hints.

`Read-PublicReferenceSource.ps1` is retained as preparation provenance only. Its relative paths belong to the original preparation location. The runner never executes it; do not treat it as a new pipeline step or use the application's derived outputs as their own independent reference.

Public-source provenance: Stapfer-Enquête scholarly edition / University of Bern and Swiss Federal Archives, source ZIP SHA256 `68eba6c4a7cc13eb3e0b6239b00a6ee21e2e0996a24de69224c3915480941c97`, member `stapferappdb_final_10.5.16.sql`. Source IDs, original spelling, markup and supplied archival references are preserved. Publication and reuse remain subject to the source's terms, linked in the repository README. **The MIT code licence does not relicense these archival excerpts.** No modern contributor fields, raw SQL dump, credentials or meeting transcript are included here.
