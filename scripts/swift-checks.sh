#!/usr/bin/env bash
# Compile and run the portable Swift regression executables in tests/ValScores*Tests.
# They exercise shared app code without Xcode, the simulator or a backend.
set -euo pipefail

cd "$(dirname "$0")/.."
out="${SWIFT_CHECKS_OUT:-${TMPDIR:-/tmp}/valscores-swift-checks}"
mkdir -p "$out"

models=(
  ValScores/Shared/Models/MatchInfo.swift
  ValScores/Shared/Time/MatchTimeContract.swift
)
networking=(
  "${models[@]}"
  ValScores/Shared/Models/MatchStats.swift
  ValScores/Shared/Models/RefreshResponse.swift
  ValScores/Shared/Networking/APIError.swift
  ValScores/Shared/Networking/APIClient.swift
)

run() {
  local name="$1"
  shift
  swiftc -parse-as-library "$@" -o "$out/$name"
  "$out/$name"
}

run time-contract "${models[@]}" tests/ValScoresTimeContractTests/MatchTimeContractTests.swift
run api-client "${networking[@]}" tests/ValScoresAPIClientTests/APIClientTests.swift
run timeline-state "${networking[@]}" ValScores/Features/Timeline/VLRDataManager.swift \
  tests/ValScoresTimelineStateTests/TimelineStateTests.swift
run match-detail "${networking[@]}" ValScores/Features/MatchDetail/MatchDetailState.swift \
  tests/ValScoresMatchDetailTests/MatchDetailStateTests.swift
