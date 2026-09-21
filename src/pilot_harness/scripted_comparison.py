"""Matched offline recovery fixtures; not model experiments or independent samples."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .acceptance import REQUIRED_ARTIFACTS, inspect_episode
from .audit import canonical_json
from .dispatch_adapter import ARTIFACTS as DISPATCH_ARTIFACTS, DispatchTaskSpec
from .faults import TIMEOUT_MESSAGE
from .manifests import sha256_file, verify_manifest, write_manifest
from .models import Action
from .provider import Provider
from .reservation_adapter import ARTIFACTS as RESERVATION_ARTIFACTS, ReservationTaskSpec
from .runtime_schema import SchemaRegistry
from .unified_engine import UnifiedEpisodeEngine


POLICIES = ('retry_once', 'query_then_retry')


class RecoveryPolicy(Provider):
    """A bounded policy that receives only the public contract and observations."""

    def __init__(self, policy):
        if policy not in POLICIES:
            raise ValueError('unsupported recovery policy')
        self.policy = policy

    @property
    def name(self):
        return 'scripted-' + self.policy + '-v1'

    def next_action(self, task, history):
        family = task.family
        if family not in ('dispatch', 'reservation'):
            raise ValueError('unsupported task family')
        public = json.loads(task.instruction.rsplit('Public ' + family + ' contract: ', 1)[1])
        mutation = 'dispatch' if family == 'dispatch' else 'reserve'
        query = 'lookup' if family == 'dispatch' else 'inspect'
        args = {'operation_id': public['operation_id']}
        args['payload' if family == 'dispatch' else 'units'] = public['payload' if family == 'dispatch' else 'units']
        attempts = sum(action.kind == mutation for action, _ in history)
        if not history:
            return Action(mutation, args)
        action, observed = history[-1]
        if not observed.ok:
            if action.kind != mutation or observed.error != TIMEOUT_MESSAGE or attempts != 1:
                raise RuntimeError('unsupported error or exhausted recovery')
            return (Action(mutation, args) if self.policy == 'retry_once'
                    else Action(query, {'operation_id': public['operation_id']}))
        content = observed.content
        if not isinstance(content, dict):
            raise RuntimeError('malformed tool response')
        if action.kind == query:
            if family == 'dispatch':
                if content.get('found') is False:
                    return Action(mutation, args)
                if content.get('found') is True and content.get('payload') == public['payload']:
                    return Action('finish')
            else:
                reservations = content.get('reservations')
                if reservations == []:
                    return Action(mutation, args)
                if isinstance(reservations, list) and len(reservations) == 1:
                    item = reservations[0]
                    if (isinstance(item, dict) and item.get('operation_id') == public['operation_id']
                            and type(item.get('units')) is int and item['units'] == public['units']):
                        return self._confirm(item)
        elif family == 'dispatch' and action.kind == mutation:
            if content.get('status') == 'accepted' and content.get('operation_id') == public['operation_id']:
                return Action('finish')
        elif family == 'reservation':
            if action.kind == mutation:
                return self._confirm(content)
            if (action.kind == 'confirm' and content.get('state') == 'confirmed'
                    and type(content.get('token')) is int and content['token'] == action.arguments['token']):
                return Action('finish')
        raise RuntimeError('unsupported tool response')

    @staticmethod
    def _confirm(content):
        token = content.get('token')
        if content.get('state') != 'held' or type(token) is not int or token < 1:
            raise RuntimeError('invalid held reservation')
        return Action('confirm', {'token': token})


def comparison_plan():
    """Fixed development design. Private conditions never enter the Provider."""
    cells = []
    for family in ('dispatch', 'reservation'):
        for fault in ('none', 'timeout_once', 'timeout_committed_once'):
            for visibility in (('fresh', 'lagged_once') if family == 'dispatch' else ('fresh',)):
                for idempotent in (False, True):
                    for policy in POLICIES:
                        task = (DispatchTaskSpec(visibility=visibility, idempotent=idempotent,
                                                 max_attempts=4, max_steps=6) if family == 'dispatch'
                                else ReservationTaskSpec(idempotent=idempotent, max_attempts=4, max_steps=6))
                        cells.append({'episode_id': f'cell-{len(cells):03d}', 'family': family,
                                      'task_id': task.task_id, 'task': asdict(task), 'condition': fault,
                                      'scaffold': policy, 'model': RecoveryPolicy(policy).name,
                                      'repetition': 1, 'time_block': 'offline-development'})
    return {'schema_version': 'scripted-comparison/1', 'data_origin': 'scripted_fixture',
            'independent_task_structures': 2, 'cells': cells}


def _read(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object: ' + path.name)
    return value


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _row(output, cell, schema):
    folder = output / 'episodes' / cell['episode_id']
    row = {'episode_id': cell['episode_id'], 'family': cell['family'], 'policy': cell['scaffold'],
           'outcome': None, 'local_score': None, 'counters': None, 'errors': []}
    try:
        events = [json.loads(line) for line in (folder / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError('expected JSON event objects')
        _read(folder / 'events.jsonl.head.json')
        inspected, critical, _ = inspect_episode(folder, schema, cell)
        row['errors'].extend(critical)
        starts = [event for event in events if event.get('event') == 'episode_start']
        if len(starts) != 1:
            raise ValueError('expected one start event')
        start = starts[0]
        if (canonical_json(start[cell['family'] + '_task']) != canonical_json(cell['task'])
                or start['provider'] != cell['model'] or start['fault'] != cell['condition']
                or start['contract']['family'] != cell['family'] or start['fault_actions'] is not None):
            row['errors'].append('episode differs from planned task, provider or fault')
        receipt = _read(folder / (cell['family'] + '-effects.json'))
        if not row['errors']:
            row.update(outcome=inspected['outcome'], local_score=receipt['score'], counters=receipt['counters'])
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        row['errors'].append('unreadable episode: ' + type(exc).__name__)
    return row


def _summary(output, plan):
    schema = SchemaRegistry(Path(__file__).parent / 'schemas')
    return {'schema_version': 'scripted-comparison-summary/1', 'data_origin': 'scripted_fixture',
            'independent_task_structures': 2, 'planned_cells': len(plan['cells']),
            'rows': [_row(output, cell, schema) for cell in plan['cells']]}


def run_comparison(output: Path):
    """Run each prespecified cell once; retain failed cells and refuse overwrite."""
    output.mkdir(parents=True, exist_ok=False)
    plan = comparison_plan()
    source = Path(__file__).parent
    plan['source_sha256'] = {p.relative_to(source).as_posix(): sha256_file(p)
                             for p in sorted(source.rglob('*')) if p.suffix in ('.py', '.json') and p.is_file()}
    _write(output / 'plan.json', plan)
    engine = UnifiedEpisodeEngine(output)
    failures = {}
    for cell in plan['cells']:
        task_class = DispatchTaskSpec if cell['family'] == 'dispatch' else ReservationTaskSpec
        try:
            engine.run(task_class(**cell['task']), RecoveryPolicy(cell['scaffold']),
                       fault=cell['condition'], episode_id=cell['episode_id'])
        except Exception as exc:
            # Keep the planned denominator, partial evidence and only a non-sensitive error class.
            failures[cell['episode_id']] = type(exc).__name__
    _write(output / 'execution-errors.json', failures)
    summary = _summary(output, plan)
    _write(output / 'summary.json', summary)
    write_manifest(output, metadata={'data_origin': 'scripted_fixture', 'design': plan['schema_version']})
    return summary


def verify_comparison(output: Path):
    """Read-only complete-boundary and semantic check; never filter or repair cells."""
    errors = []
    summary = None
    try:
        plan = _read(output / 'plan.json')
        fixed = comparison_plan()
        sources = plan.get('source_sha256')
        if (not isinstance(sources, dict) or not sources or
                any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in sources.values())):
            errors.append('missing or invalid source provenance')
        if canonical_json({k: v for k, v in plan.items() if k != 'source_sha256'}) != canonical_json(fixed):
            errors.append('unsupported or changed comparison plan')
        # Caller-owned boundary: never let an edited plan or manifest shrink the denominator.
        required = ['plan.json', 'summary.json', 'execution-errors.json']
        for cell in fixed['cells']:
            artifacts = DISPATCH_ARTIFACTS if cell['family'] == 'dispatch' else RESERVATION_ARTIFACTS
            required.extend('episodes/' + cell['episode_id'] + '/' + name for name in (*REQUIRED_ARTIFACTS, *artifacts))
        ids = {cell['episode_id'] for cell in fixed['cells']}
        if {p.name for p in (output / 'episodes').iterdir() if p.is_dir()} != ids:
            errors.append('missing or unexpected episode directories')
        manifest_path = output / 'manifest.json'
        anchor = sha256_file(manifest_path)
        valid, details = verify_manifest(manifest_path, required_artifacts=required)
        if not valid:
            errors.extend(details)
        failures = _read(output / 'execution-errors.json')
        if failures != {}:
            errors.append('execution errors retained; comparison is incomplete')
        if not errors:
            rebuilt = _summary(output, fixed)
            errors.extend(row['episode_id'] + ': ' + error for row in rebuilt['rows'] for error in row['errors'])
            if canonical_json(rebuilt) != canonical_json(_read(output / 'summary.json')):
                errors.append('saved summary differs from sealed episode evidence')
            valid, details = verify_manifest(manifest_path, required_artifacts=required)
            if not valid:
                errors.extend(details)
            if sha256_file(manifest_path) != anchor:
                errors.append('manifest changed during verification')
            if not errors:
                summary = rebuilt
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append('unreadable comparison: ' + type(exc).__name__)
    return {'valid': not errors, 'errors': errors, 'summary': summary}
