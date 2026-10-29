# ForiFlow folder organization — 22 October 2026

The standalone ForiFlow work found across Desktop, Downloads and Office recovery
folders is consolidated in `C:\Users\LENOVO\Desktop\foriflow`.

- 1,232 original/duplicate/temporary file locations removed.
- 128 distinct useful files retained at organized destinations.
- 297 existing project files verified unchanged by SHA-256,
  including application code, current model files, local database and data.
- All four separate Desktop QA directories cleared and removed.
- 68.7 MiB net file storage saved before these small audit records.
- 16 old Git bundles removed after confirming every referenced commit remains
  an ancestor of the current repository HEAD.
- Recovered Office drafts remain historical drafts; their ZIP CRCs were checked.

The working application remains the existing v2.3.1 tree with the earlier local
fixes. The discovered v2.3.2 source/review packages are preserved under
`archive/releases/`; this organization did not merge or deploy that release.
Unique QA differences and evidence are under `archive/qa/`. Duplicate extracted
files are retained in the referenced release archives or existing working tree;
`manifest.csv` records the exact original path, kept location/member and hash.

Useful documents are in `docs/academic/`, presentations in `docs/presentations/`,
older artwork in `docs/assets/design-history/`, social images in `linkedin/assets/`,
and project context in `docs/project-notes/`. Archived Office recovery drafts,
an old experimental model and obsolete but useful diagnostic scripts have their
own folders inside `archive/`.

The scan inspected 254,229 file names and
52,030 directories. Application/system installations,
generated dependency/cache directories and junctions were excluded. Access was
denied to `C:\Users\WsiAccount` and
`C:\Users\LENOVO\AppData\Local\ElevatedDiagnostics`.

The Desktop launch shortcut remains available. Application-owned Cursor history
and snapshots stay in their managed locations; the authored canvas notes have
project copies. The WPS-managed cloud presentation also has a verified project
copy, with its synced original retained. Mixed personal/project context notes
were left in place. Unrelated school, internship and Tableau work was untouched.

`verification.json` contains the final checks and counts. `protected-files.csv`
records the integrity baseline; `package-contents.json` verifies each referenced
archived member. These local organization records and private QA material are
excluded from Git through the `archive/` rule.
