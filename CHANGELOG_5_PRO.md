# Changelog - Sonar Radar Pro 5.0

## New
- Added owner-scoped PostgreSQL Pro schemas for favorites, tags, connection metrics, incidents, audit, team, safe automation rules, preferences, and migrations.
- Added responsive Telegram Mini App frontend + signed Telegram initData FastAPI backend, with no raw web tokens.
- Added `/pro`, `/find`, `/tag`, `/history`, `/probe`, `/insights`, `/diagnose`, `/team`, `/member`, `/workspace`, `/rule`, `/quiet`, `/pdfreport`.
- Added optional bounded and fair multi-node tests (two nodes maximum, explicit opt-in), incident acknowledgement/recovery, daily opt-in digest, and retention cleanup.
- Added comparative config scoring, favoriting, search/tag filtering, CSV and Persian/RTL PDF reports.
- Added WSS opt-in support to WebSocket agent server and client with certificate validation.
- Added `install_web_panel.sh` and example nginx TLS/rate-limit configuration.
- Added Pro front-end trend chart for config latency.

## Changed
- New compact network overview on main screen; Pro Center entries in menu, dashboard and settings hub.
- One remaining `config_cron_kb` definition instead of three shadowing definitions.
- Removed dead 'wallet top-up coming soon' control, renamed legacy dummy Web Token to safe Mini App setup.
- Updated normal single-config batch tester to save Pro metrics atomically.
- Avoided decrypting SSH passwords as candidate agent WS credentials; dedicated tokens are retrieved in core.
- Improved agent token lookup to prefer the configured WS port.
- Added monitor-node owner restrictions for *new* Pro manual and scheduled probes.
- Added additional installer dependency failure detection and PDF system libraries.
- Sanitized bundled `sonar_config.json` (no live Telegram token/admin ID in downloadable ZIP).

## Compatibility and known limits
See `README_5_PRO_FA.md` for deployment steps, optional components, and a candid list of features not yet completed, including persistent external job queue and per-node mTLS.
