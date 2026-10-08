"""Independent labels and leakage guard for retrieval evaluation."""
from myink.evaluation.retrieval import retrieval_metrics


def test_missing_history_and_foreign_future_rows_are_not_quality_hits():
    rows=[{'event_id':'a','chapter':2,'project_id':'p','summary':'林川修仪器'},
          {'event_id':'future','chapter':8,'project_id':'p','summary':'未来'},
          {'event_id':'foreign','chapter':1,'project_id':'other','summary':'异书'},
          {'event_id':'a','chapter':2,'project_id':'p','summary':'重复'}]
    result=retrieval_metrics(['a','b'],rows,chapter_seq=8,project_id='p')
    assert result['recall_at_k']==0.5
    assert result['returned_unique']==3
    assert result['future_leaks']==1 and result['tenant_leaks']==1
    assert result['irrelevant_ratio']==2/3
    assert result['tokens_est']>0


def test_empty_required_is_not_perfect_recall():
    result=retrieval_metrics([],[],chapter_seq=2,project_id='p')
    assert result['recall_at_k'] is None and result['irrelevant_ratio'] is None


def test_retrieval_case_rejects_duplicate_and_unavailable_required_events():
    import pytest
    from myink.evaluation.retrieval import RetrievalCase
    case={'id':'sample','group_id':'sample','split':'development','canonical':'林川',
          'aliases':[],'participants':['林川'],'query':'旧事','events':[
              {'id':'needed','chapter':1,'summary':'旧事'}],'required':['needed'],'label':'proposed'}
    assert RetrievalCase.model_validate(case).required==['needed']
    with pytest.raises(ValueError):RetrievalCase.model_validate({**case,'required':['unknown']})
    with pytest.raises(ValueError):RetrievalCase.model_validate({**case,'events':case['events']*2})
    with pytest.raises(ValueError):RetrievalCase.model_validate({**case,'events':[{'id':'needed','chapter':30,'summary':'未来'}]})
