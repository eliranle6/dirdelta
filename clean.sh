#!/bin/bash
set -e
cd "$(dirname "$0")"

for repo in . lib/treepicker; do
    echo "=== $repo ==="
    find "$repo" -name '__pycache__' -type d -prune -exec rm -rf {} +
    find "$repo" -name '*.pyc' -delete
    find "$repo" -maxdepth 1 -name '*.egg-info' -type d -prune -exec rm -rf {} +
    rm -rf "$repo/build" "$repo/AUTHORS" "$repo/ChangeLog"
done
