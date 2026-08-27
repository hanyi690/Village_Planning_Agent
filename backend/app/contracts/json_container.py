"""Fail-closed decoding for JSON containers nested in provider arguments."""

from __future__ import annotations

import json
from typing import Any


def _repair_unescaped_quotes(value: str) -> str:
    """Escape only quotes that cannot be JSON string delimiters."""

    chars: list[str] = []
    in_string = False
    escaped = False
    length = len(value)
    for index, char in enumerate(value):
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            chars.append(char)
            escaped = True
            continue
        if char != '"':
            chars.append(char)
            continue
        if not in_string:
            in_string = True
            chars.append(char)
            continue

        next_index = index + 1
        while next_index < length and value[next_index].isspace():
            next_index += 1
        next_char = value[next_index] if next_index < length else ""
        if next_char in {",", "]", "}", ":", ""}:
            in_string = False
            chars.append(char)
        else:
            chars.extend(("\\", '"'))
    return "".join(chars)


def _repair_unquoted_keys(value: str) -> str:
    """Quote bare object keys without interpreting arbitrary expressions."""

    chars: list[str] = []
    index = 0
    length = len(value)
    in_string = False
    escaped = False
    while index < length:
        char = value[index]
        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue
        chars.append(char)
        if char not in "{,":
            index += 1
            continue

        probe = index + 1
        while probe < length and value[probe].isspace():
            probe += 1
        if probe >= length or value[probe] in '"}':
            index += 1
            continue
        key_end = probe
        while key_end < length and value[key_end] not in ":,{}[]\"\r\n\t ":
            key_end += 1
        if key_end == probe or key_end >= length or value[key_end] != ":":
            index += 1
            continue
        token = value[probe:key_end]
        chars.extend(value[index + 1:probe])
        chars.extend(('"', token.replace('"', '\\"'), '"'))
        chars.append(":")
        index = key_end + 1
    return "".join(chars)


def _repair_json_literals(value: str) -> str:
    """Translate JSON-like scalar spellings only while outside strings."""

    replacements = {"None": "null", "True": "true", "False": "false"}
    chars: list[str] = []
    index = 0
    length = len(value)
    in_string = False
    escaped = False
    while index < length:
        char = value[index]
        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (value[end].isalnum() or value[end] == "_"):
                end += 1
            token = value[index:end]
            chars.append(replacements.get(token, token))
            index = end
            continue
        chars.append(char)
        index += 1
    return "".join(chars)


def _repair_trailing_commas(value: str) -> str:
    chars: list[str] = []
    index = 0
    length = len(value)
    in_string = False
    escaped = False
    while index < length:
        char = value[index]
        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue
        if char == ",":
            probe = index + 1
            while probe < length and value[probe].isspace():
                probe += 1
            if probe < length and value[probe] in "]}":
                index += 1
                continue
        chars.append(char)
        index += 1
    return "".join(chars)


def _repair_json_like(value: str) -> str:
    repaired = value
    for _ in range(2):
        repaired = _repair_unescaped_quotes(repaired)
        repaired = _repair_unquoted_keys(repaired)
        repaired = _repair_json_literals(repaired)
        repaired = _repair_trailing_commas(repaired)
    return repaired


def decode_json_container(value: str) -> Any:
    """Decode a provider JSON container, with a bounded safe wire repair.

    The repaired candidate is still accepted only if the standard JSON parser
    accepts it.  This helper never evaluates Python expressions or turns
    ordinary model text into structured output.
    """

    candidate = value.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].lstrip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Some OpenAI-compatible providers concatenate a valid container with
        # a trailing explanation or a second serialized copy.  Recover only
        # the first complete JSON value; the caller still validates its type
        # against the field annotation, so prose cannot become structured data.
        try:
            first_value, end = json.JSONDecoder().raw_decode(candidate)
            remainder = candidate[end:].strip()
            if remainder.startswith("```"):
                remainder = remainder[3:].strip()
            if remainder and not remainder.startswith(("{", "[")):
                return first_value
        except json.JSONDecodeError:
            pass
        repaired = _repair_json_like(candidate)
        if repaired == candidate:
            raise
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as repaired_exc:
            raise ValueError(
                "provider JSON container is malformed after safe wire repair: "
                f"{repaired_exc.msg} at column {repaired_exc.colno}"
            ) from exc


__all__ = ["decode_json_container"]
