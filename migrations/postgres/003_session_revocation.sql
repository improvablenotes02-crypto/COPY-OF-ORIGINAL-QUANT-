-- Apply only in the central identity database.
CREATE TABLE IF NOT EXISTS public.qe_session_revocations (
 subject_id text NOT NULL CHECK(length(subject_id) BETWEEN 1 AND 512),
 session_id text NOT NULL CHECK(length(session_id) BETWEEN 1 AND 512),
 revoked_at_epoch double precision NOT NULL CHECK(revoked_at_epoch >= 0 AND revoked_at_epoch < 'Infinity'::double precision),
 PRIMARY KEY(subject_id,session_id)
);
CREATE INDEX IF NOT EXISTS qe_session_revocations_session ON public.qe_session_revocations(session_id);
-- Grant SELECT/INSERT/UPDATE only to a dedicated server-side identity-session role.
