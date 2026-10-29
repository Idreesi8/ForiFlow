# ForiFlow — folder guide

Ye ForiFlow ka main folder hai. App chalane ke liye `start.bat` use karein.

| Folder | Kya rakha hai |
| --- | --- |
| `backend/`, `frontend/` | Current working application |
| `docs/academic/` | Proposals, assignments, bank letters aur study guides |
| `docs/presentations/` | Presentations aur defense slides |
| `docs/assets/` | Posters, graphics aur purane design concepts |
| `docs/project-notes/` | Project memory aur context notes |
| `linkedin/` | Posts aur social-media artwork |
| `backups/` | Existing database backups |
| `archive/releases/` | Preserved v2.3.2 source/review packages aur compressed QA packages |
| `archive/qa/` | Unique QA evidence, local settings aur scripts |
| `archive/office-recovery/` | Recovered Word/PowerPoint drafts |
| `archive/models/` | Purana experimental model |
| `archive/legacy-tools/` | Purane diagnostic/update tools |
| `archive/organization-2026-10-22/` | File movement/deletion manifest aur verification records |
| `.local/postgresql-16.15/` | Is laptop par isolated database tests ke liye portable PostgreSQL runtime |
| `archive/postgres-tests/` | Private PostgreSQL test logs; customer database ka backup nahi |

Current app v2.3.1 aur us par local fixes isi root mein hain. v2.3.2 ke packages
archive mein sambhal kar rakhe hain; unko current app mein merge nahi kiya gaya.

22 October 2026 ki organization ki [detailed report](docs/folder-organization-2026-10-22.md)
mein scope, verification aur retained app-managed files ki tafseel hai.

Current application ki mazeed improvements aur unki testing ki
[report](docs/improvements-2026-10-22.md) bhi available hai.
Reminders aur page recovery ki latest [follow-up report](docs/continuation-2026-10-22.md)
mein naya verification result hai.
PostgreSQL aur backup/restore ki [latest verification](docs/database-verification-2026-10-22.md)
bhi isi project mein hai.
Docker crash ki recovery aur container verification ka
[report](docs/docker-repair-2026-10-22.md) bhi yahin maujood hai.
Officer Action Desk ki [tafseel aur verification](docs/action-desk-2026-10-24.md)
bhi isi project mein hai.
Monthly monitoring calendar aur safe editing ki
[verification](docs/monitoring-calendar-2026-10-24.md) bhi yahin hai.
User-friendly dashboard, navigation, login aur assessment form ki
[report](docs/user-experience-2026-10-24.md) bhi available hai.
Poore application register ki search aur purane cases tak rasai ki
[verification](docs/complete-register-2026-10-26.md) bhi yahin hai.
Unsaved entries, statement reads aur decision-save verification ki
[report](docs/work-protection-2026-10-26.md) bhi available hai.
Pakistan-time dates, overdue alerts aur reminder schedule ki
[verification](docs/pakistan-time-2026-10-26.md) bhi yahin hai.
Credit decision ki final review, confirmation aur read-only reports ki
[tafseel](docs/decision-review-2026-10-27.md) bhi yahin hai.
Naye trained input-anomaly model, case diagnostics aur 25 ML scenarios ki
[tafseel](docs/ml-diagnostics-2026-10-27.md) bhi available hai.
Assessment save kiye baghair numerical inputs check karne ki
[verification](docs/input-checks-2026-10-27.md) bhi yahin hai.

29 October ki source sync aur generated-file cleanup ki
[report](docs/workspace-sync-2026-10-29.md) available hai. Personal academic
documents, slides, large design exports, private notes aur backups sirf laptop
par hain; public GitHub checkout mein in local folders ka hona zaroori nahi.
