"""Central PostgreSQL session denylist; deployment admission remains disabled."""
import math

class PostgreSQLSessionRevocationStore:
    production_ready = False
    durable_shared_storage = True
    global_session_scope = True

    def __init__(self, dsn, *, connect_timeout=5, connect_factory=None):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("central identity database DSN is required")
        if isinstance(connect_timeout, bool) or not isinstance(connect_timeout, int) or not 1 <= connect_timeout <= 60:
            raise ValueError("invalid connect_timeout")
        if connect_factory is not None and not callable(connect_factory):
            raise ValueError("connect_factory must be callable")
        self._dsn, self._timeout, self._factory = dsn, connect_timeout, connect_factory

    def _connect(self):
        if self._factory:
            return self._factory(self._dsn, connect_timeout=self._timeout)
        import psycopg
        return psycopg.connect(self._dsn, connect_timeout=self._timeout)

    @staticmethod
    def _validate(subject_id, session_id):
        if not isinstance(subject_id, str) or not subject_id.strip() or len(subject_id) > 512:
            raise ValueError("invalid subject_id")
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 512:
            raise ValueError("invalid session_id")

    def is_revoked(self, subject_id, session_id):
        self._validate(subject_id, session_id)
        try:
            with self._connect() as db:
                row = db.execute("SELECT 1 FROM public.qe_session_revocations WHERE subject_id=%s AND session_id=%s", (subject_id, session_id)).fetchone()
            return row is not None
        except Exception:
            raise RuntimeError("PostgreSQL session-revocation lookup failed") from None

    def revoke(self, subject_id, session_id, *, revoked_at_epoch):
        self._validate(subject_id, session_id)
        if isinstance(revoked_at_epoch, bool) or not isinstance(revoked_at_epoch, (int, float)) or not math.isfinite(float(revoked_at_epoch)) or revoked_at_epoch < 0:
            raise ValueError("invalid revocation timestamp")
        try:
            with self._connect() as db:
                db.execute("INSERT INTO public.qe_session_revocations(subject_id,session_id,revoked_at_epoch) VALUES(%s,%s,%s) ON CONFLICT(subject_id,session_id) DO UPDATE SET revoked_at_epoch=LEAST(public.qe_session_revocations.revoked_at_epoch,EXCLUDED.revoked_at_epoch)", (subject_id, session_id, float(revoked_at_epoch)))
        except Exception:
            raise RuntimeError("PostgreSQL session-revocation write failed") from None
