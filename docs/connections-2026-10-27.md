# Connection readiness and matching CI dependencies

27 October 2026.

The local repository has origin `https://github.com/Idreesi8/ForiFlow.git`.
This identifies its configured remote; it does not establish account access.
GitHub was found in the available integration directory and suggested for
installation/account setup. Its connection is not yet confirmed. No repository
content was pushed, pull request created, external CI run dispatched or customer
data sent to a new service.

The existing GitHub workflow installed backend requirements without the Linux
constraints already used by the verified Docker image. Its backend dependency
cache considered only `requirements.txt`. The workflow now installs with
`-c constraints-linux.txt -r requirements.txt`, includes both files in the cache
key and runs `pip check` before the tests. No package versions were changed.

This aligns future Linux CI dependency resolution with the serving image.
It does not establish that remote GitHub checks have run. Local workflow
structure validation and a dependency check against the existing serving
container are recorded under `archive/connections-2026-10-27/`.

The existing app, database, model artefacts and credentials are unchanged by
this workflow/documentation update. Future repository access depends on
successful GitHub account setup. Real lender/ECIB integrations still require
their own provider access; see [SME data requirements](sme_data_requirements.md).

## Local verification and Docker recovery

Local YAML validation passed: both backend engines remain in the matrix, both
dependency files contribute to the cache key, and CI uses Docker's constraint
install command. The recovered serving container reports **No broken
requirements found** from `python -m pip check`. No remote GitHub CI execution
is claimed.

Docker's engine was unavailable during verification. A launch confirmed the
previous inaccessible `dockerInference` socket failure. The existing guarded
repair was previewed and applied; its first attempt preserved runtime folders
but stopped when the secrets runtime path already existed. A subsequent
launch confirmed the corresponding inaccessible `engine.sock` failure.

With Docker's Windows processes stopped and no WSL distributions running,
the remaining exact runtime folders were inspected: only zero-byte reparse
point socket entries were present. Those folders were preserved under unique
sibling names. Each original path was verified absent, then both directories
were recreated and verified empty before a new launch. Evidence includes
the partial repair manifest and separate preservation/empty-directory records;
the first repair is not presented as a complete success.

The engine recovered and the existing app images were started with no rebuild.
All three services passed health checks. No factory reset, Docker volume
removal, data-disk change, package update or credential change was performed.
The GitHub directory was checked again after verification: its integration
still reports not installed, so account setup remains outstanding.

## Idreesi8 local Git setup

At the user's explicit request, the installed GitHub shortcut was opened. It
is a Chrome-hosted GitHub app. Desktop state capture and browser discovery
timed out, so those interfaces did not establish a signed-in browser session.

Git Credential Manager 2.9.0 lists an existing `Idreesi8` account. Its official
login command, scoped to `https://github.com` and that username, reported
existing credentials without requiring a new device code. No token or password
was extracted or printed. The local checkout now sets
`credential.https://github.com.username=Idreesi8`; no global account or commit
author settings were changed.

`git ls-remote --exit-code origin HEAD` succeeded with interactive prompts
disabled, returning `01cae5779ad900b16f690581dc896832b1b1b5d4`. This verifies
repository read access, not write permission or a fresh online identity check.
The local Git setup is distinct from installing/authorizing the ChatGPT GitHub
integration, whose connection has not been confirmed. No commit or push was
performed during this setup.

### Authenticated repository access verified

After the user's desktop sign-in confirmation, the existing `Idreesi8`
credential selection was checked again. GitHub advertised `refs/heads/main`
as the default branch; fetching remote references completed successfully.
An authenticated push dry run also completed with `Everything up-to-date`.
Its source was the freshly fetched `refs/remotes/origin/main` and its target
was the same existing remote branch, with `--dry-run --no-verify` and
interactive authentication disabled. This verifies the Git transport's
authenticated repository access without publishing local changes or executing
local push hooks. No verification code was needed.

ForiFlow can therefore use the existing local Git/GitHub connection for
repository work. This result does not install or activate the separate
ChatGPT GitHub connector, whose latest installation status remains false.

## Later connector verification

This supersedes the earlier uninstalled status above. GitHub, Product Design
and OpenAI Developers were subsequently confirmed installed and enabled. The
GitHub connector returned the authenticated login `Idreesi8` and metadata for
`Idreesi8/ForiFlow`, including pull and push permissions. This was a read-only
verification; no repository changes were published. Installing OpenAI Developers
does not provision a paid API key or connect ForiFlow to an OpenAI model.
