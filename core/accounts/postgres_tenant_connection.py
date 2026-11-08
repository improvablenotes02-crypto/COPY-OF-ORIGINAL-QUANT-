"""Tenant-bound PostgreSQL connection routing."""
from __future__ import annotations
from contextlib import ExitStack, contextmanager
import sys
from typing import Callable, Iterator


class PostgreSQLTenantIdentityError(RuntimeError):
    """Raised when the database cannot prove the requested tenant identity."""


class TenantBoundPostgreSQLConnection:
    """Open identity-checked transactions using trusted tenant-specific DSNs."""

    def __init__(self, dsn_resolver: Callable[[str], str], *, connect_timeout: int = 5, connect_factory=None):
        if not callable(dsn_resolver):
            raise ValueError("trusted tenant DSN resolver is required")
        if isinstance(connect_timeout, bool) or not isinstance(connect_timeout, int) or not 1 <= connect_timeout <= 60:
            raise ValueError("connect_timeout must be an integer from 1 to 60")
        if connect_factory is not None and not callable(connect_factory):
            raise ValueError("connect_factory must be callable")
        self._dsn_resolver, self._connect_timeout, self._connect_factory = dsn_resolver, connect_timeout, connect_factory

    @contextmanager
    def connect(self, tenant_id: str) -> Iterator[object]:
        if not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 128:
            raise ValueError("tenant_id must be a non-empty string of at most 128 characters")

        # Only connection establishment and identity verification are translated
        # into an identity error. Exceptions from application code inside the
        # yielded transaction must retain their original type and meaning.
        stack = ExitStack()
        try:
            dsn = self._dsn_resolver(tenant_id)
            if not isinstance(dsn, str) or not dsn.strip():
                raise PostgreSQLTenantIdentityError("tenant database identity is unavailable")
            from psycopg.rows import dict_row
            if self._connect_factory is None:
                import psycopg
                connect = psycopg.connect
            else:
                connect = self._connect_factory
            connection = stack.enter_context(
                connect(dsn, connect_timeout=self._connect_timeout, row_factory=dict_row)
            )
            stack.enter_context(connection.transaction())
            row = connection.execute(
                "SELECT public.qe_authenticated_tenant_id() AS tenant_id"
            ).fetchone()
            actual_tenant = row["tenant_id"] if row else None
            if actual_tenant != tenant_id:
                raise PostgreSQLTenantIdentityError(
                    "authenticated database tenant does not match requested tenant"
                )
        except (ValueError, PostgreSQLTenantIdentityError):
            try:
                stack.__exit__(*sys.exc_info())
            except Exception:
                pass
            raise
        except Exception:
            try:
                stack.__exit__(*sys.exc_info())
            except Exception:
                pass
            # Never expose DSNs, credentials, SQL parameters, or driver diagnostics.
            raise PostgreSQLTenantIdentityError(
                "tenant database identity verification failed"
            ) from None

        # Keep this outside the redaction handler: domain and authorization
        # exceptions are not connection-identity failures.
        with stack:
            yield connection
