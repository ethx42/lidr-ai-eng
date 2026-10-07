#!/usr/bin/env bash
# Branch close gate: bash scripts/gate.sh <branch>. Stops at the first failing stage.
set -euo pipefail
branch="${1:?usage: gate.sh <branch>}"
stage() { echo "==> $*"; }

stage "make check"
make check

stage "docker compose e2e"
docker compose up --build --wait
trap 'docker compose down' EXIT
make e2e
docker compose down
trap - EXIT

stage "openapi contract is current"
make openapi
git diff --exit-code contracts/openapi.json

stage "PROGRESS.md section '$branch' has no open or blocked tasks"
section=$(awk -v h="## $branch" '$0 == h {on=1; next} /^## / {on=0} on' docs/catch-up/PROGRESS.md)
[ -n "$section" ] || { echo "no section '## $branch' in PROGRESS.md" >&2; exit 1; }
if grep -nE '\[( |!)\]' <<<"$section"; then
  echo "open or blocked tasks remain" >&2
  exit 1
fi

stage "branch pushed"
git fetch origin "$branch"
sha=$(git rev-parse HEAD)
[ "$sha" = "$(git rev-parse "origin/$branch")" ] || { echo "HEAD differs from origin/$branch" >&2; exit 1; }

echo "GATE PASS $branch $sha"
