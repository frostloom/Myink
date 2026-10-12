"""Host-owned typed tools. Tokens select authority; model text cannot create it.

The private candidate must be writable only by this broker. A pending durable
intent is never executed on restart: an operator must reconcile any crash.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from difflib import SequenceMatcher
from hashlib import sha256
from hmac import compare_digest
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from threading import RLock

from .contracts import Receipt, Record
from .ledger import OperationConflict
from .plans import Plan, _path, _protected, check_diff, validate_plan

TOOL_NAMES = ('observe_metrics', 'read_source', 'propose_plan', 'apply_patch', 'run_check', 'candidate_status')
PHASE_TOOLS = {
    'analysis': ('observe_metrics', 'read_source', 'candidate_status'),
    'plan': ('observe_metrics', 'read_source', 'propose_plan', 'candidate_status'),
    'develop': ('read_source', 'apply_patch', 'run_check', 'candidate_status'),
    'diagnose': ('observe_metrics', 'read_source', 'candidate_status'),
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=True)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class ToolCapability:
    session_id: str
    candidate_id: str
    root: Path
    base: str
    owner: str
    generation: int
    phase: str
    tracked_paths: tuple[str, ...]
    plan: Plan | None = None


class ToolDenied(ValueError):
    pass


class ControlledTools:
    def __init__(self, ledger, policy, *, capability, scope_token, identity, baseline,
                 metrics, checks=None, secret_values=()):
        if (not isinstance(capability, ToolCapability) or capability.phase not in PHASE_TOOLS
                or type(capability.generation) is not int or capability.generation < 1
                or not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,128}', v)
                           for v in (capability.session_id, capability.candidate_id, capability.owner, capability.base))
                or not isinstance(capability.tracked_paths, tuple)
                or not 1 <= len(capability.tracked_paths) <= 128
                or not all(_path(v) for v in capability.tracked_paths)
                or len(set(v.casefold() for v in capability.tracked_paths)) != len(capability.tracked_paths)
                or not isinstance(scope_token, str) or not re.fullmatch(r'[!-~]{1,4096}', scope_token)):
            raise ValueError('host-owned frozen tool capability required')
        self.ledger, self.policy = ledger, deepcopy(policy)
        self.capability, self.token, self.identity = capability, scope_token, identity
        self.baseline, self.metrics = deepcopy(baseline), deepcopy(metrics)
        self.checks, self.secret_values = dict(checks or {}), tuple(secret_values)
        if set(self.checks) - {'unit', 'lint', 'contract'}:
            raise ValueError('only fixed check ids permitted')
        self._lock = RLock()
        self._safe_root()
        # Snapshot only eligible tracked source. No model-selected root or Git command.
        source_binding = digest(dict(candidate_id=capability.candidate_id, base=capability.base,
                                     owner=capability.owner, generation=capability.generation,
                                     root=str(capability.root), paths=capability.tracked_paths))
        source_id = 'tool-source-base:' + source_binding
        with self._exclusive():
            frozen = self.ledger.get(source_id)
            if frozen is None:
                sources = {p:self._read(p).decode('utf-8') for p in capability.tracked_paths if self._eligible(p)}
                if len(canonical(sources).encode()) > 2 * 1024**2:
                    raise ToolDenied('frozen source manifest too large')
                self.ledger.intent(source_id, 'tool_source_base', {'binding':source_binding})
                self.ledger.finish(Receipt(source_id, 'done', {'sources':sources}))
                frozen = self.ledger.get(source_id)
            if frozen['kind'] != 'tool_source_base' or frozen['status'] != 'done':
                raise ToolDenied('frozen base requires host reconciliation')
            self._base_sources = {p:raw.encode('utf-8') for p,raw in frozen['evidence']['sources'].items()}
        self._binding = digest(dict(session=capability.session_id, candidate_id=capability.candidate_id,
                                    base=capability.base, owner=capability.owner,
                                    generation=capability.generation, phase=capability.phase,
                                    root=str(capability.root), plan_hash=capability.plan.plan_hash if capability.plan else None))

    def _safe_root(self):
        root = self.capability.root
        if not isinstance(root, Path) or not root.is_absolute() or '..' in root.parts:
            raise ToolDenied('private absolute candidate required')
        for part in (root, *root.parents):
            if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
                raise ToolDenied('linked candidate denied')
        if not root.is_dir():
            raise ToolDenied('candidate unavailable')

    def _eligible(self, path):
        if not _path(path) or path not in self.capability.tracked_paths or _protected((path,), self.policy):
            return False
        parts = path.split('/')
        denied = {'backup', 'backups', 'runtime', 'history', 'credentials', 'secrets', 'node_modules', '__pycache__'}
        if any(p.startswith('.') or p.casefold() in denied for p in parts):
            return False
        return Path(path).suffix in {'.py', '.ts', '.tsx', '.js', '.mjs', '.go', '.css', '.html', '.md'}

    def _source_path(self, path):
        if not self._eligible(path):
            raise ToolDenied('source path outside exact tracked allowlist')
        self._safe_root()
        target = self.capability.root
        for component in path.split('/'):
            # Checking exact directory entries defeats case-insensitive filesystem aliases.
            if component not in os.listdir(target):
                raise ToolDenied('source path spelling mismatch')
            target = target / component
            if target.is_symlink() or getattr(target, 'is_junction', lambda: False)():
                raise ToolDenied('linked source denied')
        info = target.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
            raise ToolDenied('bounded single-link regular source required')
        return target

    def _read(self, path):
        target = self._source_path(path)
        before = target.stat()
        with target.open('rb') as source:
            raw = source.read(65537)
        after = target.stat()
        if (len(raw) > 65536 or (before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise ToolDenied('source changed during read')
        try:
            text = raw.decode('utf-8')
        except UnicodeError as exc:
            raise ToolDenied('UTF-8 source required') from exc
        if '\x00' in text or any(secret and secret in text for secret in self.secret_values):
            raise ToolDenied('secret or binary source denied')
        return raw

    def candidate_hash(self):
        return digest({path: sha256(self._read(path)).hexdigest() for path in self._base_sources})

    def _current(self, capability):
        expected = dict(owner=self.capability.owner, generation=self.capability.generation,
                        candidate_id=self.capability.candidate_id, base=self.capability.base)
        return capability is self.capability and self.identity() == expected

    @contextmanager
    def _exclusive(self):
        # OS lock spans intent, side effects, and receipt across broker instances.
        path = self.ledger.path.with_suffix('.tools.lock')
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ToolDenied('linked broker lock denied')
        with self._lock, path.open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @property
    def allowed_tools(self):
        return PHASE_TOOLS[self.capability.phase]

    def dispatch(self, token, body):
        if (not isinstance(token, str) or not compare_digest(token.encode(), self.token.encode())
                or not isinstance(body, dict) or set(body) != {'tool', 'call_id', 'arguments'}):
            return Receipt('tool:denied', 'blocked', {'reason': 'invalid scoped tool envelope'})
        return self.handle_tool(body['tool'], {'call_id': body['call_id'], 'input': body['arguments']}, self.capability)

    def handle_tool(self, name: str, arguments: Record, capability: ToolCapability) -> Receipt:
        operation = 'tool:denied'
        try:
            with self._exclusive():
                if not self._current(capability):
                    raise ToolDenied('foreign or stale capability')
                if (name not in PHASE_TOOLS[self.capability.phase] or not isinstance(arguments, dict)
                        or set(arguments) != {'call_id', 'input'}
                        or not isinstance(arguments['call_id'], str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', arguments['call_id'])
                        or not isinstance(arguments['input'], dict)):
                    raise ToolDenied('unknown tool, nested call, or invalid envelope')
                args = deepcopy(arguments['input'])
                encoded = canonical(args)
                if len(encoded.encode()) > 32768:
                    raise ToolDenied('tool input exceeds byte cap')
                operation = 'tool:' + self.capability.session_id + ':' + arguments['call_id']
                payload = dict(tool=name, input_hash=sha256(encoded.encode()).hexdigest(), binding=self._binding)
                prior = self.ledger.get(operation)
                if prior:
                    if prior['kind'] != 'controlled_tool' or prior['payload'] != payload:
                        raise ToolDenied('tool call identity collision')
                    if prior['status'] == 'pending':
                        return Receipt(operation, 'uncertain', {'reason': 'pending intent requires host reconciliation'})
                    return Receipt(operation, prior['status'], prior['evidence'])
                self.ledger.intent(operation, 'controlled_tool', payload)
                try:
                    validate_schema(args,tool_definitions((name,))[0]['input_schema'])
                    evidence = self._execute(name, args)
                    receipt = Receipt(operation, 'done', dict(tool=name, input_hash=payload['input_hash'],
                        binding=self._binding, **evidence))
                except RuntimeError:
                    receipt = Receipt(operation, 'uncertain', dict(tool=name, input_hash=payload['input_hash'],
                        binding=self._binding, reason='side effect requires host reconciliation'))
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    reason = str(exc) if isinstance(exc, ToolDenied) else 'tool input or resource unavailable'
                    receipt = Receipt(operation, 'blocked', dict(tool=name, input_hash=payload['input_hash'],
                        binding=self._binding, reason=reason))
                receipt = Receipt(receipt.operation_id,receipt.status,json.loads(canonical(receipt.evidence)))
                self.ledger.finish(receipt)
                return receipt
        except (ValueError, TypeError, OSError, OperationConflict):
            return Receipt(operation, 'blocked', {'reason': 'foreign/stale authority, collision, or broker unavailable'})

    def lookup(self, call_id, name, args, result):
        """Engine receipt verifier: result must match immutable authoritative lookup."""
        row = self.ledger.get('tool:' + self.capability.session_id + ':' + call_id)
        if not row or row['kind'] != 'controlled_tool' or row['status'] == 'pending':
            return False
        expected = Receipt(row['operation_id'], row['status'], row['evidence'])
        return (self._current(self.capability) and row['payload'] == dict(tool=name, input_hash=digest(args), binding=self._binding)
                and isinstance(result, dict) and result == asdict(expected))

    def approve_plan(self, plan_hash, review_id):
        """Trusted controller only; no approval tool or HTTP route exists."""
        plan = self.capability.plan
        rules = validate_plan(plan, self.baseline, self.policy) if plan else None
        review = self.ledger.get(review_id)
        expected = dict(source='independent_review', verified=True, result='approved', plan_hash=plan_hash,
                        base=self.capability.base, candidate_id=self.capability.candidate_id,
                        owner=self.capability.owner, generation=self.capability.generation)
        if (not plan or plan.plan_hash != plan_hash or rules.status != 'done'
                or not review or review['kind'] != 'independent_review' or review['status'] != 'done'
                or any(review['evidence'].get(k) != v for k, v in expected.items())
                or not isinstance(review['evidence'].get('reviewer'), str)
                or review['evidence']['reviewer'] in ('', self.capability.owner, 'model')):
            raise ToolDenied('deterministic rules and independent host review required')
        operation = 'tool-approval:' + self._binding + ':' + plan_hash
        self.ledger.intent(operation, 'tool_approval', {'plan_hash':plan_hash, 'binding':self._binding, 'review_id':review_id})
        self.ledger.finish(Receipt(operation, 'done', {'rules':asdict(rules), 'review_id':review_id}))

    def _approved(self, plan_hash):
        plan = self.capability.plan
        approval = self.ledger.get('tool-approval:' + self._binding + ':' + plan_hash) if isinstance(plan_hash,str) else None
        if (not plan or plan_hash != plan.plan_hash or not approval or approval['kind'] != 'tool_approval'
                or approval['status'] != 'done' or approval['payload'].get('binding') != self._binding):
            raise ToolDenied('approved frozen plan and separate review required')
        return plan

    @staticmethod
    def _fields(args, expected):
        if set(args) != set(expected):
            raise ToolDenied('unsupported tool fields')

    def _receipts(self):
        with self.ledger.transaction() as connection:
            rows = [self.ledger._record(row) for row in connection.execute(
                "SELECT * FROM operations WHERE kind='controlled_tool' ORDER BY rowid")]
        return [dict(operation_id=r['operation_id'], tool=r['payload']['tool'], status=r['status'])
                for r in rows if r['payload'].get('binding') == self._binding]

    def _execute(self, name, args):
        if name == 'observe_metrics':
            self._fields(args, ())
            snapshot = deepcopy(self.metrics)
            if isinstance(snapshot.get('writing_view'),dict):
                from .writing_analysis import indexed_evidence_view
                snapshot['writing_view'] = indexed_evidence_view(snapshot['writing_view'])
            return dict(snapshot=snapshot, availability='partial', semantic_quality='unknown',
                        untrusted_body_text=True)
        if name == 'candidate_status':
            self._fields(args, ())
            return dict(candidate_id=self.capability.candidate_id, base=self.capability.base,
                        generation=self.capability.generation, candidate_hash=self.candidate_hash(),
                        receipts=self._receipts(), published=False)
        if name == 'read_source':
            self._fields(args, ('path', 'start_line', 'end_line'))
            if (type(args['start_line']) is not int or type(args['end_line']) is not int
                    or not 1 <= args['start_line'] <= args['end_line'] <= args['start_line'] + 199):
                raise ToolDenied('bounded positive source positions required')
            raw = self._read(args['path']); lines = raw.decode().splitlines(keepends=True)
            if args['end_line'] > len(lines):
                raise ToolDenied('source position outside file')
            text = ''.join(lines[args['start_line'] - 1:args['end_line']])
            if len(text.encode()) > 16384:
                raise ToolDenied('source excerpt too large')
            return dict(path=args['path'], source_hash=sha256(raw).hexdigest(), text=text,
                        start_line=args['start_line'], end_line=args['end_line'], untrusted_source=True)
        if name == 'propose_plan':
            self._fields(args, ('plan',))
            data = deepcopy(args['plan'])
            if not isinstance(data, dict) or set(data) - {f.name for f in fields(Plan)}:
                raise ToolDenied('strict Plan schema required')
            for key in ('files', 'slice_ids', 'guard_metrics', 'change_types'):
                if key in data:
                    if not isinstance(data[key], list):
                        raise ToolDenied('Plan arrays required')
                    data[key] = tuple(data[key])
            plan = Plan(**data)
            rules = validate_plan(plan, self.baseline, self.policy)
            return dict(plan=asdict(plan), plan_hash=plan.plan_hash, approved=False, rules=asdict(rules))
        if name == 'run_check':
            self._fields(args, ('check_id', 'candidate_hash', 'plan_hash'))
            self._approved(args['plan_hash'])
            if args['check_id'] not in ('unit', 'lint', 'contract'):
                raise ToolDenied('unknown fixed check id')
            if args['candidate_hash'] != self.candidate_hash():
                raise ToolDenied('stale candidate hash')
            callback = self.checks.get(args['check_id'])
            if callback is None:
                raise ToolDenied('accepted isolated nonroot check executor unavailable; host containment proof required')
            snapshot = dict(candidate_hash=args['candidate_hash'], plan_hash=args['plan_hash'], base=self.capability.base,
                            candidate_id=self.capability.candidate_id, generation=self.capability.generation,
                            check_id=args['check_id'])
            result = callback(deepcopy(snapshot))
            if (not isinstance(result, Receipt) or result.status != 'done'
                    or any(result.evidence.get(k) != v for k, v in snapshot.items())
                    or result.evidence.get('result') != 'passed'):
                raise ToolDenied('check receipt not verified for frozen candidate')
            return {'check':asdict(result)['evidence'], 'check_operation_id':result.operation_id}
        self._fields(args, ('plan_hash', 'base', 'candidate_hash', 'edits'))
        plan = self._approved(args['plan_hash'])
        if args['base'] != self.capability.base or args['candidate_hash'] != self.candidate_hash():
            raise ToolDenied('stale base or candidate hash')
        edits = args['edits']
        if not isinstance(edits, list) or not 1 <= len(edits) <= self.policy.hard_tracked_files:
            raise ToolDenied('bounded exact edits required')
        replacements = {}; originals = {}
        for edit in edits:
            if not isinstance(edit, dict):
                raise ToolDenied('strict edit object required')
            self._fields(edit, ('path', 'source_hash', 'old', 'new'))
            path = edit['path']
            if not isinstance(path, str) or path not in plan.files or path in replacements:
                raise ToolDenied('undeclared or duplicate file')
            raw = self._read(path); text = raw.decode()
            if (edit['source_hash'] != sha256(raw).hexdigest() or not isinstance(edit['old'], str)
                    or not edit['old'] or not isinstance(edit['new'], str) or text.count(edit['old']) != 1):
                raise ToolDenied('source hash or unique exact replacement mismatch')
            changed = text.replace(edit['old'], edit['new'], 1).encode('utf-8')
            if len(changed) > 65536 or b'\x00' in changed or any(s and s.encode() in changed for s in self.secret_values):
                raise ToolDenied('bounded nonsecret UTF-8 replacement required')
            originals[path], replacements[path] = raw, changed
        current = {p:replacements.get(p, self._read(p)) for p in self._base_sources}
        changed_paths = []; added = deleted = 0
        for path, raw in current.items():
            if raw == self._base_sources[path]:
                continue
            changed_paths.append(path)
            for tag, a, b, c, d in SequenceMatcher(None, self._base_sources[path].splitlines(), raw.splitlines()).get_opcodes():
                if tag != 'equal':
                    deleted += b - a; added += d - c
        gate = check_diff(plan, dict(plan_hash=plan.plan_hash, files=changed_paths, production_added=added,
                                    production_deleted=deleted, tracked_files=len(changed_paths)), self.policy)
        if gate.status != 'done':
            raise ToolDenied('cumulative scope gate: ' + gate.evidence['reason'])
        temps = []; cleanup_failed = False
        try:
            for path, raw in replacements.items():
                target = self._source_path(path)
                fd, temp = tempfile.mkstemp(prefix='.controlled-', dir=target.parent)
                temps.append((Path(temp), target))
                with os.fdopen(fd, 'wb') as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
                os.chmod(temp, stat.S_IMODE(target.stat().st_mode))
            # Revalidate all edits before the first rename; denial has no side effect.
            if any(self._read(p) != raw for p, raw in originals.items()) or not self._current(self.capability):
                raise ToolDenied('source or authority changed before patch')
            for temp, target in temps:
                os.replace(temp, target)
                if os.name != 'nt':
                    fd = os.open(target.parent, os.O_RDONLY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
        except OSError:
            # Some files may have been renamed. Never report a clean denial or retry.
            raise RuntimeError('patch write uncertain; host reconciliation required') from None
        finally:
            # Cleanup must never replace a primary write-uncertainty exception.
            for temp, _ in temps:
                try:
                    if temp.exists(): temp.unlink()
                except OSError:
                    cleanup_failed = True
        if cleanup_failed:
            # The renames succeeded, but cleanup cannot prove a clean completion.
            raise RuntimeError('patch cleanup uncertain; host reconciliation required')
        return dict(candidate_hash=self.candidate_hash(), files=changed_paths, scope=asdict(gate))


def tool_definitions(phase_or_names):
    """Trusted complete schemas; caller input never selects new tool definitions."""
    names = PHASE_TOOLS.get(phase_or_names) if isinstance(phase_or_names, str) else phase_or_names
    if not isinstance(names, tuple) or not names or len(set(names)) != len(names) or any(n not in TOOL_NAMES for n in names):
        raise ValueError('fixed tool allowlist required')
    definitions = json.loads((Path(__file__).parent / 'extensions/tool-schemas.json').read_text(encoding='utf-8'))
    by_name = {d['name']:d for d in definitions}
    return [deepcopy(by_name[n]) for n in names]


def validate_schema(value, schema):
    """Small strict validator for this fixed schema vocabulary, never arbitrary schemas."""
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try:
                validate_schema(value, option)
                return
            except ValueError:
                pass
        raise ToolDenied('value outside fixed schema')
    kind = schema['type']
    valid = {'object': isinstance(value,dict), 'array': isinstance(value,list),
             'string': isinstance(value,str), 'integer':type(value) is int,
             'number':type(value) in (int,float), 'null':value is None}.get(kind,False)
    if not valid or ('enum' in schema and value not in schema['enum']):
        raise ToolDenied('tool argument type mismatch')
    if kind == 'object':
        properties=schema['properties']
        if set(value)-set(properties) or not set(schema['required']).issubset(value):
            raise ToolDenied('unsupported or missing tool fields')
        for key,item in value.items():validate_schema(item,properties[key])
    elif kind == 'array':
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',128):
            raise ToolDenied('tool array outside bound')
        if schema.get('uniqueItems') and len(set(canonical(v) for v in value)) != len(value):
            raise ToolDenied('duplicate tool array values')
        for item in value:validate_schema(item,schema['items'])
    elif kind == 'string':
        if (not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',65536)
                or ('pattern' in schema and re.fullmatch(schema['pattern'],value) is None)):
            raise ToolDenied('tool string outside bound')
    elif kind in ('integer','number'):
        import math
        if (not math.isfinite(value) or value < schema.get('minimum',-float('inf'))
                or value > schema.get('maximum',float('inf'))
                or value <= schema.get('exclusiveMinimum',-float('inf'))):
            raise ToolDenied('tool number outside bound')
