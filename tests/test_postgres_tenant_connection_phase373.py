"""Phase 373-375: tenant-bound PostgreSQL routing and adapter admission."""
import pytest
from core.accounts.postgres_tenant_connection import PostgreSQLTenantIdentityError, TenantBoundPostgreSQLConnection

class _Transaction:
    def __enter__(self): return self
    def __exit__(self, typ, value, tb): return False
class _Connection:
    def __init__(self, tenant): self.tenant, self.queries = tenant, []
    def __enter__(self): return self
    def __exit__(self, typ, value, tb): return False
    def transaction(self): return _Transaction()
    def execute(self, sql):
        self.queries.append(sql)
        assert sql == "SELECT public.qe_authenticated_tenant_id() AS tenant_id"
        return self
    def fetchone(self): return {"tenant_id": self.tenant}

def _factory_for(tenant):
    opened=[]
    def factory(dsn, *, connect_timeout, row_factory):
        conn=_Connection(tenant); opened.append((dsn,connect_timeout,row_factory,conn)); return conn
    return factory,opened

def test_tenant_dsn_and_authenticated_identity_checked():
    factory,opened=_factory_for("tenant-a")
    router=TenantBoundPostgreSQLConnection(lambda tenant:f"postgresql://role-for-{tenant}/db",connect_timeout=7,connect_factory=factory)
    with router.connect("tenant-a") as conn: assert conn.tenant=="tenant-a"
    assert opened[0][0]=="postgresql://role-for-tenant-a/db" and opened[0][1]==7
    assert opened[0][2] is not None
    assert opened[0][3].queries==["SELECT public.qe_authenticated_tenant_id() AS tenant_id"]

@pytest.mark.parametrize("identity",[None,"tenant-b",""])
def test_missing_or_mismatched_identity_fails_closed(identity):
    factory,opened=_factory_for(identity)
    router=TenantBoundPostgreSQLConnection(lambda tenant:"dsn",connect_factory=factory)
    with pytest.raises(PostgreSQLTenantIdentityError):
        with router.connect("tenant-a"): pytest.fail("untrusted connection yielded")
    assert len(opened)==1

def test_identity_query_failure_is_redacted():
    class Broken(_Connection):
        def execute(self,sql): raise RuntimeError("sensitive driver details")
    router=TenantBoundPostgreSQLConnection(lambda tenant:"dsn",connect_factory=lambda dsn,**kw:Broken("tenant-a"))
    with pytest.raises(PostgreSQLTenantIdentityError,match="verification failed"):
        with router.connect("tenant-a"): pytest.fail("untrusted connection yielded")

def test_invalid_resolver_output_fails_closed():
    router=TenantBoundPostgreSQLConnection(lambda tenant:None,connect_factory=lambda *a,**k:None)
    with pytest.raises(PostgreSQLTenantIdentityError):
        with router.connect("tenant-a"): pytest.fail("untrusted connection yielded")

def test_authenticated_adapters_keep_production_readiness_false():
    from core.accounts.postgres_delta_account_repository import AuthenticatedPostgreSQLDeltaAccountRepository
    from core.accounts.postgres_owner_governance_repository import AuthenticatedPostgreSQLOwnerGovernanceRepository
    delta=AuthenticatedPostgreSQLDeltaAccountRepository(lambda tenant:"tenant-specific-dsn")
    governance=AuthenticatedPostgreSQLOwnerGovernanceRepository(lambda tenant:"tenant-specific-dsn")
    assert delta.tenant_isolation_enforced and not delta.production_ready
    assert governance.tenant_isolation_enforced and not governance.production_ready
