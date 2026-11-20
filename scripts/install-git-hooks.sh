#!/usr/bin/env bash
# Install OracleForge's local git hooks into this clone's .git/hooks.
# Run from anywhere in the repo:  bash scripts/install-git-hooks.sh
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
src="$root/scripts/git-hooks"
dst="$(git rev-parse --git-path hooks)"

mkdir -p "$dst"
for hook in "$src"/*; do
  name="$(basename "$hook")"
  cp "$hook" "$dst/$name"
  chmod +x "$dst/$name"
  echo "installed $name -> $dst/$name"
done
echo "done. (local-only; see STATUS.md on server-side protection)"
