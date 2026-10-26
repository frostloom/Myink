"""Bounded static navigation over declared frozen files; never execute source."""
import ast
import hashlib
import json
from pathlib import Path
import stat

from .plans import _path

MAX_FILE_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 8192
MAX_SYMBOLS = 128


class _Functions(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.symbols = []

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.symbols.append(dict(name='.'.join([*self.scope, node.name]),
            start_line=min([node.lineno, *(d.lineno for d in node.decorator_list)]),
            end_line=node.end_lineno))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef


def _file(root, name):
    p = root / name
    if (any(q.is_symlink() for q in (p, *p.parents)) or not p.is_file()
            or not stat.S_ISREG(p.stat().st_mode) or p.stat().st_nlink != 1):
        raise ValueError('regular non-linked source file required')
    with p.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
        sha = hashlib.sha256(raw)
        line_count = raw.count(b'\n')
        last = raw[-1:] if raw else b''
        if len(raw) > MAX_FILE_BYTES:
            while chunk := stream.read(128 * 1024):
                sha.update(chunk)
                line_count += chunk.count(b'\n')
                last = chunk[-1:]
            row = dict(path=name, source_sha256=sha.hexdigest(),
                       line_count=line_count + int(bool(last) and last != b'\n'),
                       symbols=[], omitted_symbols=None, status='too_large')
            return row, []
    row = dict(path=name, source_sha256=sha.hexdigest(), line_count=len(raw.splitlines()),
               symbols=[], omitted_symbols=None, status='not_python')
    if p.suffix != '.py':
        return row, []
    try:
        visitor = _Functions()
        visitor.visit(ast.parse(raw, filename=name))
    except (SyntaxError, RecursionError) as error:
        row.update(status='syntax_error', error_line=getattr(error, 'lineno', None))
        return row, []
    row.update(status='python', omitted_symbols=len(visitor.symbols))
    return row, visitor.symbols


def source_index(root, files, focus=''):
    """Initial-snapshot hints only; omitted/unparseable symbols are explicit."""
    root = Path(root)
    if (not root.is_absolute() or '..' in root.parts or not root.is_dir()
            or any(p.is_symlink() for p in (root, *root.parents))
            or not isinstance(files, (list, tuple)) or not 0 < len(files) <= 8
            or not all(_path(f) for f in files) or len(files) != len(set(files))
            or not isinstance(focus, str)):
        raise ValueError('declared frozen source files required')
    result = dict(version=1, files=[])
    choices = []
    for pos, name in enumerate(files):
        row, symbols = _file(root, name)
        result['files'].append(row)
        for symbol in symbols:
            mentioned = symbol['name'].split('.')[-1] in focus
            choices.append((not mentioned, pos, symbol))
    def size():
        return len(json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode())
    if size() > MAX_INDEX_BYTES:
        raise ValueError('source index metadata too large')
    choices.sort(key=lambda v: (v[0], v[1], v[2]['start_line'], v[2]['name']))
    for _, pos, symbol in choices[:MAX_SYMBOLS]:
        row = result['files'][pos]
        row['symbols'].append(symbol)
        row['omitted_symbols'] -= 1
        if size() > MAX_INDEX_BYTES:
            row['symbols'].pop()
            row['omitted_symbols'] += 1
            break
    return result
