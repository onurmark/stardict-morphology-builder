#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import struct
import sys
import tempfile

from lemminflect import getAllInflections


def stardict_sort_key(word):
    """
    StarDict의 stardict_strcmp()와 동일한 정렬을
    영어 ASCII 범위에서 구현한다.

    먼저 case-insensitive 비교,
    같으면 원래 문자열 비교.
    """
    return (word.lower(), word)


def add_alias_candidate(result, ambiguous, form, index):
    """Keep an alias only while all generated candidates agree on its target."""
    key = form.casefold()
    if key in ambiguous:
        return
    existing = result.get(key)
    if existing is None:
        result[key] = (form, index)
    elif existing[1] != index:
        result.pop(key, None)
        ambiguous.add(key)


def read_ifo(path):
    values = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")

            if not line or line.startswith("StarDict's dict ifo file"):
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()

    return values


def read_idx(path, offset_bits=32):
    """
    .idx 파일을 읽는다.

    반환:
        [(word, offset, size), ...]
    """
    entries = []

    offset_size = 8 if offset_bits == 64 else 4
    entry_struct = ">QI" if offset_bits == 64 else ">II"

    with open(path, "rb") as f:
        while True:
            chars = bytearray()

            while True:
                c = f.read(1)

                if not c:
                    if chars:
                        raise RuntimeError(
                            "잘못된 .idx 파일: 마지막 word가 NULL로 끝나지 않았습니다."
                        )
                    return entries

                if c == b"\0":
                    break

                chars.extend(c)

            # Some legacy entries in this dictionary contain malformed UTF-8.
            # Keep their positions in the index; English inflection generation
            # will naturally skip the replacement characters.
            word = chars.decode("utf-8", errors="replace")

            data = f.read(offset_size + 4)

            if len(data) != offset_size + 4:
                raise RuntimeError(
                    f".idx 파일이 잘못되었습니다: {word}"
                )

            offset, size = struct.unpack(entry_struct, data)

            entries.append((word, offset, size))


def read_idx_without_nul_words(path, dict_path, offset_bits, expected_count):
    """Recover record boundaries from contiguous .dict offsets and omit NUL labels."""
    offset_size = 8 if offset_bits == 64 else 4
    entry_size = offset_size + 4
    entry_struct = ">QI" if offset_bits == 64 else ">II"
    idx_data = open(path, "rb").read()
    dict_size = os.path.getsize(dict_path)
    cursor = 0
    expected_offset = 0
    words = []
    clean_records = []
    removed = 0

    for record_number in range(expected_count):
        candidates = []
        search_from = cursor
        while True:
            terminator = idx_data.find(b"\0", search_from)
            if terminator < 0:
                break
            metadata_start = terminator + 1
            metadata_end = metadata_start + entry_size
            if metadata_end <= len(idx_data):
                offset, size = struct.unpack(
                    entry_struct, idx_data[metadata_start:metadata_end]
                )
                if (
                    offset == expected_offset
                    and size <= dict_size - offset
                ):
                    candidates.append((terminator, metadata_end, offset, size))
                    break
            search_from = terminator + 1

        if len(candidates) != 1:
            raise RuntimeError(
                f".idx {record_number + 1}번째 레코드 경계를 유일하게 복원할 수 없습니다."
            )

        terminator, next_cursor, offset, size = candidates[0]
        raw_word = idx_data[cursor:terminator]
        if b"\0" in raw_word:
            removed += 1
        else:
            word = raw_word.decode("utf-8", errors="replace")
            words.append((word, offset, size))
            clean_records.append(idx_data[cursor:next_cursor])

        cursor = next_cursor
        expected_offset = offset + size

    if cursor != len(idx_data):
        raise RuntimeError(
            f".ifo wordcount 이후 .idx에 {len(idx_data) - cursor}바이트가 남습니다."
        )
    if expected_offset != dict_size:
        raise RuntimeError(
            f"복원된 .idx가 .dict 전체를 덮지 않습니다 ({expected_offset}/{dict_size})."
        )

    return words, b"".join(clean_records), removed


def write_syn(path, synonyms):
    """
    StarDict .syn 파일 생성.

    각 entry:
        synonym_word + '\\0' + original_word_index(uint32 BE)
    """

    with open(path, "wb") as f:
        for synonym, original_index in synonyms:
            f.write(synonym.encode("utf-8"))
            f.write(b"\0")
            f.write(struct.pack(">I", original_index))


def read_syn(path, entry_count):
    """Read existing StarDict .syn entries and validate their target indexes."""
    entries = []
    with open(path, "rb") as f:
        while True:
            chars = bytearray()
            while True:
                char = f.read(1)
                if not char:
                    if chars:
                        raise RuntimeError("잘못된 .syn 파일: 마지막 별칭이 NULL로 끝나지 않았습니다.")
                    return entries
                if char == b"\0":
                    break
                chars.extend(char)

            raw_index = f.read(4)
            if len(raw_index) != 4:
                raise RuntimeError("잘못된 .syn 파일: 표제어 인덱스가 잘렸습니다.")
            index = struct.unpack(">I", raw_index)[0]
            if index >= entry_count:
                raise RuntimeError(f"잘못된 .syn 파일: 대상 인덱스 {index}가 범위를 벗어났습니다.")
            entries.append((chars.decode("utf-8", errors="replace"), index))


def write_text(path, content):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def write_bytes(path, content):
    with open(path, "wb") as f:
        f.write(content)


def updated_ifo_text(path, syn_count, updates=None):
    """Return .ifo contents with updated synonym and optional index counts."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    replacements = dict(updates or {})
    replacements["synwordcount"] = syn_count
    output = []

    for line in lines:
        key, separator, _ = line.partition("=")
        if separator and key in replacements:
            output.append(f"{key}={replacements.pop(key)}\n")
        else:
            output.append(line)

    if replacements:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        output.extend(f"{key}={value}\n" for key, value in replacements.items())

    return "".join(output)


def generate_inflections(words, explicit_lemmas=None):
    """
    사전의 lemma 각각에 대해 LemmInflect로
    가능한 영어 활용형을 생성한다.

    반환:
        [(inflected_word, original_index), ...]
    """

    # 정확한 단어 → idx index
    word_to_index = {
        word: index
        for index, (word, _, _) in enumerate(words)
    }

    # 대소문자 무시 lookup
    lower_to_index = {}

    for index, (word, _, _) in enumerate(words):
        lower_to_index.setdefault(word.lower(), index)

    result = {}
    ambiguous = set()

    # Explicit mappings are applied only when the user supplies a map.
    explicit_lemmas = explicit_lemmas or {}

    total = len(words)

    for index, (lemma, _, _) in enumerate(words):
        if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", lemma):
            continue

        # 너무 짧거나 이상한 항목은 제외
        if len(lemma) < 2:
            continue

        try:
            forms = getAllInflections(lemma)
        except Exception as e:
            print(
                f"warning: {lemma}: {e}",
                file=sys.stderr,
            )
            continue

        for pos, form_list in forms.items():
            for form in form_list:
                if not form:
                    continue

                # 원형 자체는 synonym으로 만들 필요 없음
                if form == lemma:
                    continue

                # 영어 단어만
                if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", form):
                    continue

                # 이미 사전에 정확한 표제어로 존재하면
                # 기존 의미를 우선한다.
                #
                # 예:
                # saw가 이미 사전에 있다면
                # see -> saw 를 synonym으로 추가하지 않는다.
                if form.lower() in lower_to_index:
                    continue

                add_alias_candidate(result, ambiguous, form, index)

        # English possessive form (lemminflect does not emit possessives).
        if "NN" in forms or "NNS" in forms:
            possessive = lemma + ("'" if lemma.lower().endswith("s") else "'s")
            if possessive.lower() not in lower_to_index:
                add_alias_candidate(result, ambiguous, possessive, index)

        if (index + 1) % 10000 == 0:
            print(
                f"processed {index + 1:,} / {total:,}",
                file=sys.stderr,
            )

    # Apply explicit lemma choices after generated forms so collisions cannot
    # redirect these forms to a different dictionary entry.
    index_by_lower = {word.lower(): i for i, (word, _, _) in enumerate(words)}
    applied = 0
    skipped = []
    for form, lemma in explicit_lemmas.items():
        if lemma.lower() not in index_by_lower:
            skipped.append(f"{form} -> {lemma}")
            continue
        ambiguous.discard(form.lower())
        result[form.lower()] = (form, index_by_lower[lemma.lower()])
        applied += 1

    if skipped:
        print(
            "Skipped explicit lemma mappings whose targets are absent: "
            + ", ".join(skipped),
            file=sys.stderr,
        )
    if applied:
        print(f"Applied explicit lemma mappings: {applied:,}")
    if ambiguous:
        print(
            f"Omitted ambiguous inflection aliases: {len(ambiguous):,}",
            file=sys.stderr,
        )

    synonyms = [
        (form, index)
        for form, index in result.values()
    ]

    synonyms.sort(
        key=lambda x: stardict_sort_key(x[0])
    )

    return synonyms


def generate_multiword_verb_inflections(words, synonyms):
    """Generate aliases by inflecting the verb at the start of dictionary phrases."""
    from nltk.corpus import wordnet as wn

    particles = {
        "about", "across", "after", "along", "apart", "around", "aside",
        "at", "away", "back", "by", "down", "for", "forth", "forward", "from", "in",
        "into", "off", "on", "onto", "out", "over", "through", "to",
        "together", "under", "up", "upon", "with",
    }
    exact_headwords = {word.casefold() for word, _, _ in words}
    result = {form.casefold(): (form, index) for form, index in synonyms}
    ambiguous = set()
    added = 0

    for index, (phrase, _, _) in enumerate(words):
        parts = phrase.split()
        if len(parts) < 2 or not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", parts[0]):
            continue
        # Handle both verb + particle ("get to know") and verb + object +
        # preposition ("abandon oneself to something"). Only inflect the
        # initial verb; object and particle positions stay fixed.
        second = parts[1].casefold()
        has_particle_after_object = (
            second in {"someone", "somebody", "something", "oneself", "yourself",
                       "himself", "herself", "itself", "themselves"}
            and any(part.casefold() in particles for part in parts[2:])
        )
        if second not in particles and not has_particle_after_object:
            continue
        if not wn.synsets(parts[0].replace("'", ""), pos=wn.VERB):
            continue

        try:
            forms = getAllInflections(parts[0])
        except Exception:
            continue

        for tag in ("VBD", "VBN", "VBG", "VBZ"):
            for form in forms.get(tag, ()):
                if form.casefold() == parts[0].casefold():
                    continue
                variant = " ".join((form, *parts[1:]))
                key = variant.casefold()
                if key in exact_headwords or key in ambiguous:
                    continue
                was_present = key in result
                add_alias_candidate(result, ambiguous, variant, index)
                if not was_present and key in result:
                    added += 1

    output = list(result.values())
    output.sort(key=lambda item: stardict_sort_key(item[0]))
    print(f"Added multiword verb aliases: {added:,}")
    if ambiguous:
        print(f"Omitted ambiguous multiword verb aliases: {len(ambiguous):,}", file=sys.stderr)
    return output


def generate_noun_phrase_inflections(words, synonyms):
    """Add plural aliases for clear determiner-led noun phrases.

    The head is selected as the rightmost WordNet noun before a prepositional
    phrase, or the rightmost noun in a simple compound. Indefinite articles
    are dropped in the plural ("a bad apple" -> "bad apples").
    """
    from nltk.corpus import wordnet as wn

    determiners = {"a", "an", "the", "this", "that", "these", "those"}
    prepositions = {
        "about", "across", "after", "against", "along", "among", "around",
        "at", "before", "behind", "below", "beneath", "beside", "between",
        "beyond", "by", "despite", "during", "for", "from", "in", "into",
        "near", "of", "off", "on", "onto", "out", "over", "through",
        "to", "under", "up", "upon", "with", "within", "without",
    }
    exact_headwords = {word.casefold() for word, _, _ in words}
    result = {form.casefold(): (form, index) for form, index in synonyms}
    ambiguous = set()
    added = 0

    def plural_forms(noun):
        forms = getAllInflections(noun).get("NNS", ())
        if forms:
            return forms

        # LemmInflect does not list every regular dictionary noun (for
        # example, "boomer"). Use a regular fallback only after WordNet has
        # confirmed the token is a noun.
        lower = noun.casefold()
        if re.search(r"[^aeiou]y$", lower):
            return (noun[:-1] + "ies",)
        if lower.endswith(("s", "x", "z", "ch", "sh")):
            return (noun + "es",)
        if lower in {"sheep", "deer", "fish", "species", "series"}:
            return ()
        return (noun + "s",)

    for index, (phrase, _, _) in enumerate(words):
        parts = phrase.split()
        if len(parts) < 2 or parts[0].casefold() not in determiners:
            continue

        # A/an is only valid for singulars. "the" and demonstratives remain.
        body_start = 1
        prep_pos = next(
            (i for i in range(body_start + 1, len(parts))
             if parts[i].casefold() in prepositions),
            len(parts),
        )
        head_candidates = [
            i for i in range(body_start, prep_pos)
            if re.fullmatch(r"[A-Za-z][A-Za-z'-]*", parts[i])
            and wn.synsets(parts[i].replace("'", ""), pos=wn.NOUN)
            and plural_forms(parts[i])
        ]
        if not head_candidates:
            continue

        head_pos = head_candidates[-1]
        plurals = plural_forms(parts[head_pos])
        for plural in plurals:
            if plural.casefold() == parts[head_pos].casefold():
                continue
            plural_parts = list(parts)
            plural_parts[head_pos] = plural
            if parts[0].casefold() in {"a", "an"}:
                del plural_parts[0]
            elif parts[0].casefold() in {"this", "that"}:
                plural_parts[0] = "these" if parts[0].casefold() == "this" else "those"
            variant = " ".join(plural_parts)
            key = variant.casefold()
            if key in exact_headwords or key in ambiguous:
                continue
            was_present = key in result
            add_alias_candidate(result, ambiguous, variant, index)
            if not was_present and key in result:
                added += 1

    output = list(result.values())
    output.sort(key=lambda item: stardict_sort_key(item[0]))
    print(f"Added noun phrase plural aliases: {added:,}")
    if ambiguous:
        print(f"Omitted ambiguous noun phrase aliases: {len(ambiguous):,}", file=sys.stderr)
    return output


def add_wordnet_derivations(words, synonyms):
    """Add unambiguous WordNet derivational/pertainym aliases.

    WordNet relations can connect one spelling to several lemmas. To avoid
    arbitrary redirects, only aliases with exactly one target present in the
    dictionary are added. Existing dictionary headwords are left to their
    direct index entry.
    """
    try:
        from nltk.corpus import wordnet as wn

        # Force corpus loading here so the error is clear if it is not installed.
        wn.synsets("perpetual")
    except (ImportError, LookupError) as exc:
        raise RuntimeError(
            "WordNet support requires NLTK and its WordNet corpus. Install NLTK "
            "and run `python -m nltk.downloader wordnet`."
        ) from exc

    lemma_to_index = {}
    for index, (word, _, _) in enumerate(words):
        lemma_to_index.setdefault(word.casefold(), index)

    indexed_headwords = set(lemma_to_index)
    candidates = {}

    for synset in wn.all_synsets():
        for lemma in synset.lemmas():
            related = list(lemma.derivationally_related_forms())
            # WordNet records adverbs such as "perpetually" as pertaining to
            # their source adjective, a useful relation not always exposed as
            # a derivationally-related-form pointer.
            related.extend(lemma.pertainyms())

            source = lemma.name().replace("_", " ").casefold()
            if source not in indexed_headwords and re.fullmatch(
                r"[a-z][a-z'-]*", source
            ):
                for target_lemma in related:
                    target = target_lemma.name().replace("_", " ").casefold()
                    if target in indexed_headwords:
                        candidates.setdefault(source, set()).add(target)

    by_lower = {form.casefold(): (form, index) for form, index in synonyms}
    added = 0
    for source, targets in candidates.items():
        if len(targets) != 1:
            continue
        target = next(iter(targets))
        # Preserve inflection mappings and direct dictionary headwords.
        if source in by_lower or source in indexed_headwords:
            continue
        source_display = source
        by_lower[source] = (source_display, lemma_to_index[target])
        added += 1

    result = list(by_lower.values())
    result.sort(key=lambda item: stardict_sort_key(item[0]))
    print(f"Added WordNet derivation aliases: {added:,}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Add English inflection aliases to a StarDict dictionary."
    )

    parser.add_argument(
        "ifo",
        help="StarDict .ifo file"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing .syn"
    )
    parser.add_argument(
        "--no-wordnet",
        action="store_true",
        help="skip WordNet derivational aliases"
    )
    parser.add_argument(
        "--lemma-map",
        metavar="JSON",
        help="JSON file of explicit form-to-lemma mappings; omitted by default",
    )
    parser.add_argument(
        "--merge-existing-syn",
        action="store_true",
        help="keep existing .syn entries unless a generated alias uses the same spelling",
    )
    parser.add_argument(
        "--drop-nul-idx-entries",
        action="store_true",
        help="remove .idx records whose headword contains an embedded NUL and rebuild indexes",
    )

    args = parser.parse_args()

    ifo_path = os.path.abspath(args.ifo)

    if not ifo_path.endswith(".ifo"):
        raise SystemExit("error: .ifo 파일을 지정하세요.")

    base = ifo_path[:-4]

    idx_path = base + ".idx"
    dict_path = base + ".dict"
    syn_path = base + ".syn"

    if not os.path.exists(idx_path):
        raise SystemExit(
            f"error: .idx 파일이 없습니다: {idx_path}"
        )

    if os.path.exists(syn_path) and not args.force:
        raise SystemExit(
            f"error: 이미 존재합니다: {syn_path}\n"
            "덮어쓰려면 --force를 사용하세요."
        )

    ifo = read_ifo(ifo_path)

    offset_bits = int(ifo.get("idxoffsetbits", "32"))

    if offset_bits not in (32, 64):
        raise SystemExit(
            f"error: 지원하지 않는 idxoffsetbits={offset_bits}"
        )

    try:
        expected_count = int(ifo["wordcount"])
    except (KeyError, ValueError) as exc:
        raise SystemExit("error: .ifo에 유효한 wordcount가 없습니다.") from exc

    if args.drop_nul_idx_entries and args.merge_existing_syn:
        raise SystemExit(
            "error: --drop-nul-idx-entries와 --merge-existing-syn은 함께 사용할 수 없습니다. "
            "기존 .syn의 대상 번호가 변경될 수 있습니다."
        )

    print(f"Reading: {idx_path}")
    print(f"idxoffsetbits: {offset_bits}")

    repaired_idx_data = None
    if args.drop_nul_idx_entries:
        try:
            words, repaired_idx_data, removed_nul_entries = read_idx_without_nul_words(
                idx_path, dict_path, offset_bits, expected_count
            )
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"error: NUL 포함 .idx 레코드 복원 실패: {exc}") from exc
        print(f"Removed NUL-containing .idx records: {removed_nul_entries:,}")
    else:
        words = read_idx(idx_path, offset_bits)

    explicit_lemmas = {}
    if args.lemma_map:
        try:
            with open(args.lemma_map, "r", encoding="utf-8") as f:
                explicit_lemmas = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"error: lemma map could not be read: {exc}") from exc
        if not isinstance(explicit_lemmas, dict) or not all(
            isinstance(form, str) and isinstance(lemma, str)
            for form, lemma in explicit_lemmas.items()
        ):
            raise SystemExit("error: lemma map must be a JSON object of strings")

    print(f"Dictionary entries: {len(words):,}")
    print("Generating English inflections...")

    synonyms = generate_inflections(words, explicit_lemmas)
    synonyms = generate_multiword_verb_inflections(words, synonyms)
    synonyms = generate_noun_phrase_inflections(words, synonyms)

    if not args.no_wordnet:
        synonyms = add_wordnet_derivations(words, synonyms)

    print(f"Generated aliases: {len(synonyms):,}")

    if os.path.exists(syn_path) and args.merge_existing_syn:
        old_synonyms = read_syn(syn_path, len(words))
        merged = {form.casefold(): (form, index) for form, index in old_synonyms}
        merged.update({form.casefold(): (form, index) for form, index in synonyms})
        synonyms = sorted(merged.values(), key=lambda item: stardict_sort_key(item[0]))
        print(f"Preserved/merged existing .syn aliases: {len(old_synonyms):,}")

    # Stage both files before replacing either. Back up the exact current files
    # on every run so a backup never silently remains stale.
    staged = []
    try:
        ifo_updates = {}
        targets = []
        if repaired_idx_data is not None:
            targets.append((idx_path, lambda path: write_bytes(path, repaired_idx_data)))
            ifo_updates["wordcount"] = len(words)
            ifo_updates["idxfilesize"] = len(repaired_idx_data)
        targets.extend((
            (syn_path, lambda path: write_syn(path, synonyms)),
            (ifo_path, lambda path: write_text(
                path, updated_ifo_text(ifo_path, len(synonyms), ifo_updates)
            )),
        ))

        for target, writer in targets:
            fd, temp_path = tempfile.mkstemp(prefix=".morphology-", dir=os.path.dirname(target))
            os.close(fd)
            staged.append((target, temp_path))
            writer(temp_path)
            mode = os.stat(target).st_mode & 0o777 if os.path.exists(target) else 0o644
            os.chmod(temp_path, mode)

        original_targets = {target for target, _ in staged if os.path.exists(target)}
        for target, _ in staged:
            if os.path.exists(target):
                backup = target + ".bak"
                print(f"Backup: {backup}")
                shutil.copy2(target, backup)

        replaced = []
        try:
            for target, temp_path in staged:
                os.replace(temp_path, target)
                replaced.append(target)
        except OSError:
            # Best-effort rollback from the freshly created backups.
            for target in reversed(replaced):
                backup = target + ".bak"
                if target in original_targets:
                    shutil.copy2(backup, target)
                else:
                    os.unlink(target)
            raise
    finally:
        for _, temp_path in staged:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    print()
    print("Done.")
    print(f"  .syn : {syn_path}")
    print(f"  aliases: {len(synonyms):,}")
    print()
    if repaired_idx_data is None:
        print("Original .idx and .dict were not modified.")
    else:
        print("NUL-containing .idx records were removed; .dict data was left unchanged.")


if __name__ == "__main__":
    main()
