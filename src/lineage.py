"""Validated display lineage and stable task authorization fingerprints.

Lineage never grants permissions. Every downstream operation must still check
the authenticated actor, target and approval independently.
"""
import hashlib
import json
import re

PROJECTS = {'solosuite', 'bbp', 'parker', 'schlagbaum', 'demo'}


def validate(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'ticket_id', 'project', 'target', 'environment', 'release_id'}:
        raise ValueError('Invalid task lineage fields')
    if type(value.get('ticket_id')) is not int or not 0 < value['ticket_id'] < 1_000_000_000 or value.get('project') not in PROJECTS:
        raise ValueError('Lineage requires a valid ticket_id and project')
    if 'target' in value and value['target'] not in PROJECTS:
        raise ValueError('Invalid lineage target')
    if 'environment' in value and value['environment'] not in ('dev', 'prod'):
        raise ValueError('Invalid lineage environment')
    if 'release_id' in value and (not isinstance(value['release_id'], str) or not re.fullmatch(r'[a-f0-9-]{36}|[a-f0-9]{64}', value['release_id'])):
        raise ValueError('Invalid lineage release_id')
    return dict(value)


def fingerprint(task):
    body = {key: task.get(key) for key in ('source_agent', 'target_agent', 'task_type', 'summary', 'risk_level', 'requires_approval', 'workflow_mode')}
    payload = task.get('payload') or {}
    body['payload'] = {key: payload.get(key) for key in ('description', 'context_refs', 'amendments', 'lineage', 'originating_task_id')}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str).encode()).hexdigest()
