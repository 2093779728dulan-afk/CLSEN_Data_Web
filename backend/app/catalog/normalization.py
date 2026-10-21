"""Unicode 15.1 normalization independent from the host Unicode runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from app.catalog.errors import CatalogDataIntegrityError, CatalogNormalizationError

UCD_VERSION: Final = "15.1.0"
SELLER_SKU_MATCH_VERSION: Final = "seller_sku_match_v1"
CATALOG_IDENTITY_KEY_VERSION: Final = "catalog_identity_key_v1"
SAFE_SOURCE_PROJECTION_VERSION: Final = "safe_source_projection_v1"

_EXPECTED_DATA_FILES: Final = frozenset(
    {
        "CaseFolding.txt",
        "CompositionExclusions.txt",
        "DerivedNormalizationProps.txt",
        "LICENSE.txt",
        "NormalizationTest.txt",
        "PropList.txt",
        "UnicodeData.txt",
    }
)
_UNSAFE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})

_S_BASE = 0xAC00
_L_BASE = 0x1100
_V_BASE = 0x1161
_T_BASE = 0x11A7
_L_COUNT = 19
_V_COUNT = 21
_T_COUNT = 28
_N_COUNT = _V_COUNT * _T_COUNT
_S_COUNT = _L_COUNT * _N_COUNT
_HTML_STRUCTURAL_CODEPOINTS = frozenset(ord(character) for character in "<>&\"'")


@dataclass(frozen=True, slots=True, repr=False)
class NormalizedKey:
    version: str
    text: str
    utf8: bytes
    sha256: bytes

    def __repr__(self) -> str:
        return (
            f"NormalizedKey(version={self.version!r}, utf8_length={len(self.utf8)}, "
            f"sha256={self.sha256.hex()!r})"
        )


@dataclass(frozen=True, slots=True)
class SafeSourceProjection:
    version: str
    preview: str
    sha256: str
    is_unsafe: bool
    is_truncated: bool


@dataclass(frozen=True, slots=True)
class _UcdData:
    combining_classes: MappingProxyType[int, int]
    decompositions: MappingProxyType[int, tuple[int, ...]]
    compositions: MappingProxyType[tuple[int, int], int]
    casefold: MappingProxyType[int, tuple[int, ...]]
    white_space: frozenset[int]
    unsafe_categories: frozenset[int]


def _strict_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=no_duplicates)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise CatalogDataIntegrityError() from error
    if not isinstance(value, dict):
        raise CatalogDataIntegrityError()
    return value


def verify_ucd_manifest(data_root: Path) -> dict[str, Any]:
    """Verify the frozen official data set before parsing any semantic table."""

    try:
        root = data_root.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise CatalogDataIntegrityError()
        manifest_path = root / "manifest.json"
        manifest = _strict_json(manifest_path)
        if (
            set(manifest)
            != {
                "files",
                "format",
                "source_base_url",
                "unicode_version",
            }
            or manifest.get("format") != "clsen-ucd-manifest-v1"
            or manifest.get("unicode_version") != UCD_VERSION
            or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != _EXPECTED_DATA_FILES
        ):
            raise CatalogDataIntegrityError()
        for filename in sorted(_EXPECTED_DATA_FILES):
            record = manifest["files"].get(filename)
            path = root / filename
            if (
                not isinstance(record, dict)
                or set(record) != {"bytes", "sha256"}
                or not isinstance(record.get("bytes"), int)
                or not isinstance(record.get("sha256"), str)
                or path.is_symlink()
                or not path.is_file()
                or path.resolve().parent != root
            ):
                raise CatalogDataIntegrityError()
            payload = path.read_bytes()
            if (
                len(payload) != record["bytes"]
                or hashlib.sha256(payload).hexdigest() != record["sha256"]
            ):
                raise CatalogDataIntegrityError()
    except (OSError, KeyError, TypeError, CatalogDataIntegrityError) as error:
        raise RuntimeError("UCD data integrity check failed") from error
    return manifest


def _parse_codepoint_range(value: str) -> range:
    if ".." in value:
        first, last = value.split("..", 1)
        return range(int(first, 16), int(last, 16) + 1)
    codepoint = int(value, 16)
    return range(codepoint, codepoint + 1)


def _property_codepoints(path: Path, property_name: str) -> frozenset[int]:
    result: set[int] = set()
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            codepoints, name = (part.strip() for part in line.split(";", 1))
            if name == property_name:
                result.update(_parse_codepoint_range(codepoints))
    return frozenset(result)


def _composition_exclusions(root: Path) -> frozenset[int]:
    result = set(
        _property_codepoints(
            root / "DerivedNormalizationProps.txt",
            "Full_Composition_Exclusion",
        )
    )
    with (root / "CompositionExclusions.txt").open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            value = raw_line.split("#", 1)[0].strip()
            if value:
                result.update(_parse_codepoint_range(value))
    return frozenset(result)


def _parse_unicode_data(
    path: Path,
) -> tuple[
    dict[int, int],
    dict[int, tuple[int, ...]],
    dict[int, tuple[int, ...]],
    dict[int, str],
]:
    combining: dict[int, int] = {}
    decompositions: dict[int, tuple[int, ...]] = {}
    canonical_decompositions: dict[int, tuple[int, ...]] = {}
    categories: dict[int, str] = {}
    range_start: tuple[int, str, int] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            fields = raw_line.rstrip("\n").split(";")
            if len(fields) != 15:
                raise CatalogDataIntegrityError()
            codepoint = int(fields[0], 16)
            name = fields[1]
            category = fields[2]
            combining_class = int(fields[3])
            if name.endswith(", First>"):
                range_start = (codepoint, category, combining_class)
                continue
            if name.endswith(", Last>"):
                if range_start is None:
                    raise CatalogDataIntegrityError()
                first, first_category, first_combining = range_start
                if category != first_category or combining_class != first_combining:
                    raise CatalogDataIntegrityError()
                for member in range(first, codepoint + 1):
                    if category in _UNSAFE_CATEGORIES:
                        categories[member] = category
                    if combining_class:
                        combining[member] = combining_class
                range_start = None
                continue
            if range_start is not None:
                raise CatalogDataIntegrityError()
            if category in _UNSAFE_CATEGORIES:
                categories[codepoint] = category
            if combining_class:
                combining[codepoint] = combining_class
            decomposition = fields[5].strip()
            if decomposition:
                parts = decomposition.split()
                is_compatibility = parts[0].startswith("<")
                if is_compatibility:
                    parts = parts[1:]
                parsed_decomposition = tuple(int(part, 16) for part in parts)
                decompositions[codepoint] = parsed_decomposition
                if not is_compatibility:
                    canonical_decompositions[codepoint] = parsed_decomposition
    if range_start is not None:
        raise CatalogDataIntegrityError()
    return combining, decompositions, canonical_decompositions, categories


def _parse_casefold(path: Path) -> dict[int, tuple[int, ...]]:
    result: dict[int, tuple[int, ...]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            codepoint_text, status, mapping_text, *_ = (
                part.strip() for part in line.split(";")
            )
            if status not in {"C", "F"}:
                continue
            codepoint = int(codepoint_text, 16)
            mapping = tuple(int(part, 16) for part in mapping_text.split())
            if status == "F" or codepoint not in result:
                result[codepoint] = mapping
    return result


def _load_ucd_from(root: Path) -> _UcdData:
    verify_ucd_manifest(root)
    try:
        (
            combining,
            decompositions,
            canonical_decompositions,
            categories,
        ) = _parse_unicode_data(root / "UnicodeData.txt")
        exclusions = _composition_exclusions(root)
        compositions: dict[tuple[int, int], int] = {}
        for composite, decomposition in canonical_decompositions.items():
            if (
                composite not in exclusions
                and len(decomposition) == 2
                and combining.get(decomposition[0], 0) == 0
            ):
                compositions[decomposition] = composite
        return _UcdData(
            combining_classes=MappingProxyType(combining),
            decompositions=MappingProxyType(decompositions),
            compositions=MappingProxyType(compositions),
            casefold=MappingProxyType(_parse_casefold(root / "CaseFolding.txt")),
            white_space=_property_codepoints(root / "PropList.txt", "White_Space"),
            unsafe_categories=frozenset(categories),
        )
    except (OSError, UnicodeError, ValueError, CatalogDataIntegrityError) as error:
        raise RuntimeError("UCD data integrity check failed") from error


@lru_cache(maxsize=1)
def _ucd() -> _UcdData:
    root = Path(str(files("app.catalog").joinpath("data/ucd_15_1")))
    return _load_ucd_from(root)


def _assert_scalar_text(value: str) -> None:
    if not isinstance(value, str) or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise CatalogNormalizationError()


def _decompose(codepoint: int, data: _UcdData, target: list[int]) -> None:
    syllable_index = codepoint - _S_BASE
    if 0 <= syllable_index < _S_COUNT:
        leading = _L_BASE + syllable_index // _N_COUNT
        vowel = _V_BASE + (syllable_index % _N_COUNT) // _T_COUNT
        target.extend((leading, vowel))
        trailing_index = syllable_index % _T_COUNT
        if trailing_index:
            target.append(_T_BASE + trailing_index)
        return
    decomposition = data.decompositions.get(codepoint)
    if decomposition is None:
        target.append(codepoint)
        return
    for member in decomposition:
        _decompose(member, data, target)


def _canonical_order(codepoints: list[int], data: _UcdData) -> list[int]:
    ordered: list[int] = []
    for codepoint in codepoints:
        combining_class = data.combining_classes.get(codepoint, 0)
        position = len(ordered)
        if combining_class:
            while position > 0:
                previous_class = data.combining_classes.get(ordered[position - 1], 0)
                if previous_class == 0 or previous_class <= combining_class:
                    break
                position -= 1
        ordered.insert(position, codepoint)
    return ordered


def _hangul_composite(left: int, right: int) -> int | None:
    leading_index = left - _L_BASE
    if 0 <= leading_index < _L_COUNT:
        vowel_index = right - _V_BASE
        if 0 <= vowel_index < _V_COUNT:
            return _S_BASE + (leading_index * _V_COUNT + vowel_index) * _T_COUNT
    syllable_index = left - _S_BASE
    if 0 <= syllable_index < _S_COUNT and syllable_index % _T_COUNT == 0:
        trailing_index = right - _T_BASE
        if 0 < trailing_index < _T_COUNT:
            return left + trailing_index
    return None


def _compose(codepoints: list[int], data: _UcdData) -> list[int]:
    if not codepoints:
        return []
    result = [codepoints[0]]
    starter_position = 0
    starter = codepoints[0]
    last_combining_class = 0
    for codepoint in codepoints[1:]:
        combining_class = data.combining_classes.get(codepoint, 0)
        composite = _hangul_composite(starter, codepoint)
        if composite is None:
            composite = data.compositions.get((starter, codepoint))
        if composite is not None and (
            last_combining_class == 0 or last_combining_class < combining_class
        ):
            result[starter_position] = composite
            starter = composite
            continue
        if combining_class == 0:
            starter_position = len(result)
            starter = codepoint
        last_combining_class = combining_class
        result.append(codepoint)
    return result


def nfkc_15_1(value: str) -> str:
    """Apply Unicode 15.1 NFKC without using the host unicodedata module."""

    _assert_scalar_text(value)
    data = _ucd()
    decomposed: list[int] = []
    for character in value:
        _decompose(ord(character), data, decomposed)
    ordered = _canonical_order(decomposed, data)
    return "".join(chr(codepoint) for codepoint in _compose(ordered, data))


def _trim_white_space(value: str, data: _UcdData) -> str:
    first = 0
    last = len(value)
    while first < last and ord(value[first]) in data.white_space:
        first += 1
    while last > first and ord(value[last - 1]) in data.white_space:
        last -= 1
    return value[first:last]


def _normalized_key(value: str, *, casefold: bool, version: str) -> NormalizedKey:
    data = _ucd()
    normalized = _trim_white_space(nfkc_15_1(value), data)
    if casefold:
        normalized = "".join(
            chr(member)
            for character in normalized
            for member in data.casefold.get(ord(character), (ord(character),))
        )
    if casefold and not normalized:
        raise ValueError("normalized key must not be empty")
    payload = normalized.encode("utf-8")
    return NormalizedKey(
        version=version,
        text=normalized,
        utf8=payload,
        sha256=hashlib.sha256(payload).digest(),
    )


def seller_sku_match_v1(value: str) -> NormalizedKey:
    return _normalized_key(value, casefold=False, version=SELLER_SKU_MATCH_VERSION)


def catalog_identity_key_v1(value: str) -> NormalizedKey:
    return _normalized_key(
        value,
        casefold=True,
        version=CATALOG_IDENTITY_KEY_VERSION,
    )


def _is_xml_1_0_character(codepoint: int) -> bool:
    return (
        codepoint in {0x09, 0x0A, 0x0D}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _is_noncharacter(codepoint: int) -> bool:
    return 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFE == 0xFFFE


def _is_projection_separator(codepoint: int, data: _UcdData) -> bool:
    return (
        codepoint in data.white_space
        or codepoint in _HTML_STRUCTURAL_CODEPOINTS
        or not _is_xml_1_0_character(codepoint)
        or codepoint in data.unsafe_categories
        or _is_noncharacter(codepoint)
    )


def is_unsafe_source_text_v1(value: str) -> bool:
    _assert_scalar_text(value)
    data = _ucd()
    return not value or any(
        not _is_xml_1_0_character(codepoint)
        or codepoint in data.unsafe_categories
        or _is_noncharacter(codepoint)
        for codepoint in map(ord, value)
    )


def safe_source_projection_v1(
    value: str,
    *,
    max_scalars: int = 255,
) -> SafeSourceProjection:
    _assert_scalar_text(value)
    if (
        not isinstance(max_scalars, int)
        or isinstance(max_scalars, bool)
        or max_scalars < 1
    ):
        raise CatalogNormalizationError()
    data = _ucd()
    projected: list[str] = []
    in_replaced_run = False
    replaced = False
    for character in value:
        if _is_projection_separator(ord(character), data):
            replaced = True
            if not in_replaced_run:
                projected.append(" ")
                in_replaced_run = True
        else:
            projected.append(character)
            in_replaced_run = False
    safe_value = _trim_white_space("".join(projected), data)
    if not safe_value:
        preview = "[不可显示]"
        replaced = True
        truncated = False
    else:
        truncated = len(safe_value) > max_scalars
        preview = safe_value[:max_scalars]
    return SafeSourceProjection(
        version=SAFE_SOURCE_PROJECTION_VERSION,
        preview=preview,
        sha256="sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest(),
        is_unsafe=replaced or safe_value != value,
        is_truncated=truncated,
    )


__all__ = (
    "CATALOG_IDENTITY_KEY_VERSION",
    "SAFE_SOURCE_PROJECTION_VERSION",
    "SELLER_SKU_MATCH_VERSION",
    "UCD_VERSION",
    "NormalizedKey",
    "SafeSourceProjection",
    "catalog_identity_key_v1",
    "is_unsafe_source_text_v1",
    "nfkc_15_1",
    "safe_source_projection_v1",
    "seller_sku_match_v1",
    "verify_ucd_manifest",
)
