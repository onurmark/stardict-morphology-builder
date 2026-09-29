#!/usr/bin/env python3

import argparse
import os
import re
import shutil
import struct
import sys

from lemminflect import getAllInflections


def stardict_sort_key(word):
    """
    StarDict의 stardict_strcmp()와 동일한 정렬을
    영어 ASCII 범위에서 구현한다.

    먼저 case-insensitive 비교,
    같으면 원래 문자열 비교.
    """
    return (word.lower(), word)


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


def update_ifo(path, syn_count):
    """
    .ifo에 synwordcount를 추가/수정한다.
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = False
    output = []

    for line in lines:
        if line.startswith("synwordcount="):
            output.append(f"synwordcount={syn_count}\n")
            found = True
        else:
            output.append(line)

    if not found:
        # 일반적으로 마지막에 추가해도 된다.
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"

        output.append(f"synwordcount={syn_count}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(output)


def generate_inflections(words):
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

    # Resolve these common, unambiguous forms to their requested lemmas even
    # when the inflected spelling is also present as a separate headword.
    preferred_lemmas = {
        "precautions": "precaution",
        "precaution's": "precaution",
        "studies": "study",
        "studied": "study",
        "studying": "study",
        "protected": "protect",
        "protecting": "protect",
        "children": "child",
        "men": "man",
        "went": "go",
    }

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

                key = form.lower()

                # 동일한 inflection이 여러 lemma에서 발생하면
                # 첫 번째 것만 사용한다.
                if key not in result:
                    result[key] = (form, index)

        # English possessive form (lemminflect does not emit possessives).
        if "NN" in forms or "NNS" in forms:
            possessive = lemma + ("'" if lemma.lower().endswith("s") else "'s")
            if possessive.lower() not in lower_to_index:
                result.setdefault(possessive.lower(), (possessive, index))

        if (index + 1) % 10000 == 0:
            print(
                f"processed {index + 1:,} / {total:,}",
                file=sys.stderr,
            )

    # Apply explicit lemma choices after generated forms so collisions cannot
    # redirect these forms to a different dictionary entry.
    index_by_lower = {word.lower(): i for i, (word, _, _) in enumerate(words)}
    for form, lemma in preferred_lemmas.items():
        if lemma.lower() not in index_by_lower:
            raise RuntimeError(f"required lemma is missing from dictionary: {lemma}")
        result[form.lower()] = (form, index_by_lower[lemma.lower()])

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
                if key in exact_headwords or key in result:
                    continue
                result[key] = (variant, index)
                added += 1

    output = list(result.values())
    output.sort(key=lambda item: stardict_sort_key(item[0]))
    print(f"Added multiword verb aliases: {added:,}")
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
            if key in exact_headwords or key in result:
                continue
            result[key] = (variant, index)
            added += 1

    output = list(result.values())
    output.sort(key=lambda item: stardict_sort_key(item[0]))
    print(f"Added noun phrase plural aliases: {added:,}")
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

    args = parser.parse_args()

    ifo_path = os.path.abspath(args.ifo)

    if not ifo_path.endswith(".ifo"):
        raise SystemExit("error: .ifo 파일을 지정하세요.")

    base = ifo_path[:-4]

    idx_path = base + ".idx"
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

    print(f"Reading: {idx_path}")
    print(f"idxoffsetbits: {offset_bits}")

    words = read_idx(idx_path, offset_bits)

    print(f"Dictionary entries: {len(words):,}")
    print("Generating English inflections...")

    synonyms = generate_inflections(words)
    synonyms = generate_multiword_verb_inflections(words, synonyms)
    synonyms = generate_noun_phrase_inflections(words, synonyms)

    if not args.no_wordnet:
        synonyms = add_wordnet_derivations(words, synonyms)

    print(f"Generated aliases: {len(synonyms):,}")

    # 기존 .syn이 있다면 백업
    if os.path.exists(syn_path):
        backup = syn_path + ".bak"

        print(f"Backup: {backup}")
        shutil.copy2(syn_path, backup)

    write_syn(syn_path, synonyms)

    # .ifo 백업
    ifo_backup = ifo_path + ".bak"

    if not os.path.exists(ifo_backup):
        print(f"Backup: {ifo_backup}")
        shutil.copy2(ifo_path, ifo_backup)

    update_ifo(ifo_path, len(synonyms))

    print()
    print("Done.")
    print(f"  .syn : {syn_path}")
    print(f"  aliases: {len(synonyms):,}")
    print()
    print("Original .idx and .dict were not modified.")


if __name__ == "__main__":
    main()
