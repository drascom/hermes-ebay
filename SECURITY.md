# Security Policy

## Supported versions

Security fixes are provided for the latest release.

## Reporting

Please report vulnerabilities privately through GitHub Security Advisories for `drascom/hermes-ebay`. Do not open a public issue containing credentials, OAuth codes, tokens, buyer data, order data, or seller data.

## Data and threat model

- The plugin is read-only with respect to eBay seller resources.
- App credentials remain in the active Hermes profile `.env`; OAuth tokens remain in a profile-scoped `0600` file.
- Token endpoints receive HTTP Basic credentials only over a fixed eBay HTTPS origin. Marketplace bearer tokens are sent only to `https://api.ebay.com`.
- Tool output and monitor state omit buyer identity, addresses, email, usernames, and item titles.
- Dedupe state contains one-way SHA-256 event fingerprints and timestamps.
- Hermes plugins execute in-process and are not a security sandbox. Review source and pin an immutable commit for high-assurance installation.

Revoking access in eBay's account settings is the authoritative emergency response. Then run `hermes ebay disconnect` and rotate the Cert ID in the eBay developer portal if it may have been exposed.
