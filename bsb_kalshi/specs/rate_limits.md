# Rate Limits and Tiers

Pasted from the Kalshi documentation by the project owner. Perps-only sections are kept for
completeness but are out of scope for Kalshi Recon.

## Token-based limits

Every authenticated request costs tokens. Your tier sets your budget: the rate, in tokens per
second, at which your balance refills. Your sustained rate for an endpoint is budget ÷ cost.

Most requests cost the default of 10 tokens. For endpoints that cost more or less,
`GET /account/endpoint_costs` is the authoritative list of non-default costs currently in
effect.

## Read and Write buckets

| Bucket | Covers |
|---|---|
| Read | GET endpoints and anything not routed to Write. |
| Write | Order placement, amends, cancels, order groups, the RFQ quote flow, and block trade proposal accepts. |

The split is by operation type, not by protocol. REST and FIX requests drain the same buckets.
Read budgets are not shard-scoped.

## Bucket capacity and bursting

Each budget is a token bucket. The bucket refills continuously at your per-second budget, up
to its capacity, and a request is allowed whenever the bucket holds enough tokens to cover
its cost. There are no fixed windows and no per-second resets.

Basic and Advanced Predictions Read buckets, and Write buckets above the Basic tier, hold up
to three seconds of budget. After three quiet seconds the bucket is full; you can then spend
up to three times your per-second budget in a single burst before throttling back to the
refill rate.

Predictions Read buckets above Advanced, Perps Read buckets, and Basic-tier Write buckets hold
one second of budget.

## When you hit the limit

A rate-limited request returns `429 Too Many Requests` with the body:

```json
{"error": "too many requests"}
```

429 responses do not currently include `Retry-After` or `X-RateLimit-*` headers. There is no
penalty or cooldown. The bucket keeps refilling, and your next request succeeds once the
balance covers its cost. Apply exponential backoff on 429.

## Batch endpoints don't save tokens

A batch request costs the same as making each call individually (write endpoints; not used by
this tool).

## Tiers and budgets

Per-second token budgets in each event-contract bucket:

| Tier | Read budget | Write budget |
|---|---|---|
| Basic | 200 | 100 |
| Advanced | 300 | 300 |
| Expert | 600 | 600 |
| Premier | 1,200 | 1,200 |
| Paragon | 2,400 | 2,400 |
| Prime | 4,800 | 4,800 |
| Prestige | 12,000 | 9,600 |

Write bucket capacity is three times the per-second budget above the Basic tier.

## Tier qualification

- Basic: complete account signup.
- Advanced: call the Upgrade Account API Usage Level endpoint (a write endpoint; not used by
  this tool).
- Expert and above: earned automatically from trading volume, or assigned by Kalshi.

## Your grants

Fetch your grants from `GET /account/limits`, returned alongside your current `usage_tier`:

```json
{
  "usage_tier": "premier",
  "read":  { "refill_rate": 1200, "bucket_capacity": 1200 },
  "write": { "refill_rate": 1200, "bucket_capacity": 3600 },
  "grants": [
    { "exchange_instance": "event_contract", "level": "premier", "expires_ts": 1751558400, "source": "volume" },
    { "exchange_instance": "event_contract", "level": "advanced", "source": "manual" }
  ]
}
```

A grant with no `expires_ts` is permanent.
