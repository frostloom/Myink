from pathlib import Path
from myink.evaluation.cases import load_cases


def test_alias_error_and_replacement_share_group_and_distinct_labels():
    cases={c.id:c for c in load_cases(Path('evals/cases/audit'),Path.cwd())}
    bad=cases['hard.alias_destroyed']; good=cases['hard.alias_replaced']
    assert bad.group_id==good.group_id and bad.split==good.split
    assert bad.expected.required_issues and not good.expected.required_issues
    assert '老林' in bad.input.draft and '林川' in str(bad.input.context)
