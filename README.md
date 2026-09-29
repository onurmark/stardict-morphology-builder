# StarDict inflection and WordNet aliases

## 한국어 안내

이 도구는 StarDict 사전에 영어 활용형, 일부 동사구·명사구 변형, WordNet 파생형을 검색 별칭으로 추가합니다. `.syn`을 만들고 `.ifo`의 `synwordcount`를 갱신합니다.

### Python 환경 설정

프로젝트 디렉토리에서 아래 명령을 한 번 실행하세요.

```bash
./setup_environment.sh
```

필요하면 `venv/`를 만들고 `requirements.txt`에 고정된 Python 패키지를 설치한 다음, NLTK WordNet 코퍼스를 준비합니다. 이미 환경이 준비되어 있으면 설치와 다운로드를 건너뛰므로 다시 실행해도 됩니다.

Python 인터프리터나 가상환경 경로를 바꾸려면 `PYTHON` 또는 `VENV_DIR` 환경 변수를 지정하세요.

### StarDict 사전 갱신

사전의 `.ifo`, `.idx`, `.dict` 파일은 같은 기본 이름을 사용해야 합니다. 다음처럼 `.ifo` 파일을 지정해 실행합니다.

```bash
venv/bin/python add_inflections.py "/경로/사전.ifo" --force
```

기존 `.syn`을 덮어쓰며, 원본 `.syn`과 `.ifo`는 각각 `.bak` 파일로 백업합니다. WordNet 파생형 없이 활용형만 만들려면 `--no-wordnet` 옵션을 추가하세요. 기존 구 표제어를 보존하면서 동사구의 첫 동사 활용형(예: `get to know`, `abandon oneself to something`)과 명사구의 복수형(예: `a bad apple` → `bad apples`)도 별칭으로 생성합니다.

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

This regenerates `.syn` with English inflections, selected multiword verb and
noun phrase forms, and unambiguous WordNet derivational aliases, and updates
`synwordcount` in `.ifo`. Existing `.syn` and `.ifo` files are backed up as
`.bak` files. Use `--no-wordnet` to omit WordNet derivational aliases.
