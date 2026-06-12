#!/usr/bin/env bash
#
# Bumps the patch version in packages/giulia/pyproject.toml when package
# source files are staged. Called by pre-commit; exits 0 (no-op) if no
# relevant files are staged.
#
set -euo pipefail

TOML="packages/giulia/pyproject.toml"

STAGED_FILES=$(git diff --cached --name-only -- 'packages/giulia/giulia/' | grep -v '^packages/giulia/pyproject\.toml$' || true)

if [ -z "$STAGED_FILES" ]; then
    exit 0
fi

CURRENT=$(grep '^version' "$TOML" | sed 's/.*"\(.*\)"/\1/')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"

sed -i.bak "s/^version = \".*\"/version = \"${NEW_VERSION}\"/" "$TOML"
rm -f "${TOML}.bak"

git add "$TOML"

echo "giulia: bumped $CURRENT → $NEW_VERSION"
