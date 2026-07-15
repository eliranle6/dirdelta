ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PYTHONPATH="$ROOT/lib/treepicker" \
           python3 "$ROOT/dirdelta/main.py" cloud/mein
