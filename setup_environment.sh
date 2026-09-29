#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
PYTHON="${PYTHON:-python3}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "Creating virtual environment: $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

echo "Installing Python packages..."
"$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

echo "Downloading WordNet corpus..."
if "$VENV_DIR/bin/python" -c "import nltk; nltk.data.find('corpora/wordnet.zip')" >/dev/null 2>&1; then
    echo "WordNet corpus is already available."
else
    "$VENV_DIR/bin/python" -c "import nltk; nltk.download('wordnet', quiet=True, raise_on_error=True)"
fi

echo
echo "Setup complete. Run the converter with:"
echo "  $VENV_DIR/bin/python $PROJECT_DIR/add_inflections.py \"/path/to/dictionary.ifo\" --force"
