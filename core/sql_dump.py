"""Narrow lexical reader. Source SQL is never executed, including SET/ALTER commands."""

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import zipfile

from core.policy import EXPECTED_ROWS, PUBLIC_FIELDS, SQL_MEMBER, SQL_SHA256


@dataclass
class Dump:
    tables: dict
    columns: dict
    counts: dict
    sha256: str
    member: str


def statements(text):
    """Split outside SQL strings/comments, accepting backslash and doubled quotes."""
    index = start = 0
    quote = None
    parts = []
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"`":
            quote = char
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                raise ValueError("Unterminated SQL comment")
            parts.extend((text[start:index], " "))
            index = end + 2
            start = index
            continue
        elif char == "#" or (text.startswith("--", index) and
                              (index + 2 == len(text) or text[index + 2].isspace())):
            end = text.find("\n", index)
            end = len(text) if end == -1 else end + 1
            parts.extend((text[start:index], "\n"))
            index = start = end
            continue
        elif char == ";":
            value = "".join(parts + [text[start:index]]).strip()
            if value:
                yield value
            parts.clear()
            start = index + 1
        index += 1
    if quote:
        raise ValueError("Unterminated SQL string")
    if "".join(parts + [text[start:]]).strip():
        raise ValueError("SQL statement lacks final semicolon")


def value_rows(text):
    """Yield scalar token lists; nested expressions and trailing commas fail."""
    if not text:
        raise ValueError("SQL VALUES contains no rows")
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "(":
            raise ValueError("Expected SQL VALUES tuple")
        index += 1
        start, quote, fields = index, None, []
        while index < len(text):
            char = text[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "(":
                raise ValueError("SQL expressions are not supported in VALUES")
            elif char in ",)":
                fields.append(text[start:index].strip())
                start = index + 1
                if char == ")":
                    index += 1
                    break
            index += 1
        else:
            raise ValueError("Unterminated SQL VALUES tuple")
        if quote or any(not field for field in fields):
            raise ValueError("Malformed SQL field")
        yield fields
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return
        if text[index] != ",":
            raise ValueError("Unexpected SQL VALUES suffix")
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            raise ValueError("Trailing SQL VALUES comma")


def literal(token):
    """Decode MySQL scalar literals, without eval or a database engine."""
    if token.upper() == "NULL":
        return None
    if re.fullmatch(r"[-+]?\d+", token):
        return int(token)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", token):
        return float(token)
    if re.fullmatch(r"0x[0-9a-fA-F]*", token):
        return bytes.fromhex(token[2:])
    if re.fullmatch(r"[bB]'[01]*'", token):
        return int(token[2:-1] or "0", 2)
    match = re.fullmatch(r"(?:_(?:utf8|utf8mb4|binary))?(['\"])(.*)\1", token, re.S | re.I)
    if not match:
        raise ValueError("Unsupported SQL scalar literal")
    quote, body = match.groups()
    escapes = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a",
               "\\": "\\", "'": "'", '"': '"', "%": "\\%", "_": "\\_"}
    output, index = [], 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            if index + 1 == len(body):
                raise ValueError("Dangling SQL escape")
            output.append(escapes.get(body[index + 1], body[index + 1]))
            index += 2
        elif char == quote:
            if body[index:index + 2] != quote * 2:
                raise ValueError("Unescaped quote inside SQL literal")
            output.append(quote)
            index += 2
        else:
            output.append(char)
            index += 1
    return "".join(output)


def parse_dump(text, *, projection=PUBLIC_FIELDS):
    columns, tables, counts = {}, {name: [] for name in projection}, Counter()
    for statement in statements(text):
        create = re.match(r"CREATE TABLE\s+`([^`]+)`\s*\(", statement, re.I)
        insert = re.match(r"INSERT INTO\s+`([^`]+)`\s*(\([^)]*\))?\s*VALUES\s*", statement, re.I)
        if create:
            name = create[1]
            if name in columns:
                raise ValueError("Duplicate SQL table definition: " + name)
            columns[name] = re.findall(r"^\s*`([^`]+)`\s+[^\n]+", statement[create.end():], re.M)
            if not columns[name] or len(set(columns[name])) != len(columns[name]):
                raise ValueError("Invalid SQL column definition: " + name)
            if name in projection and not set(projection[name]).issubset(columns[name]):
                raise ValueError("Missing allowlisted source columns: " + name)
        elif insert:
            name = insert[1]
            if name not in columns:
                raise ValueError("INSERT before CREATE TABLE: " + name)
            names = re.findall(r"`([^`]+)`", insert[2]) if insert[2] else columns[name]
            if names != columns[name]:
                raise ValueError("Unexpected INSERT column order: " + name)
            for tokens in value_rows(statement[insert.end():]):
                if len(tokens) != len(names):
                    raise ValueError("SQL column/value count differs: " + name)
                counts[name] += 1
                row = {}
                for column, token in zip(names, tokens):
                    value = literal(token)
                    if name in projection and column in projection[name]:
                        if isinstance(value, str):
                            value.encode("utf-8", errors="strict")
                        if isinstance(value, bytes):
                            raise ValueError("Binary value in an allowlisted column: " + name + "." + column)
                        row[column] = value
                if name in tables:
                    tables[name].append(row)
        elif re.match(r"(?:SET|START TRANSACTION|COMMIT|ALTER TABLE|DROP TABLE|LOCK TABLE|UNLOCK TABLE|USE|CREATE DATABASE)\b", statement, re.I):
            if "NO_BACKSLASH_ESCAPES" in statement.upper():
                raise ValueError("Unsupported MySQL string mode")
            # Read-only structural/header statements are recognized, never executed.
        else:
            raise ValueError("Unsupported SQL statement; refusing a partial import")
    if not set(projection).issubset(columns):
        raise ValueError("Required source tables are absent")
    return tables, columns, {name: counts.get(name, 0) for name in columns}


def read_dump(path: Path):
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != SQL_SHA256:
        raise ValueError("SQL ZIP differs from the pinned source; no import performed")
    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if info.filename.endswith(".sql")]
        if len(members) != 1 or members[0].filename != SQL_MEMBER or members[0].file_size > 25_000_000:
            raise ValueError("Unexpected SQL archive member/size")
        text = archive.read(SQL_MEMBER).decode("utf-8-sig", errors="surrogateescape")
    tables, columns, counts = parse_dump(text)
    if len(columns) != 27 or any(counts.get(name, 0) != count for name, count in EXPECTED_ROWS.items()):
        raise ValueError("Pinned source table counts differ from intake")
    return Dump(tables, columns, counts, digest, SQL_MEMBER)
