# Native document loader preservation evidence — 2026-10-09

Scope: TableSpec Python implementation 0.0.8, UMF companion contract 1.0.0,
BagIt 1.0 complete SHA-256 profile, PREMIS 3 semantic JSON mapping and PROV-O
JSON-LD. No Bun subprocess or PDF parser.

32 unit cases pass; Ruff lint and format checks pass. Coverage includes URL
admission/redirect refusal, rights, SHA pins, SEC contact, byte/retry/time budgets,
unchanged originals, failed refresh pointer preservation, immutable staged writes,
exact DuckDB constraints, read-back, offline BagIt closure, special files,
preservation/provenance fixity, explicit rights and postcommit cleanup.
Astra ultra reviewed and independently reproduced/fixed crash recovery,
truncation and late-chunk accounting; final disposition has no material findings
in the reviewed local slice. Earlier failed test attempts were corrected and
rerun; they are not qualification evidence.

Live native HTTPS acquired the three user-selected court originals. Python and
the pinned Bun 1.3.14 companion produced identical SHA-256 values:

| Source | SHA-256 |
| --- | --- |
| Loper Bright 22-451 | 12f5ea075004886774c25e7831ea1608fd0f831f0113e83bb0e85811c0a4bb6e |
| Trump 23-939 | 4cbb9bd0c0f023cd0273826e9481f16edd2ca942e5b378123d2478b66ef31746 |
| DCD 1:20-cv-03010 opinion | 4405d79bd64530edae9a3af325b27ba36c5cbd59c67a6d73c08a037f8f7dcd13 |

The 14-file/3,559,055-byte payload BagIt handoff passed independent bagit 1.9.0
validation. Offline native DuckDB published and read back all three metadata
rows and original objects with exact hashes. Test publishers prevent outbound
HTTPS and remove Bun from PATH. Scheduler audit validates all retained revisions.
The repository guide documents the exact fixture URLs and source rights.

Live Spark/Databricks serverless and UC filesystem behavior remain unqualified;
a caller-named workspace/table/volume is still needed. Native SEC live acquisition
requires the user's filers/contact. No Snowflake execution, PREMIS XML, OCFL
repository or WARC capture claim is made. The prepared development environment
used umf-core 0.8.0 serialization; released-wheel clean installation against
umf-core 0.8.1 is a separate release check.


Release correction 0.0.9: all 33 loader tests pass and whole-source Pyright reports
zero errors or warnings. The Spark CLI passes the required application name to
the central session factory. Astra ultra independently reviewed the corrections
and verified the loader tests and typing. Both website workflows serialize with
queued runs preserved, and deployment requires successful release asset upload.
The published 0.0.8 wheel was installed with --no-deps alongside umf-core 0.8.1
and published the three court originals offline to DuckDB with exact read-back.
