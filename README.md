# StarDict inflection and WordNet aliases

## 한국어 안내

이 도구는 StarDict 사전에 영어 활용형, 일부 동사구·명사구 변형, WordNet 파생형을 검색 별칭으로 추가합니다. `.syn`을 만들고 `.ifo`의 `synwordcount`를 갱신합니다.

### Python 환경 설정

프로젝트 디렉토리에서 아래 명령을 한 번 실행하세요.

```bash
./setup_environment.sh
```

필요하면 `venv/`를 만들고 `requirements.txt`에 고정된 Python 패키지를 설치한 다음, NLTK WordNet 코퍼스를 준비합니다. 다시 실행해도 환경을 점검하고 필요한 구성 요소를 설치할 수 있습니다.

Python 인터프리터나 가상환경 경로를 바꾸려면 `PYTHON` 또는 `VENV_DIR` 환경 변수를 지정하세요.

### StarDict 사전 갱신

사전의 `.ifo`, `.idx`, `.dict` 파일은 같은 기본 이름을 사용해야 합니다. 다음처럼 `.ifo` 파일을 지정해 실행합니다.

```bash
venv/bin/python add_inflections.py "/경로/사전.ifo" --force
```

기본 동작은 `.syn`을 새로 생성해 기존 파일을 교체하는 것입니다. 기존 `.syn`이 있으면 `--merge-existing-syn`으로 수동 별칭을 보존할 수 있으며, 같은 철자의 새 생성 별칭은 새 결과가 우선합니다. 교체되는 `.syn`과 `.ifo`는 실행할 때마다 현재 상태를 `.bak` 파일에 백업합니다. WordNet 파생형 없이 활용형만 만들려면 `--no-wordnet` 옵션을 추가하세요. 기존 구 표제어를 보존하면서 동사구의 첫 동사 활용형(예: `get to know`, `abandon oneself to something`)과 명사구의 복수형(예: `a bad apple` → `bad apples`)도 별칭으로 생성합니다.

코드에 들어 있던 특수 매핑은 [`lemma-map.json`](lemma-map.json)으로 분리했습니다. 이 파일은 예시/설정 파일이며, 명령에 `--lemma-map`으로 지정하지 않으면 적용되지 않습니다. 사전마다 필요한 매핑만 남기거나 수정해 사용하세요. JSON은 표면형을 기본형에 연결하는 객체입니다.

```json
{
  "went": "go",
  "better": "good"
}
```

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force --lemma-map lemma-map.json
```

지정한 매핑의 대상 기본형이 현재 사전에 없으면 변환을 중단하지 않고 해당 매핑을 경고와 함께 건너뜁니다. 매핑을 지정하지 않으면 특수 매핑은 하나도 적용하지 않습니다. 자동 생성 과정에서 하나의 형태가 서로 다른 기본형 후보에 연결되면 임의로 하나를 고르지 않고 그 별칭을 제외합니다. 꼭 연결해야 하는 경우 `--lemma-map`으로 명시할 수 있습니다.

기본적으로 `.idx`는 수정하지 않습니다. NUL 문자가 표제어 안에 들어간 레코드를 색인에서 제거하려면 `--drop-nul-idx-entries`를 명시하세요. 이 옵션은 `.dict` 오프셋을 이용해 레코드 경계를 검증하고, 해당 `.idx` 레코드를 제거한 뒤 `.ifo`의 `wordcount`와 `idxfilesize` 및 새 `.syn`을 함께 갱신합니다. 제거된 표제어의 정의는 색인에서 접근할 수 없게 됩니다. 갱신 전 `.idx`, `.ifo`, `.syn`은 `.bak`으로 백업하며, 경계를 안전하게 복원할 수 없으면 파일을 변경하지 않고 중단합니다. 이 옵션과 `--merge-existing-syn`은 함께 쓸 수 없습니다.

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force --drop-nul-idx-entries
```

## Set up Python

From the project directory, run:

```bash
./setup_environment.sh
```

The script creates `venv/` if needed, installs the Python packages pinned in
`requirements.txt`, and downloads the NLTK WordNet corpus. You can run it again
to check and repair the environment. Set `PYTHON` to choose the interpreter
used to create the virtual environment, or `VENV_DIR` to choose its path.

## Update a StarDict dictionary

The dictionary's `.ifo`, `.idx`, and `.dict` files must share the same base
name. Pass the `.ifo` path to the script:

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force
```

This generates English inflection aliases, selected multiword verb forms
(such as `get to know` and `abandon oneself to something`), plural forms of
some determiner-led noun phrases (such as `a bad apple` → `bad apples`), and
unambiguous WordNet derivational aliases. It then updates `synwordcount` in
`.ifo`.

By default, the script replaces an existing `.syn` file. Use
`--merge-existing-syn` to keep its aliases; if a generated alias has the same
spelling, the newly generated entry takes precedence. The current `.syn` and
`.ifo` are backed up to their `.bak` paths on every run. Add `--no-wordnet` to
skip WordNet derivational aliases.

Dictionary-specific form-to-lemma mappings are stored in
[`lemma-map.json`](lemma-map.json). This file is an example/configuration file
and is **not applied unless explicitly passed** with `--lemma-map`:

```json
{
  "went": "go",
  "better": "good"
}
```

Edit the file to keep only mappings appropriate for your dictionary, then run:

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force --lemma-map lemma-map.json
```

Mappings whose target lemmas are absent from the dictionary are skipped with a
warning. Without `--lemma-map`, no explicit mappings are applied. If automatic
morphology finds that a spelling could point to multiple lemmas, it omits that
alias instead of choosing a target based on dictionary order. Add an explicit
mapping when you want to resolve such a case.

By default, the script does not modify `.idx`. To remove index records whose
headword contains an embedded NUL, explicitly pass
`--drop-nul-idx-entries`. The script validates record boundaries using the
`.dict` offsets, removes those `.idx` records, and updates `.ifo`'s `wordcount`
and `idxfilesize` along with the newly generated `.syn`. Definitions whose
records were removed remain in `.dict` but are no longer reachable through the
index. Original `.idx`, `.ifo`, and `.syn` files are backed up to `.bak`; if
record boundaries cannot be reconstructed safely, no files are changed. This
option cannot be combined with `--merge-existing-syn`.

```bash
venv/bin/python add_inflections.py "/path/to/dictionary.ifo" --force --drop-nul-idx-entries
```
