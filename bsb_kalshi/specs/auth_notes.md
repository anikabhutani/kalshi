# Kalshi auth notes (source of truth for signing)

Pasted from the Kalshi documentation by the project owner. The "Quick Start: Create your
first order" guide was intentionally omitted because it only describes write endpoints,
which Kalshi Recon never calls.

---

## API Environments and Endpoints

REST and WebSocket base URLs for production and demo.

Kalshi provides separate production and demo environments. Credentials are not shared
between environments, so demo API keys only work against demo endpoints and production API
keys only work against production endpoints.

### REST API

| Environment | Recommended base URL | Also supported |
|---|---|---|
| Production | https://external-api.kalshi.com/trade-api/v2 | https://api.elections.kalshi.com/trade-api/v2 |
| Demo | https://external-api.demo.kalshi.co/trade-api/v2 | https://demo-api.kalshi.co/trade-api/v2 |

The external-api hosts are dedicated to the external Trade API and are the recommended hosts
for API traders. The existing shared hosts remain supported for compatibility with existing
clients. Despite the elections subdomain, the production Trade API provides access to all
Kalshi markets, not only election-related markets.

### WebSocket API

| Environment | Recommended URL | Also supported |
|---|---|---|
| Production | wss://external-api-ws.kalshi.com/trade-api/ws/v2 | wss://api.elections.kalshi.com/trade-api/ws/v2 |
| Demo | wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2 | wss://demo-api.kalshi.co/trade-api/ws/v2 |

### Request Signing

The host does not change the signature payload. Sign the full request path from the API
root, without query parameters.

If the request URL is:

    https://external-api.kalshi.com/trade-api/v2/portfolio/orders?limit=5

sign:

    /trade-api/v2/portfolio/orders

not the hostname and not the query string.

---

## Quick Start: Market Data (unauthenticated)

Kalshi provides several public endpoints that don't require API keys, served from
`https://external-api.kalshi.com/trade-api/v2`. No authentication headers are required for
the endpoints in this guide.

- Step 1: `GET /series/KXHIGHNY` -> `series_data['series']['title' | 'frequency' | 'category']`
- Step 2: `GET /markets?series_ticker=KXHIGHNY&status=open` -> `markets[]` with `ticker`,
  `title`, `event_ticker`, `yes_bid_dollars`, `volume_fp`. If there are no open markets,
  remove `status=open`.
- Step 2b: `GET /events/{event_ticker}` -> `event['title' | 'category']`
- Step 3: `GET /markets/{market_ticker}/orderbook` -> `orderbook_fp['yes_dollars']` and
  `orderbook_fp['no_dollars']`, each a list of `[price_dollars, count_fp]`.

The API uses cursor-based pagination. The orderbook only returns bids (not asks) because of
the reciprocal relationship between YES and NO positions.

Setting up a WebSocket connection for live updates requires authentication.

---

## Quick Start: Authenticated Requests

Every authenticated request to Kalshi requires three headers:

| Header | Description | Example |
|---|---|---|
| KALSHI-ACCESS-KEY | Your API Key ID | a952bcbe-ec3b-4b5b-b8f9-11dae589608c |
| KALSHI-ACCESS-TIMESTAMP | Current time in milliseconds | 1703123456789 |
| KALSHI-ACCESS-SIGNATURE | Request signature (see below) | base64_encoded_signature |

### How to Create the Signature

1. Create a message string: concatenate `timestamp + HTTP_METHOD + path`.
   Example: `1703123456789GET/trade-api/v2/portfolio/balance`.
   Sign the full URL path from the API root, without query parameters. For
   `https://external-api.demo.kalshi.co/trade-api/v2/portfolio/orders?limit=5`, sign
   `/trade-api/v2/portfolio/orders`.
2. Sign with your private key: RSA keys use RSA-PSS with SHA-256; Ed25519 keys sign the
   message directly.
3. Encode as base64.

```python
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def sign_request(private_key, timestamp, method, path):
    path_without_query = path.split('?')[0]
    message = f"{timestamp}{method}{path_without_query}".encode('utf-8')
    if isinstance(private_key, Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
    return base64.b64encode(signature).decode('utf-8')
```

Key loading: `serialization.load_pem_private_key(f.read(), password=None)`.

Signing path: `urlparse(base_url + path).path` (e.g. `/trade-api/v2/portfolio/balance`).

Example authenticated call: `GET /portfolio/balance` -> `balance` (cents).

### Common Issues

| Problem | Solution |
|---|---|
| 401 Unauthorized | Check the API Key ID and private key path, and sign with the algorithm of the parsed key (the PEM header alone does not tell you which) |
| Signature error | Ensure timestamp is in milliseconds (not seconds) |
| Path not found | If BASE_URL already ends with /trade-api/v2, pass only the endpoint path (e.g. /portfolio/balance) so the URL is not double-prefixed |
| Signature error with query params | Sign the request path without query parameters |

---

## Quick Start: WebSockets

Real-time updates for order book changes, trade executions, market status updates, fill
notifications.

Connection URL: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`
(demo: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`). The shared hosts
`wss://api.elections.kalshi.com/trade-api/ws/v2` (production) and
`wss://demo-api.kalshi.co/trade-api/ws/v2` (demo) remain supported.

### Authentication

WebSocket connections require authentication during the connection handshake. Once
connected, channels fall into two groups:

- Private channels (user-specific data): orderbook_delta, fill, market_positions,
  communications, order_group_updates
- Public market-data channels (no additional channel-level auth): ticker, trade,
  market_lifecycle_v2, multivariate_market_lifecycle, multivariate

Even channels that carry public market data still use the authenticated WebSocket session,
but they do not impose additional per-channel authorization checks.

Required handshake headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`,
`KALSHI-ACCESS-TIMESTAMP` (unix ms).

Signature message: `timestamp + "GET" + "/trade-api/ws/v2"`, signed exactly like REST.

```python
async with websockets.connect(ws_url, additional_headers=auth_headers) as websocket:
    async for message in websocket:
        ...
```

### Subscribing

```json
{"id": 1, "cmd": "subscribe", "params": {"channels": ["ticker"]}}
{"id": 2, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_tickers": ["..."]}}
{"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": "..."}}
```

### Processing messages

Message `type` values used in the guide: `subscribed`, `ticker` (msg.market_ticker,
msg.yes_bid_dollars, msg.yes_ask_dollars), `orderbook_snapshot`, `orderbook_delta`
(optional msg.client_order_id), `error` (msg.code, msg.msg).

Error format:

```json
{"id": 123, "type": "error", "msg": {"code": 2, "msg": "Params required"}}
```

### Keep-alive

The Python websockets library automatically handles ping/pong frames. No manual heartbeat
handling is required.

### Error codes

| Code | Error | Description |
|---|---|---|
| 1 | Unable to process message | Invalid JSON or incompatible field type |
| 2 | Params required | Command requires params or required subscription params missing |
| 3 | Channels required | Subscribe must include at least one channel |
| 4 | Subscription IDs required | Unsubscribe must include at least one sid |
| 5 | Unknown command | cmd value not supported |
| 6 | Retired | Not emitted |
| 7 | Unknown subscription ID | Command references inactive sid |
| 8 | Unknown channel name | Channel not supported by this endpoint |
| 9 | Authentication required | Channel/action requires auth not granted |
| 10 | Channel error | Internal channel error |
| 11 | Invalid parameter | e.g. malformed market ID |
| 12 | Exactly one subscription ID is required | update_subscription |
| 13 | Unsupported action | Subscription does not support the action |
| 14 | Market Ticker required | Needs market_ticker or market_tickers |
| 15 | Action required | update_subscription needs params.action |
| 16, 17 | Retired | Not emitted |
| 18 | Command timeout | Server timed out routing a command |
| 19-22 | shard_factor / shard_key errors | communications sharding |
| 25 | Subscription buffer overflow | Subscribe to less data or read faster |

### Best practices

Reconnect with exponential backoff, handle malformed messages, cache the initial orderbook
state before applying updates, never expose the private key client-side, subscribe only to
markets you need.
