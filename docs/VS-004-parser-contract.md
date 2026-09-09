# VS-004 match-detail parser contract

The match-detail parser reads the current VLR overview structure by semantic
`data-col` attributes inside `ovw-row` elements. It returns `stats_status` as
`available`, `partial`, or `unavailable`, plus human-readable
`parse_warnings`. A completed or live page whose stats container no longer
matches the supported structure raises `MatchDetailParseError` instead of
returning a successful empty result.

Player statistics remain nested under their map. An `all` game is used when
VLR supplies one; otherwise the API's existing aggregation path combines the
individual map records. KD remains derived from kills and deaths for the
existing API contract.

## Agents and roles

VLR currently exposes played agents as image metadata. Those values are not
tactical roles and are never written to `PlayerStat.role`. Persisting agents
would require a multi-agent-per-map database and API contract plus an iOS UI
change, so it is deferred from V1 of this repair. The API exposes the parser's
team tag as `team_abbreviation`, and the player subtitle names that data
directly instead of presenting it as a tactical role. The existing `role`
response field remains available for contract compatibility but is not used as
a substitute for agents or a team abbreviation.

Follow-up: add an explicit `agents: [String]` field through the parser,
database, API, and Swift models, then render agent names or icons without
reusing the role field.
