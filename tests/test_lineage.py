from src.tools.queue import submit_task_handler,get_task_handler,set_task_status_handler,amend_task_handler
from src.lineage import fingerprint

def seed(tmp_path,**kw):
    return submit_task_handler(source_agent='planner',target_agent='builder',task_type='build',summary='Build',description='Reviewed work',queue_dir=str(tmp_path),**kw)

def test_lineage_is_typed_and_inherited_by_authorized_followup(tmp_path):
    first=seed(tmp_path,lineage={'ticket_id':62,'project':'schlagbaum'})
    assert first['ok']
    child=submit_task_handler(source_agent='builder',target_agent='deployer',task_type='deploy',summary='Release',description='Deploy selected artifact',originating_task_id=first['task_id'],queue_dir=str(tmp_path))
    assert get_task_handler(child['task_id'],str(tmp_path))['payload']['lineage']=={'ticket_id':62,'project':'schlagbaum'}
    refused=submit_task_handler(source_agent='builder',target_agent='deployer',task_type='deploy',summary='Release',description='Changed ticket',originating_task_id=first['task_id'],queue_dir=str(tmp_path),lineage={'ticket_id':99,'project':'parker'})
    assert refused['ok'] is False

def test_invalid_lineage_does_not_write(tmp_path):
    for lineage in [{'ticket_id':True,'project':'parker'},{'ticket_id':1,'project':'foreign'},{'ticket_id':1,'project':'parker','authority':'admin'}]:
        assert seed(tmp_path,lineage=lineage)['ok'] is False
    assert not list(tmp_path.glob('*.yml'))

def test_approval_refuses_amendment_between_review_and_approval(tmp_path):
    result=seed(tmp_path);tid=result['task_id']
    reviewed=fingerprint(get_task_handler(tid,str(tmp_path)))
    assert amend_task_handler(tid,'Additional production operation','planner',queue_dir=str(tmp_path))['ok']
    refused=set_task_status_handler(tid,'approved','operator',expected_fingerprint=reviewed,queue_dir=str(tmp_path))
    assert refused['ok'] is False
    current=get_task_handler(tid,str(tmp_path));assert current['status']=='submitted'
    assert set_task_status_handler(tid,'approved','operator',expected_fingerprint=fingerprint(current),queue_dir=str(tmp_path))['ok']
