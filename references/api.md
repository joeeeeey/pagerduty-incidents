# Official API and runtime notes

Reviewed 2026-10-08. Public documentation is authoritative for the target account/version.

## [REST API overview](https://docs.pagerduty.com/developer/rest-api-overview)

REST API version 2; user-context From header for incident changes.

## [Events API v2](https://developer.pagerduty.com/docs/events-api-v2/overview/)

Events routing keys and deduplication differ from REST authentication.

## Boundaries

Python 3.10+. REST: `PAGERDUTY_API_KEY` or `PAGERDUTY_API_KEY_FILE`. Events: `PAGERDUTY_EVENTS_ROUTING_KEY` or its `_FILE` counterpart. REST incident updates also need `PD_FROM_EMAIL` or `--from`. Secret files must be private (`chmod 600` on POSIX). Dry-run events need no credential.

List commands return one page; use `--param offset=...` and inspect pagination. US API endpoints only. The same dedup key on another integration is not the same incident. Raw output remains redacted but can contain incident details and personal data.

HTTP helpers do not follow redirects or automatically retry writes. A timeout can mean an unknown outcome; inspect the target before retrying. Secret-field redaction is defense in depth, not a guarantee that arbitrary free text is safe to publish.
