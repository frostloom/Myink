"""Trusted gold only, executed with root-authored fake parser; never a candidate import."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

GOLD=Path(__file__).parent/'fixtures/repository_pilots/short_parse_unicode/fixed.py'

def load_gold(monkeypatch,parser,*,mutate_import=False):
    def load(module):
        if mutate_import:sys.set_int_max_str_digits(0)
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=load))
    def source_spec(name,path):
        assert path=='/source/src/myink/workflow/short_parse.py'
        return spec
    monkeypatch.setattr(importlib.util,'spec_from_file_location',source_spec)
    monkeypatch.setattr(importlib.util,'module_from_spec',lambda spec:parser)
    namespace={}
    exec(compile(GOLD.read_text(),str(GOLD),'exec'),namespace)
    return namespace

@pytest.mark.parametrize('name', ['parse_short_draft','render_short_draft','find_empty_chapters'])
@pytest.mark.parametrize('direction',['disable','lower'])
def test_every_gold_exported_call_rejects_persistent_global_limit_change(monkeypatch,name,direction):
    initial=sys.get_int_max_str_digits()
    def mutate(*args,**kw):
        sys.set_int_max_str_digits(0 if direction=='disable' else 640)
        return []
    parser=SimpleNamespace(**{key:mutate for key in ('parse_short_draft','render_short_draft','find_empty_chapters')})
    try:
        ns=load_gold(monkeypatch,parser)
        with pytest.raises(AssertionError,match='integer limit'):
            ns[name]('synthetic',2)
    finally:sys.set_int_max_str_digits(initial)

def test_gold_import_limit_is_immutable_and_checked(monkeypatch):
    initial=sys.get_int_max_str_digits()
    parser=SimpleNamespace(parse_short_draft=lambda *a:[],render_short_draft=lambda *a:'',find_empty_chapters=lambda *a:[])
    try:
        with pytest.raises(AssertionError,match='integer limit'):load_gold(monkeypatch,parser,mutate_import=True)
    finally:sys.set_int_max_str_digits(initial)

def test_exception_path_cannot_hide_global_limit_change(monkeypatch):
    initial=sys.get_int_max_str_digits()
    def mutate(*a,**k):
        sys.set_int_max_str_digits(0)
        raise ValueError('synthetic parser failure')
    parser=SimpleNamespace(parse_short_draft=mutate,render_short_draft=mutate,find_empty_chapters=mutate)
    try:
        ns=load_gold(monkeypatch,parser)
        with pytest.raises(AssertionError,match='integer limit'):ns['parse_short_draft']('synthetic',2)
    finally:sys.set_int_max_str_digits(initial)

def test_unchanged_global_limit_preserves_return_values(monkeypatch):
    initial=sys.get_int_max_str_digits();value=['one','two']
    parser=SimpleNamespace(parse_short_draft=lambda *a:value,render_short_draft=lambda *a:'body',find_empty_chapters=lambda *a:[2])
    ns=load_gold(monkeypatch,parser)
    assert ns['parse_short_draft']('synthetic',2) is value
    assert ns['render_short_draft'](value)=='body' and ns['find_empty_chapters'](value)==[2]
    assert sys.get_int_max_str_digits()==initial

def test_all_direct_numbering_calls_are_protected_by_shared_alias(monkeypatch):
    initial=sys.get_int_max_str_digits()
    def mutate(*a,**k):
        sys.set_int_max_str_digits(0)
        return ['第一章。','第二章。']
    parser=SimpleNamespace(parse_short_draft=mutate,render_short_draft=lambda *a:'',find_empty_chapters=lambda *a:[])
    try:
        ns=load_gold(monkeypatch,parser)
        case=ns['OrdinaryUnicodeNumbers']('test_arabic_indic_nonzero_digits')
        with pytest.raises(AssertionError,match='integer limit'):case.test_arabic_indic_nonzero_digits()
    finally:sys.set_int_max_str_digits(initial)
