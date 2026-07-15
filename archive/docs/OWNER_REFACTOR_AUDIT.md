# Owner Refactor Audit

Generated for the final Owner-abstraction hardening pass.

## Categories

| Category | Meaning | Action |
|----------|---------|--------|
| AUTH | JWT, login, refresh tokens | Keep `user_id` |
| IDENTITY | Owner.user_id / guest_session_id fields | Keep |
| BUSINESS | Jobs, docs, convs, dashboard, chat, search | Migrate to `owner_type` + `owner_id` |
| WORKER | Claim/heartbeat/PK upsert | Keep PK paths; stamp Owner when writing |
| INTERNAL | Telemetry, scratch | Leave unless user-visible |

## Symbol map (pre-fix)

### AUTH / IDENTITY — keep
- `api/deps.py` `get_current_user`, `get_optional_user`
- `api/auth.py`, `db/refresh_tokens.py`
- `api/main.py` `/auth/*`, `/guest/upgrade` (JWT required)
- `core/owner.py` `user_id`, `guest_session_id` on Owner

### BUSINESS — migrate
- `db/jobs.py` `list_jobs_for_user`, `retain_only_latest_job`, user branch of `list_jobs_for_owner` / `retain_only_latest_job_for_owner`, `queue_snapshot_for_user`
- `db/jobs.py` `cancel_job` / `purge_job_completely` `user_id`-only permission checks
- `db/conversations.py` save/load omit Owner stamps
- `memory/service.py` conversation persist `user_id` only
- `memory/storage.py` `list_documents` / `get_dashboard_stats` `user_id` fallback
- `api/deps.py` legacy `require_*` / `assert_document_owner(user_id)` / `enforce_job_owner(user_id)` / `user_id` branch in `enforce_owner`

### WORKER — keep PK + stamp Owner
- `worker/runner.py` `get_job` by id, upsert by id; update `ensure_document_owner` to stamp Owner pair
- Claim/reclaim by `status` (system)

### INTERNAL — leave (Phase 6 = A)
- `db/routing_events.py` — shared telemetry, not user-visible Owner data

## Target end state
One ownership path for business resources: `owner_type` AND `owner_id`. No list/aggregate/delete-many by `user_id` alone.
