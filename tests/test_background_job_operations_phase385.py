import pytest
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal,ContextVarPrincipalSource,bind_authenticated_principal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore
from core.accounts.background_job_operations import SQLiteBackgroundJobOperations
def p(s="owner-1"):return AuthenticatedPrincipal(s,"s1",frozenset({"tenant-a"}),9999999999)
def setup(tmp_path):
 st=SQLiteBackgroundJobStore(str(tmp_path/"jobs.db"),clock=lambda:100.0);src=ContextVarPrincipalSource()
 op=SQLiteBackgroundJobOperations(st,principal_source=src,owner_authorizer=lambda x:x.subject_id=="owner-1",clock=lambda:101.0)
 with bind_authenticated_principal(p()):j=st.enqueue(src.current_principal(),"tenant-a");st.claim_job(j)
 return st,src,op,j
def test_phase385_owner_only_sanitized_inspection(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p("member")):
  with pytest.raises(PermissionError):op.inspect(j)
 with bind_authenticated_principal(p()):r=op.inspect(j)
 assert r["state"]=="RUNNING" and "session_id" not in r and "tenant_ids_json" not in r
def test_phase386_stale_inventory_bounded_and_read_only(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p()):r=op.stale_running(before_epoch=999,limit=3)
 assert len(r)==1 and r[0]["job_id"]==j and st.status(j)=="RUNNING"
 with pytest.raises(ValueError):op.stale_running(before_epoch=999,limit=501)
def test_phase387_review_never_changes_or_replays_job(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p()):
  e=op.review_running(j,disposition="OUTCOME_UNKNOWN",reason="venue outcome ambiguous")
  assert op.audit_chain_valid()
 assert e.actor_id=="owner-1" and st.status(j)=="RUNNING" and st.claim_job(j) is None
def test_phase388_owner_only_hash_chain_detects_tampering(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p("member")):
  with pytest.raises(PermissionError):op.review_running(j,disposition="NO_EXTERNAL_EFFECT",reason="checked")
 with bind_authenticated_principal(p()):
  op.review_running(j,disposition="NO_EXTERNAL_EFFECT",reason="reviewed")
  assert op.audit_chain_valid()
 c=st._connect()
 try:c.execute("DROP TRIGGER qe_job_review_no_update");c.execute("UPDATE qe_background_job_reviews SET reason='tampered'")
 finally:c.close()
 with bind_authenticated_principal(p()):assert not op.audit_chain_valid()
