# ValScores API contract

This is the contract between the FastAPI backend (`valoreal/api.py`,
`valoreal/api_models.py`) and the SwiftUI client (`valoreal/MatchTimeContract.swift`,
`valoreal/APIModels.swift`, `valoreal/APIClient.swift`). FastAPI's generated schema at
`/openapi.json` is authoritative for field names and types; this document explains
their meaning.

Contract guarantees are enforced by tests:

- `tests/fixtures/api/*.json` are exact API responses for a deterministic database
  covering upcoming, live, incomplete, finished, postponed and cancelled matches.
  `tests/test_api_fixtures.py` checks that the API still produces them byte for byte
  and that they validate against the generated OpenAPI schema.
- Every JSON example in this document is tagged with its endpoint and validated
  against the same schema.
- `ValScoresTests/APIContractFixtureTests.swift` decodes every fixture with the
  app's real decoder.

After an intentional contract change, regenerate the fixtures, review the diff, and
update the Swift models and this document in the same commit:

```bash
UPDATE_API_FIXTURES=1 python -m unittest discover -s tests -p 'test_api_fixtures.py'
```

## Conventions

- JSON keys are `snake_case`.
- **`null` means unknown or not applicable. A number is always a value VLR
  reported.** A real `0` (for example zero assists) is sent as `0`; a value VLR has
  not published is `null`. Clients must never display `null` as zero; the app shows
  a dash.
- Responses never contain fields outside the schema, and clients must tolerate new
  optional fields being added.

## Identifiers

| Field | Meaning |
| --- | --- |
| `id` (timeline), `match_info.match_id` | ValScores match ID: the database primary key. It is the **only** match ID accepted in API paths (`/api/matches/{match_id}/stats`). Stable for the life of a database, not across databases. |
| `vlr_match_id` | Upstream VLR match ID, the number in `https://www.vlr.gg/<vlr_match_id>/...`, as a string without a leading slash. Informational; never used in API paths. Refresh failures use the same form. |
| `maps[].game_id`, `selected_game_id`, `game_id` query | Upstream VLR game (map) ID as a string, or `"all"` for the whole-series aggregate. Internal game row IDs are never exposed. |
| `maps[].map_number` | 1-based position in the series; `null` for `"all"` or when VLR does not number the map. |

## Match status

`status` is one of five values. Clients that receive any other value must treat it
as unknown rather than failing (Swift decodes it as `MatchStatus.unknown(raw)`).

| Status | Meaning | Scores |
| --- | --- | --- |
| `upcoming` | Scheduled, not started. | Series and round scores are `null`. |
| `live` | In progress. | Series score is maps won so far; round scores describe the current map. Either may be `null` if unknown. |
| `postponed` | VLR marked the match postponed; `start_time` is the last known schedule. | `null`. |
| `finished` | Completed. | Series score is final (`null` only if unknown); round scores are `null`. |
| `cancelled` | VLR marked the match cancelled. | `null`. |

`is_live` and `is_finished` are derived (`status == "live"` / `"finished"`) and kept
for compatibility.

Persistence (`valoreal/match_status.py`) only applies these transitions; any other
observation keeps the stored status, so a stale page cannot move a match backwards:

| From | Allowed to |
| --- | --- |
| `upcoming` | `live`, `postponed`, `finished`, `cancelled` |
| `postponed` | `upcoming` (rescheduled), `live`, `finished`, `cancelled` |
| `live` | `finished`, `cancelled` |
| `finished` | none (terminal) |
| `cancelled` | none (terminal) |

A stored `upcoming` match whose maps already have winners is reported as
`finished`. Legacy rows with an unrecognized stored label are reported as
`upcoming`.

## Timestamps and the timeline range

- `start_time` is always an ISO-8601 UTC instant ending in `Z`, such as
  `2026-09-07T10:00:00Z`. It is required in timeline responses: matches without a
  trustworthy start time are not returned.
- `GET /api/matches/timeline` requires `start` and `end` query parameters with an
  explicit UTC offset (`Z` or `+02:00`). A value without an offset is rejected with
  `invalid_range`.
- The range is half-open: a match is included when `start <= start_time < end`.
  `end` must be later than `start`, and the range may be at most 31 days.
- The client converts `start_time` to the device's calendar and time zone for
  grouping and display; the backend never applies a display time zone.

## Endpoints

### `GET /api/matches/timeline`

Returns persisted matches in the requested range, ordered by `start_time` then
`id`. Read-only. Full example: [timeline.json](../tests/fixtures/api/timeline.json).

<!-- example: GET /api/matches/timeline 200 -->
```json
[
  {
    "id": 2,
    "vlr_match_id": "730002",
    "team1": "Team Heretics",
    "team2": "FNATIC",
    "team1_score": 1,
    "team2_score": 0,
    "team1_round_score": 7,
    "team2_round_score": 5,
    "status": "live",
    "start_time": "2026-09-07T10:00:00Z",
    "is_live": true,
    "is_finished": false
  },
  {
    "id": 4,
    "vlr_match_id": "730004",
    "team1": "Team Liquid",
    "team2": "Natus Vincere",
    "team1_score": null,
    "team2_score": null,
    "team1_round_score": null,
    "team2_round_score": null,
    "status": "postponed",
    "start_time": "2026-09-07T12:00:00Z",
    "is_live": false,
    "is_finished": false
  }
]
```

### `GET /api/matches/{match_id}/stats?game_id=all`

Returns persisted map and player statistics for one match. Read-only.

- `game_id` defaults to `"all"`. A specific `game_id` that the match does not have
  returns `404 game_not_found`; it never falls back to another map.
- `maps` lists the `"all"` aggregate first (when the match has any maps), then each
  map in series order. Unplayed maps have `null` round scores.
- Rosters are assigned to `team1`/`team2` by matching VLR's team labels, independent
  of row order. `team_abbreviation` is the label VLR shows beside the player.
- For `"all"`, VLR's own overall table is used when persisted; otherwise per-map
  values are combined. A combined value is `null` if **any** map lacks it, so a
  partial total is never presented as complete.
- `kd` is a ratio, `plus_minus` a signed integer, and `kast` a percentage number
  (`78.0` means 78%).

Examples: [upcoming, no stats](../tests/fixtures/api/match_stats_upcoming.json),
[live aggregate](../tests/fixtures/api/match_stats_live_all.json),
[live map with unpublished stats](../tests/fixtures/api/match_stats_live_map_incomplete.json),
[finished](../tests/fixtures/api/match_stats_finished_all.json).

<!-- example: GET /api/matches/{match_id}/stats 200 -->
```json
{
  "match_info": {
    "match_id": 2,
    "vlr_match_id": "730002",
    "team1": "Team Heretics",
    "team2": "FNATIC",
    "status": "live",
    "map_vetoes": ["TH pick Ascent", "FNC pick Lotus"],
    "selected_game_id": "602",
    "maps": [
      {"game_id": "all", "map_number": null, "map_name": "All Maps", "team1_round_score": null, "team2_round_score": null},
      {"game_id": "602", "map_number": 2, "map_name": "Lotus", "team1_round_score": 7, "team2_round_score": 5},
      {"game_id": "603", "map_number": 3, "map_name": "Split", "team1_round_score": null, "team2_round_score": null}
    ]
  },
  "team1_roster": [
    {
      "name": "Boo",
      "team": "Team Heretics",
      "team_abbreviation": "TH",
      "role": "initiator",
      "acs": 244,
      "kd": 1.75,
      "adr": null,
      "kills": 7,
      "deaths": 4,
      "assists": 0,
      "plus_minus": 3,
      "kast": null,
      "first_kills": null,
      "first_deaths": null
    }
  ],
  "team2_roster": []
}
```

### `POST /api/matches/refresh`

The only endpoint that contacts VLR and writes to the database. Query parameters:
`limit` (1–100, default 50), `details_limit` (0–50, default 12), `results_limit`
(0–200, default 100).

The response is `200` whenever the refresh ran, even if every step failed; check
`status`: `success` (no failures), `partial` (some failures, some data written) or
`failed` (nothing usable). Each entry in `failures` names the `stage` that failed and
an `error` message, plus whatever context is known. Example:
[refresh_partial.json](../tests/fixtures/api/refresh_partial.json).

Only one refresh runs at a time; a concurrent request gets `409 refresh_in_progress`.

<!-- example: POST /api/matches/refresh 200 -->
```json
{
  "status": "partial",
  "matches_examined": 12,
  "inserted": 2,
  "updated": 3,
  "unchanged": 6,
  "details_refreshed": 4,
  "failure_count": 1,
  "failures": [
    {
      "stage": "detail_fetch",
      "error": "429 Too Many Requests",
      "source": null,
      "vlr_match_id": "730002",
      "url": "https://www.vlr.gg/730002",
      "card_index": null,
      "href": null
    }
  ]
}
```

## Errors

Every non-2xx response has the same body. `code` is stable and drives client
behavior; `message` is human-readable and may change.

<!-- example: GET /api/matches/{match_id}/stats 404 -->
```json
{"error": {"code": "match_not_found", "message": "Match 999 was not found"}}
```

| HTTP | `code` | When |
| --- | --- | --- |
| 422 | `validation_error` | A path or query parameter is missing, malformed or out of bounds (for example `limit=101` or `game_id=bad map`). |
| 422 | `invalid_range` | Timeline `start`/`end` lack a UTC offset, `end <= start`, or the range exceeds 31 days. |
| 404 | `match_not_found` | No match has the requested ValScores match ID. |
| 404 | `game_not_found` | The match exists but has no map with the requested `game_id`. |
| 404 | `not_found` | The URL does not name an API route. |
| 405 | `method_not_allowed` | The route exists but not for this method (for example `GET /api/matches/refresh`). |
| 409 | `refresh_in_progress` | Another refresh is running. Retry later. |
| 409 | `ambiguous_roster` | Persisted player rows cannot be assigned to exactly the two match teams. |
| other 4xx | `http_error` | Any other framework-level HTTP error. |
| 500 | `internal_error` | Unexpected server failure. Details are logged, not returned. |

Example bodies: [validation](../tests/fixtures/api/error_validation_error.json),
[range](../tests/fixtures/api/error_invalid_range.json),
[match](../tests/fixtures/api/error_match_not_found.json),
[game](../tests/fixtures/api/error_game_not_found.json),
[refresh conflict](../tests/fixtures/api/error_refresh_in_progress.json).

<!-- example: POST /api/matches/refresh 409 -->
```json
{"error": {"code": "refresh_in_progress", "message": "A match refresh is already in progress"}}
```

<!-- example: GET /api/matches/timeline 422 -->
```json
{"error": {"code": "invalid_range", "message": "timeline range cannot exceed 31 days"}}
```

The Swift client maps codes to `APIErrorCode` (unknown codes become
`.unknown(raw)`), exposed as `APIClientError.serverCode`.

## Client handling

- `MatchStatus` and `APIErrorCode` have an `unknown` case, so a newer backend never
  breaks decoding. Unknown statuses are listed with scheduled matches and labelled
  with the raw value.
- All optional numbers are Swift optionals. `GameCardView`, the match header and
  `PlayerStatRowView` (`PlayerStatFormat`) render `nil` as a dash.
- The timeline lists live matches first, then scheduled (upcoming, postponed,
  unknown), then finished, then cancelled.

## Changes from the previous contract

This contract (overhaul ticket 02) changed both sides together:

| Change | Before | Now |
| --- | --- | --- |
| Statuses | `upcoming`, `live`, `finished`; postponed/cancelled VLR cards were skipped as unparseable | adds `postponed` and `cancelled` |
| Upstream IDs | not exposed | `vlr_match_id` on timeline entries, `match_info`, and (slash-free) refresh failures |
| Stats context | `match_info` had teams only | adds `match_id`, `vlr_match_id`, `status` |
| Timeline round scores | stored value, often a default `0`, for every status | `null` unless `live` |
| `start_time` | nullable | required (matches without one were already excluded) |
| `map_number` | `0` for the aggregate and for unknown numbers | `null` |
| Player stats | unavailable values sent as `0`, `"0"`, `"0%"`; `plus_minus`/`kast` strings; `role` `""` | `null` when unavailable; `plus_minus` integer, `kast` number, `role` nullable |
| Unknown route / 405 | codes `http_404` / `http_405` | `not_found` / `method_not_allowed` |
| Unhandled server errors | plain-text `Internal Server Error` | `500` with `internal_error` envelope |

The scraper and persistence layer now keep missing values as `NULL` instead of
storing zeros. Rows written before this change may still contain zeros that were
originally unknown; they are reported as stored.
