# Hermes eBay

A production-oriented, read-only Hermes Agent plugin for monitoring an eBay seller account. It exposes six tools and an opt-in, deduplicated 30-minute alert job. It does not create listings, issue refunds, message buyers, or persist buyer PII.

## Requirements

- Hermes Agent 0.21.6 or later
- An eBay Developer Program account
- An activated **Production** keyset with App ID (Client ID) and Cert ID (Client Secret)
- An eBay OAuth Redirect URL configured in the developer portal; eBay calls its identifier the **RuName**

## eBay prerequisites and compliance caveat

1. In the [eBay Developer Program](https://developer.ebay.com/), create or select an application.
2. Activate its Production keyset. Sandbox credentials do not work with this plugin's Production endpoints.
3. Under User Tokens, configure an OAuth Redirect URL and note the generated RuName. Supply the RuName—not the URL itself—as `EBAY_RUNAME`.
4. Review eBay's Marketplace Account Deletion/Closure notification requirements. Depending on your application and data use, eBay may require a deletion-notification endpoint or an approved exemption. This plugin does not create that endpoint and does not make your application compliant by itself. Obtain the appropriate exemption or implement the required endpoint before production use.

Requested scopes:

- `https://api.ebay.com/oauth/api_scope`
- `https://api.ebay.com/oauth/api_scope/sell.account.readonly`
- `https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly`
- `https://api.ebay.com/oauth/api_scope/sell.inventory.readonly`

Returns and cancellations use eBay's Post-Order read endpoints. eBay may vary scope availability by seller program and marketplace.

## Install

From GitHub:

```text
hermes plugins install drascom/hermes-ebay --yes-deps --enable
```

Or from a clone:

```text
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## Terminal-only setup

OAuth setup is deliberately terminal-only: never paste a Cert ID, authorization code, access token, or refresh token into a chat.

```text
hermes ebay setup
hermes ebay connect
hermes ebay status
```

`setup` prompts with hidden input for the Cert ID and writes the three app values to the active profile's `$HERMES_HOME/.env` with mode `0600`. `connect` opens eBay consent and asks for the returned authorization code with hidden input. OAuth access and refresh tokens are stored under `$HERMES_HOME/plugin-data/ebay/tokens.json` with mode `0600`; tools refresh access tokens automatically before expiry. Neither status nor tool output returns credentials or tokens.

For SSH/headless systems:

```text
hermes ebay connect --no-browser
```

Open the printed URL on another device, approve it, then paste only the `code` query value into the hidden terminal prompt. The `state` value protects browser navigation but eBay's RuName redirect prevents a conventional loopback callback, so verify the redirect host before copying the code.

## Tools

- `ebay_account_status` — seller registration and selling limits
- `ebay_orders` — recent order status and pricing summary, with buyer fields omitted
- `ebay_offers` — inventory offers
- `ebay_returns` — return IDs and state only
- `ebay_cancellations` — cancellation IDs and state only
- `ebay_monitor_status` — connection and dedupe status, never secrets

All API calls are GET requests except OAuth token exchange/renewal. There are no write-capable marketplace tools.

## Opt-in alerts

Enable a no-LLM monitor every 30 minutes:

```text
hermes ebay monitor enable --deliver telegram
```

Other delivery values accepted by Hermes include `discord`, `signal`, `platform:chat_id`, and `local`. `local` records the job without sending chat notifications. The first successful poll establishes a baseline silently; later unseen order/return/cancellation state transitions are delivered. Dedupe records are SHA-256 hashes of event type, platform identifier, and state. Buyer names, addresses, usernames, emails, and item titles are never persisted.

```text
hermes ebay monitor status
hermes ebay monitor disable
```

A running Hermes gateway/ticker is required for cron execution; verify with `hermes cron status`.

## Disconnect and uninstall

```text
hermes ebay disconnect
hermes plugins remove ebay
```

`disconnect` removes the plugin-managed cron job, OAuth token file, and dedupe database. It does not delete the BYO app credentials from `.env`, because those may be reused and deleting arbitrary user configuration during uninstall is unsafe. Remove `EBAY_APP_ID`, `EBAY_CERT_ID`, and `EBAY_RUNAME` from the active profile's `.env` yourself if desired. `hermes plugins remove ebay` also removes plugin grants managed by Hermes, but this plugin uses its own RuName flow and therefore requires `disconnect` first.

## Troubleshooting

- `invalid_client`: confirm Production App ID/Cert ID, with no Sandbox/Production mixing.
- `invalid_grant`: authorization codes are short-lived and single-use; reconnect and paste a fresh code.
- `redirect_uri_mismatch` or `unauthorized_client`: supply the exact RuName associated with your Production keyset, not its callback URL.
- `insufficient_scope`: reconnect after confirming the scopes are enabled for the keyset and seller account.
- HTTP 401 after refresh: the user grant may be revoked; run `hermes ebay disconnect`, then connect again.
- Empty returns/cancellations: the account may have no cases, or eBay may not expose the Post-Order endpoint for that program/marketplace.
- Alerts do not run: check `hermes cron status`, the gateway, and the chosen delivery platform.

## Security

See [SECURITY.md](SECURITY.md). The plugin uses Python's standard TLS client, explicit eBay HTTPS origins, bounded timeouts, file modes `0700`/`0600`, allowlisted output fields, and parameterized SQLite statements. Never commit `.env`, `tokens.json`, `monitor.sqlite3`, or real sample output.

## Fake sample output

```json
{"success":true,"data":{"total":1,"orders":[{"orderId":"FAKE-ORDER-1001","creationDate":"2026-01-02T03:04:05Z","orderFulfillmentStatus":"NOT_STARTED","orderPaymentStatus":"PAID","pricingSummary":{"total":{"value":"19.99","currency":"USD"}}}]}}
```

```json
{"connected":true,"token_expires_at":1790000000,"monitor_initialized_at":"1789990000","dedupe_records":12,"pii_persisted":false}
```

## Development

```text
uv sync --dev
uv run pytest
uv run ruff check .
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

License: MIT.
