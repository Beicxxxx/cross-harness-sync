"""Regressions for the October 2026 review; all writes use disposable repos."""
from __future__ import annotations

import argparse
import json
import subprocess

import pytest

from helpers import (SCRIPTS, TEMPLATES_DIR, git, hermetic_env, load_ai_common, load_script,
                     run_python, scaffold)


def config(repo, **updates):
    path = repo / '.ai/sync_config.json'
    cfg = json.loads(path.read_text(encoding='utf-8'))
    cfg.update(updates)
    path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')


@pytest.mark.parametrize('old,new', [
    ('| <workstream 1> | <one line> |',
     '| Database migration complete | <one line> |'),
    ('| Current stage | <one line> |',
     '| Current stage | production complete <!-- keep this --> |'),
    ('> Last updated: <YYYY-MM-DD HH:MM> (<timezone>) by <harness/model> (<what triggered the update>).',
     '> Last updated: 2026-10-13 14:00 (Sydney) by user (migration completed).'),
])
def test_force_preserves_partial_fields_and_user_comments(ai_repo, old, new):
    original = (TEMPLATES_DIR / 'CURRENT.md').read_text(encoding='utf-8')
    assert old in original
    live = original.replace(old, new)
    path = ai_repo / '.ai/state/CURRENT.md'
    path.write_text(live, encoding='utf-8')
    before = path.read_bytes()
    result = scaffold(ai_repo, '--force')
    assert result.rc == 0, result.stdout + result.stderr
    assert path.read_bytes() == before, result.stdout
    assert any('KEEP (edited)' in line and 'CURRENT.md' in line
               for line in result.lines), result.stdout


@pytest.mark.parametrize('exists', [True, False])
def test_negated_secret_ignore_is_a_failure(ai_repo, exists):
    with (ai_repo / '.gitignore').open('a', encoding='utf-8') as stream:
        stream.write('\n.env\n!.env\n')
    if exists:
        (ai_repo / '.env').write_text('FAKE_TEST_VALUE=fixture\n', encoding='utf-8')
    res = run_python(ai_repo / '.ai/scripts/sync_verify.py', cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert '[FAIL] secret ignored: .env' in res.stdout, res.stdout
    if exists:
        dry_run = subprocess.run(['git', 'add', '--dry-run', '--', '.env'],
                                 cwd=ai_repo, env=hermetic_env(ai_repo),
                                 capture_output=True)
        assert dry_run.returncode == 0 and b'.env' in dry_run.stdout


@pytest.mark.parametrize('legacy', [False, True])
def test_failed_migration_commit_can_be_retried(ai_repo, monkeypatch, capsys, legacy):
    if legacy:
        (ai_repo / '.ai/protocol/VERSION').write_text('2.0.0\n', encoding='utf-8')
        (ai_repo / '.ai/scripts/ai_common.py').unlink()
        for name in ('checkpoint.py', 'sync_verify.py'):
            blob = subprocess.run(
                ['git', 'show', 'e692e73:scripts/' + name], cwd=SCRIPTS.parent,
                env=hermetic_env(ai_repo), capture_output=True, check=True).stdout
            (ai_repo / '.ai/scripts' / name).write_bytes(blob)
    ignore = ai_repo / '.gitignore'
    old_ignore = ignore.read_text('utf-8')
    assert '.env\n' in old_ignore
    ignore.write_text(old_ignore.replace('.env\n', ''), encoding='utf-8')
    git(ai_repo, 'add', '-A')
    git(ai_repo, 'commit', '-q', '-m', 'installed')
    before = git(ai_repo, 'rev-parse', 'HEAD')
    mod = load_script('init_sync.py', '_review_commit_recovery')
    common = load_ai_common('_review_commit_common')
    real_git = mod.run_git
    attempts = []

    def fail_first_commit(root, argv, **kwargs):
        if argv[0] == 'commit':
            attempts.append(argv)
            if len(attempts) == 1:
                return common.GitResult(128, b'', b'simulated commit failure', False)
        return real_git(root, argv, **kwargs)

    monkeypatch.setattr(mod, 'run_git', fail_first_commit)
    args = argparse.Namespace(authorizations_dir=None)
    first_rc = mod.run_migration(ai_repo, args)
    first_record = json.loads((ai_repo / mod.MIGRATION_REL).read_text('utf-8'))
    assert git(ai_repo, 'rev-parse', 'HEAD') == before
    second_rc = mod.run_migration(ai_repo, args)
    output = capsys.readouterr().out
    assert first_rc == mod.MIGRATE_INCOMPLETE, output
    assert first_record['incomplete'] is True and first_record['to'] is None
    assert second_rc == 0, output
    assert len(attempts) == 2, output
    recovered = json.loads((ai_repo / mod.MIGRATION_REL).read_text('utf-8'))
    assert recovered['from'] == ('2.0.0' if legacy else mod.PROTOCOL_VERSION)
    assert recovered['started'] == first_record['started']
    assert set(first_record['files_touched']) <= set(recovered['files_touched'])
    journal = (ai_repo / mod.MIGRATION_JOURNAL_REL).read_text('utf-8')
    assert '.gitignore` was APPENDED' in journal, journal
    assert git(ai_repo, 'rev-parse', 'HEAD') != before
    assert git(ai_repo, 'diff', '--name-only', 'HEAD', '--',
               '.ai', ':(exclude).ai/runtime/WRITER_LOCK.json') == ''
    assert mod.run_migration(ai_repo, args) == 0
    assert len(attempts) == 2, 'successful recovery must become a verifying no-op'


@pytest.mark.parametrize('source,absolute', [('config', False), ('config', True),
                                          ('cli', True)])
def test_migration_rejects_escaping_effective_authorizations_dir(
        ai_repo, source, absolute):
    outside = ai_repo.parent / 'outside'
    value = str(outside) if absolute else '../outside'
    if source == 'config':
        config(ai_repo, authorizations_dir=value)
    git(ai_repo, 'add', '-A')
    git(ai_repo, 'commit', '-q', '-m', 'installed configuration')
    before = {p.relative_to(ai_repo): p.read_bytes()
              for p in (ai_repo / '.ai').rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    flags = ['--authorizations-dir', value] if source == 'cli' else []
    result = run_python(SCRIPTS / 'init_sync.py',
                        [str(ai_repo), '--migrate', *flags], cwd=ai_repo)
    assert result.rc != 0, result.stdout
    assert 'repo-relative' in result.stdout, result.stdout + result.stderr
    assert not outside.exists(), 'refusal must precede any out-of-repo writes'
    after = {p.relative_to(ai_repo): p.read_bytes()
             for p in (ai_repo / '.ai').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    assert after == before, 'invalid config must be refused before lock or state writes'


@pytest.mark.parametrize('rel', ['README.md', 'docs/required.md'])
def test_validate_resolves_required_files_from_repository_root(ai_repo, rel):
    required = ai_repo / rel
    required.parent.mkdir(parents=True, exist_ok=True)
    required.write_text('required fixture\n', encoding='utf-8')
    cfg = json.loads((ai_repo / '.ai/sync_config.json').read_text('utf-8'))
    config(ai_repo, required_files=cfg['required_files'] + [rel])
    validate = run_python(ai_repo / '.ai/scripts/checkpoint.py', ['--validate'],
                          cwd=ai_repo)
    verify = run_python(ai_repo / '.ai/scripts/sync_verify.py', cwd=ai_repo)
    assert verify.rc == 0 and f'[PASS] required {rel}' in verify.stdout
    assert validate.rc == 0, validate.stdout + validate.stderr
    assert f'OK:      {rel}' in validate.stdout, validate.stdout
    required.unlink()
    # An .ai/ decoy cannot satisfy a missing root-relative requirement.
    decoy = ai_repo / '.ai' / rel
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text('wrong location\n', encoding='utf-8')
    missing = run_python(ai_repo / '.ai/scripts/checkpoint.py', ['--validate'],
                         cwd=ai_repo)
    assert missing.rc == 1 and f'MISSING: {rel}' in missing.stdout, missing.stdout


@pytest.mark.parametrize('absolute', [False, True])
def test_validate_rejects_required_file_outside_repository(ai_repo, absolute):
    outside = ai_repo.parent / 'outside.md'
    outside.write_text('outside fixture\n', encoding='utf-8')
    rel = str(outside) if absolute else '../outside.md'
    config(ai_repo, required_files=[rel])
    verify = run_python(ai_repo / '.ai/scripts/sync_verify.py', cwd=ai_repo)
    validate = run_python(ai_repo / '.ai/scripts/checkpoint.py', ['--validate'],
                          cwd=ai_repo)
    assert verify.rc == 2, verify.stdout
    assert validate.rc == 2, validate.stdout + validate.stderr
    assert 'repo-relative' in validate.stdout, validate.stdout
