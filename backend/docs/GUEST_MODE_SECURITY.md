# Guest Mode Security

## Threat model

| Threat | Mitigation |
|--------|------------|
| Guess another guest's job UUID | Ownership check on every job/doc/chat (`owner_type`+`owner_id`); 403/404 |
| Steal guest cookie | HttpOnly + Secure (prod) + SameSite=Lax; 2h inactivity (sliding on each API request) |
| Cross-tenant via JWT | JWT still verified first; guest never overrides a valid user |
| PII in guest rows | No email/password; optional `ip_hash` / `user_agent_hash` only |
| Abuse (large PDFs / chat spam) | 25 MB upload cap; 50 chats/session; 1 active document |
| Orphan data after expiry | Cleanup loop every 30 min purges guest jobs/docs/chats/R2/embeddings |

## Session material

- Cookie: `ga_guest_session` (HttpOnly)
- Header fallback: `X-Guest-Session-Id` (required for CORS `*` cross-origin)
- IDs are UUIDv4 — not enumerable

## Isolation rules

```
assert owner_type/owner_id on resource == caller owner
legacy rows: fall back to user_id match for USER only
```

Guests cannot call `get_current_user` routes that require JWT (e.g. `/auth/me`).

## Upgrade safety

`POST /guest/upgrade` requires a **valid JWT** and the guest session id.  
Transfer is an SQL UPDATE of ownership stamps — no recompute, no cross-guest move without the session secret.

## What is not shared

Expired guest purge deletes: PDFs (R2), embeddings, conversations, jobs, document rows.  
Shared telemetry aggregates are **not** deleted.
