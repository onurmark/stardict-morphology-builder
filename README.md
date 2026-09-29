# StarDict inflection and WordNet aliases

## Set up Python

Run this once from the project directory:

```bash
./setup_environment.sh
```

The script creates `venv/` if needed, installs the pinned Python dependencies,
and downloads the NLTK WordNet corpus. It can be run again to repair or refresh
the setup. Override the interpreter or environment path with `PYTHON` or
`VENV_DIR` if needed.

## Update a StarDict dictionary

The dictionary's `.ifo`, `.idx`, and `.dict` files must share the same base
name. Run:

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force
```

This regenerates `.syn` with English inflections and unambiguous WordNet
derivational aliases, and updates `synwordcount` in `.ifo`. Existing `.syn`
and `.ifo` files are backed up as `.bak` files. Use `--no-wordnet` to generate
inflection aliases only.
