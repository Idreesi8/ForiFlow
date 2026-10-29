# Workspace sync and cleanup — 29 October 2026

The current laptop implementation is collected into a single source update:
officer Action Desk, complete case register, monitoring coverage, reviewed
assessments and decisions, statement/cash-flow inspection, model diagnostics,
team access management and reviewed reminders. The original credit ensemble
remains unchanged. The new input-applicability artefacts are included so a
fresh clone can reproduce the current serving setup.

The GitHub connector verified `Idreesi8` and repository push permission. Remote
references were fetched before preparing the update; the starting local commit
was one commit ahead of `main`, with no incoming remote changes.

## Public and local files

The repository includes application source, tests, dependency manifests, serving
artefacts, synthetic examples and implementation reports. The public update
excludes `.env`, real databases, dumps, raw training downloads, local QA evidence,
personal academic documents, slides and large design exports. Existing local
material is preserved. These exclusions are enforced in `.gitignore`.

A scan of the publish candidates found no matching live `.env` credentials,
provider-token patterns or private-key headers. This is a scoped check, not a
guarantee that every possible secret format can be recognised. Before cleanup,
a local ZIP snapshot and per-file SHA-256 inventory were saved under the ignored
`archive/github-sync-2026-10-29/` folder.

## Removed generated material

Nine inactive archived `ui-dist` directories contained 505 generated build files,
totalling 18,602,492 bytes. They were removed after recording their paths and
hashes. Source, build logs, screenshots and verification reports remain.
Three obsolete, unreferenced UCI download/preparation helpers were also removed;
their originals remain recoverable in the source snapshot. Dependencies,
serving models, data backups, Office drafts and unique artwork were retained.
After testing, ten Python/test cache directories (137 files, 3,912,958 bytes)
and an empty misplaced evidence directory were also removed. Together with the
three helpers (1,719 bytes), the cleanup removed 645 files totalling 22,517,169
bytes. This is removed file size, not net disk savings: the recovery snapshot
and new verification logs also occupy space.

Cleanup targets were resolved under this project and checked for reparse points.
No Docker volumes, running application containers or unrelated projects were
removed.

## Verification

- Frontend: 101 tests passed; production build passed.
- The complete native Windows backend run stalled in its backup-wrapper helper
  after the preceding test groups passed. It was stopped and is not reported
  as a complete pass. The separate run passed 856 tests, with 87 deselected,
  excluding PostgreSQL/ML-marked cases and the wrapper module. It reported one
  dependency deprecation warning; no dependency upgrade is implied.
- GitHub CI runs both backend engines and the frontend. Its PostgreSQL database
  now meets the register tests' disposable-database guard. A separate database
  enables the three overlapping account-management tests. Workflow permissions
  are limited to reading repository contents and jobs have time limits.
- Existing `v7` GitHub action refs were checked against their official repositories.

The first complete Linux surrogate run passed 958 tests and skipped 14, but
one offline research-publication test failed: Git had converted the new JSON
sidecar's CRLF line endings to LF, breaking its recorded raw-byte provenance.
The two serving JSON sidecars now disable Git text conversion explicitly.
Their exact laptop bytes and research-recorded hashes are preserved across
checkouts; no measured report, model parameter or data value was rewritten to
hide the mismatch. The updated commit's CI supersedes that failed run.

Local logs and removal manifests are intentionally excluded from Git. Remote
check results are authoritative on the commit's GitHub Actions page.
