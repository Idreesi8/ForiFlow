"""Execute real Windows/Bash wrappers with a fake Docker, and real PG scripts.

No test targets the user's database. PostgreSQL cases create UUID-named
databases on the explicitly configured disposable test server.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _bash():
    candidate = Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe'
    return str(candidate) if candidate.exists() else shutil.which('bash')


FAKE_DOCKER = r'''
import json, os, sys
from pathlib import Path
a = json.loads(os.environ['FAKE_DOCKER_ARGS']) if 'FAKE_DOCKER_ARGS' in os.environ else sys.argv[1:]
with open(os.environ['FAKE_EVENTS'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(a) + '\n')
stage = os.environ.get('FAKE_STAGE', '')
if a[:2] == ['compose', 'stop']:
    sys.exit(1 if stage == 'stop_failed' else 0)
if a[:2] == ['compose', 'ps']:
    if stage == 'still_running': print('synthetic-running-container')
    sys.exit(1 if stage == 'inspect_failed' else 0)
if a[:2] == ['compose', 'up']:
    sys.exit(1 if stage == 'restart_failed' else 0)
if a[:2] == ['compose', 'cp']:
    sys.exit(1 if stage == 'copy_failed' and 'backup-check' not in a[-1] else 0)
if a[:2] == ['compose', 'exec']:
    if '-s' in a:
        body = sys.stdin.read()
        with open(os.environ['FAKE_EVENTS'], 'a') as f:
            f.write(json.dumps(['INNER_VERIFY' if 'RESULT: PASS' in body else 'INNER_RESTORE']) + '\n')
        sys.exit({'inner_refused': 3, 'inner_failed': 4}.get(stage, 0))
    command = a[-1]
    if 'pg_dump' in command:
        if stage == 'backup_failed': sys.exit(1)
        sys.stdout.write('A' * 2000)
    if 'test -s' in command and stage == 'preflight_failed': sys.exit(1)
sys.exit(0)
'''


@pytest.fixture(scope='session')
def docker_stub(tmp_path_factory):
    folder = tmp_path_factory.mktemp('fake-docker-tools')
    script = folder / 'fake_docker.py'
    script.write_text(FAKE_DOCKER, encoding='utf-8')
    if os.name == 'nt':
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.exists():
            pytest.skip('Windows .NET compiler is unavailable for the native Docker stub')
        source = folder / 'Docker.cs'
        source.write_text(r'''
using System;
using System.Diagnostics;
using System.Web.Script.Serialization;
class Docker {
  static int Main(string[] args) {
    var info = new ProcessStartInfo(Environment.GetEnvironmentVariable("FAKE_PYTHON"));
    info.Arguments = "-X utf8 \"" + Environment.GetEnvironmentVariable("FAKE_SCRIPT") + "\"";
    info.UseShellExecute = false;
    info.EnvironmentVariables["FAKE_DOCKER_ARGS"] = new JavaScriptSerializer().Serialize(args);
    var child = Process.Start(info);
    child.WaitForExit();
    return child.ExitCode;
  }
}
''', encoding='utf-8')
        subprocess.run([str(compiler), '/nologo', '/r:System.Web.Extensions.dll',
                        f'/out:{folder / "docker.exe"}', str(source)], check=True, capture_output=True)
    else:
        launcher = folder / 'docker'
        launcher.write_text('#!/bin/sh\nexec "$FAKE_PYTHON" "$FAKE_SCRIPT" "$@"\n')
        launcher.chmod(0o755)
    return folder, script


@pytest.fixture()
def wrapper(tmp_path, docker_stub):
    repo = tmp_path / 'repo'
    (repo / 'scripts/db').mkdir(parents=True)
    for name in ['restore.bat', 'verify-backup.bat', 'backup.bat', 'scripts/restore.sh',
                 'scripts/backup.sh', 'scripts/verify-backup.sh', 'scripts/db/restore.sh',
                 'scripts/db/verify-restore.sh']:
        shutil.copy2(ROOT / name, repo / name)
    backup = repo / 'chosen backup.dump'
    backup.write_bytes(b'NEW-CHOSEN-SYNTHETIC-BACKUP')
    events = tmp_path / 'events.jsonl'
    folder, script = docker_stub

    def run(kind, stage='', verify=False):
        env = dict(os.environ, FAKE_PYTHON=sys.executable, FAKE_SCRIPT=str(script),
                   FAKE_EVENTS=str(events), FAKE_STAGE=stage, MSYS_NO_PATHCONV='1')
        env['PATH'] = str(folder) + os.pathsep + env['PATH']
        if kind == 'windows':
            if os.name != 'nt': pytest.skip('Native batch execution requires Windows')
            command = ['cmd.exe', '/d', '/c', 'verify-backup.bat' if verify else 'restore.bat', backup.name, '--no-pause']
        else:
            if not _bash(): pytest.skip('Bash is not installed')
            command = [_bash(), str(repo / ('scripts/verify-backup.sh' if verify else 'scripts/restore.sh')), backup.name]
        # Windows text-mode stdin rewrites LF to CRLF; Bash would read a
        # literal carriage return as part of the confirmation word.
        result = subprocess.run(command, cwd=repo, env=env, input=b'RESTORE\n',
                                capture_output=True, timeout=90)
        result.stdout = result.stdout.decode('utf-8', errors='replace')
        result.stderr = result.stderr.decode('utf-8', errors='replace')
        calls = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
        return result, calls
    return run


@pytest.mark.parametrize('kind', ['windows', 'bash'])
@pytest.mark.parametrize('stage', ['backup_failed', 'stop_failed', 'still_running', 'inspect_failed', 'copy_failed', 'preflight_failed'])
def test_preconditions_fail_before_destructive_restore(wrapper, kind, stage):
    result, calls = wrapper(kind, stage)
    assert result.returncode != 0, result.stdout + result.stderr
    assert calls, 'The wrapper must reach the injected failure, not cancel before it.'
    assert ['INNER_RESTORE'] not in calls


@pytest.mark.parametrize('kind', ['windows', 'bash'])
def test_an_incomplete_restore_never_restarts_the_api(wrapper, kind):
    result, calls = wrapper(kind, 'inner_failed')
    assert result.returncode != 0, result.stdout + result.stderr
    assert ['INNER_RESTORE'] in calls
    assert not any(call[:2] == ['compose', 'up'] for call in calls)
    assert 'RESTORE INCOMPLETE' in result.stdout


@pytest.mark.parametrize('kind', ['windows', 'bash'])
def test_safe_refusal_restarts_unchanged_database(wrapper, kind):
    result, calls = wrapper(kind, 'inner_refused')
    assert result.returncode != 0
    assert ['INNER_RESTORE'] in calls
    assert any(call[:2] == ['compose', 'up'] for call in calls)


@pytest.mark.parametrize('kind', ['windows', 'bash'])
def test_success_uses_a_unique_temporary_dump_and_restarts(wrapper, kind):
    result, calls = wrapper(kind)
    assert result.returncode == 0, result.stdout + result.stderr
    copies = [call for call in calls if call[:2] == ['compose', 'cp'] and 'backup-check' not in call[-1]]
    assert len(copies) == 1
    assert copies[0][-2] == 'chosen backup.dump'
    assert copies[0][-1].startswith('db:/tmp/foriflow-restore-')
    assert ['INNER_RESTORE'] in calls
    assert calls[-1][:2] in (['compose', 'up'], ['compose', 'exec'])


@pytest.mark.parametrize('kind', ['windows', 'bash'])
@pytest.mark.parametrize('stage', ['copy_failed', 'preflight_failed'])
def test_verification_never_uses_a_missing_or_stale_copy(wrapper, kind, stage):
    result, calls = wrapper(kind, stage, verify=True)
    assert result.returncode != 0, result.stdout + result.stderr
    assert ['INNER_VERIFY'] not in calls


@pytest.mark.parametrize('kind', ['windows', 'bash'])
def test_failed_restart_cannot_be_reported_as_a_success(wrapper, kind):
    result, calls = wrapper(kind, 'restart_failed')
    assert result.returncode != 0, result.stdout + result.stderr
    assert ['INNER_RESTORE'] in calls


@pytest.fixture()
def pg_backup(tmp_path):
    url_text = os.environ.get('FORIFLOW_TEST_POSTGRES_URL', '')
    tools = ['psql', 'pg_dump', 'pg_restore', 'createdb', 'dropdb']
    if not url_text or not _bash() or not all(shutil.which(tool) for tool in tools):
        pytest.skip('Requires the disposable PostgreSQL runner and client tools')
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(url_text)
    assert 'test' in (url.database or '').lower(), 'Only a disposable test server is permitted'
    live = 'foriflow_test_restore_' + uuid.uuid4().hex[:12]
    env = dict(os.environ, PGHOST=url.host or '127.0.0.1', PGPORT=str(url.port or 5432),
               PGPASSWORD=url.password or '', PGUSER=url.username or '',
               POSTGRES_USER=url.username or '', POSTGRES_DB=live, MSYS_NO_PATHCONV='1')
    subprocess.run(['createdb', live], env=env, check=True, capture_output=True)
    engine = create_engine(url.set(database=live))
    try:
        cfg = Config(str(ROOT / 'backend/alembic.ini'))
        cfg.set_main_option('sqlalchemy.url', url.set(database=live).render_as_string(hide_password=False).replace('%', '%%'))
        cfg.attributes['configure_logger'] = False
        command.upgrade(cfg, 'head')
        with engine.begin() as db:
            db.execute(text("INSERT INTO users (username, hashed_password, role, created_at, is_active) VALUES ('synthetic', 'not-a-real-hash', 'analyst', now(), true)"))
        dump = tmp_path / 'synthetic.dump'
        subprocess.run(['pg_dump', '-Fc', '-d', live, '-f', str(dump)], env=env, check=True, capture_output=True)
        env['DUMP'] = dump.as_posix()

        def execute(script, **changes):
            result = subprocess.run([_bash(), '-c', 'sh -s'], input=(ROOT / script).read_bytes(),
                                    env={**env, **changes}, capture_output=True, timeout=90)
            result.stdout = result.stdout.decode('utf-8', errors='replace')
            result.stderr = result.stderr.decode('utf-8', errors='replace')
            return result
        yield env, engine, dump, execute, tmp_path
    finally:
        engine.dispose()
        subprocess.run(['dropdb', '--force', live], env=env, check=True, capture_output=True)


@pytest.mark.postgres
def test_real_backup_verifies_all_content_and_removes_only_its_scratch(pg_backup):
    env, engine, dump, run, _ = pg_backup
    result = run('scripts/db/verify-restore.sh')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'content applications: identical' in result.stdout
    assert 'content revoked_tokens: identical' in result.stdout
    assert 'scratch database dropped:' in result.stdout
    assert 'RESULT: PASS' in result.stdout


@pytest.mark.postgres
def test_real_verification_detects_content_changes_with_identical_counts(pg_backup):
    from sqlalchemy import text
    _, engine, _, run, _ = pg_backup
    with engine.begin() as db:
        db.execute(text("UPDATE users SET username='changed' WHERE username='synthetic'"))
    result = run('scripts/db/verify-restore.sh')
    assert result.returncode != 0
    assert 'content differs for users' in result.stdout
    assert 'scratch database dropped:' in result.stdout


@pytest.mark.postgres
def test_real_verifier_never_drops_an_existing_database(pg_backup):
    env, _, _, run, _ = pg_backup
    existing = 'foriflow_test_keep_' + uuid.uuid4().hex[:12]
    subprocess.run(['createdb', existing], env=env, check=True, capture_output=True)
    try:
        result = run('scripts/db/verify-restore.sh', SCRATCH_DB=existing)
        assert result.returncode != 0
        assert 'could not create a new scratch database' in result.stdout
        assert subprocess.run(['psql', '-d', existing, '-Atc', 'SELECT 1'], env=env, capture_output=True).returncode == 0
    finally:
        subprocess.run(['dropdb', existing], env=env, check=True, capture_output=True)


@pytest.mark.postgres
def test_real_restore_refuses_corrupt_archive_without_changing_database(pg_backup):
    from sqlalchemy import text
    _, engine, _, run, folder = pg_backup
    corrupt = folder / 'corrupt.dump'
    corrupt.write_bytes(b'PGDMP-corrupt')
    result = run('scripts/db/restore.sh', DUMP=corrupt.as_posix(), CONFIRM='RESTORE')
    assert result.returncode == 3, result.stdout + result.stderr
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM users WHERE username='synthetic'")) == 1


@pytest.mark.postgres
def test_real_restore_replaces_only_the_disposable_target(pg_backup):
    from sqlalchemy import text
    _, engine, _, run, _ = pg_backup
    with engine.begin() as db:
        db.execute(text("UPDATE users SET username='changed' WHERE username='synthetic'"))
    engine.dispose()
    result = run('scripts/db/restore.sh', CONFIRM='RESTORE')
    assert result.returncode == 0, result.stdout + result.stderr
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM users WHERE username='synthetic'")) == 1


@pytest.mark.postgres
def test_a_readable_non_application_archive_reports_incomplete_restore(pg_backup):
    env, engine, _, run, folder = pg_backup
    incomplete = folder / 'users-only.dump'
    subprocess.run(['pg_dump', '-Fc', '-d', env['POSTGRES_DB'], '-t', 'users', '-f', str(incomplete)],
                   env=env, check=True, capture_output=True)
    engine.dispose()
    result = run('scripts/db/restore.sh', DUMP=incomplete.as_posix(), CONFIRM='RESTORE')
    assert result.returncode == 4, result.stdout + result.stderr
    assert 'RESTORE: INCOMPLETE' in result.stdout
