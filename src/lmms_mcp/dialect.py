"""LMMS file-format dialects: convert between project files and the in-memory tree.

The rest of the server works on ONE internal form:

* note keys and instrument base notes are **MIDI numbers** (A4 = 69, C4 = 60)
* mixer tags use the LMMS 1.3 names: ``<mixer>``, ``<mixerchannel>``, ``mixch``
* sample clips are ``<sampleclip>``
* pattern / Beat+Bassline tags use the LMMS 1.2 names: ``<pattern>``, ``<bbtrack>``,
  ``<bbtco>``, ``<automationpattern>``

Files on disk come in two dialects:

``legacy`` (LMMS 1.2.x, ``version="1.0"``)
    Keys count from A4 = 57 (one octave below MIDI), ``<fxmixer>``/``<fxchannel>``/``fxch``,
    ``<sampletco>``. **New projects are always written in this dialect**: LMMS 1.2 reads it
    natively and LMMS 1.3 upgrades it on load (``DataFile::upgrade_extendedNoteRange``,
    ``upgrade_mixerRename``, ``upgrade_bbTcoRename`` in LMMS 1.3 ``src/core/DataFile.cpp``
    run for every file whose ``creatorversion`` is below 1.3.0), so one file serves both.

``modern`` (LMMS 1.3+, ``version`` is an integer such as ``"31"``)
    MIDI keys, ``<mixer>``, ``<midiclip>``, ``<patternclip>``, ``<patterntrack>``,
    ``<automationclip>``, step notes as ``type="1"``. A project loaded from a 1.3 file is
    saved back as 1.3, so 1.3 users don't lose 1.3-only data.

Projects written by the original LMMS MCP (``creator="LMMS MCP Server"``, legacy version
but ``<mixer>`` tags and MIDI keys) are recognised and loaded without shifting keys.
"""

from __future__ import annotations

import copy
from xml.etree import ElementTree as ET

LEGACY = "legacy"
MODERN = "modern"

#: creatorversion stamped on legacy files (LMMS 1.3 upgrades anything below 1.3.0)
LEGACY_CREATOR_VERSION = "1.2.2"
#: semitones between MIDI numbering and LMMS 1.2 numbering
KEY_OFFSET = 12

# tag renames LMMS 1.3 applies to old files (upgrade_bbTcoRename / upgrade_mixerRename)
_MODERN_TAGS = {           # internal tag -> 1.3 tag
    "automationpattern": "automationclip",
    "bbtco": "patternclip",
    "pattern": "midiclip",
    "bbtrack": "patterntrack",
}
_LEGACY_TAGS = {           # internal tag -> 1.2 tag
    "mixer": "fxmixer",
    "mixerchannel": "fxchannel",
    "sampleclip": "sampletco",
}
_TRACK_ELEMS_WITH_MIXCH = ("instrumenttrack", "sampletrack")
# instrument plugins renamed in LMMS 1.3 (DataFile::upgrade_1_3_0): internal -> 1.2 name
_LEGACY_INSTRUMENTS = {"freeboy": "papu", "opulenz": "OPL2"}


def detect(root: ET.Element) -> str:
    """Return the dialect of a project root as stored on disk."""
    version = root.get("version", "1.0")
    return LEGACY if version in ("1.0", "") or not version.isdigit() else MODERN


def _is_old_mcp_file(root: ET.Element) -> bool:
    """Files saved by the original LMMS MCP: legacy stamp, 1.3 mixer tags, MIDI keys."""
    song = root.find("song")
    return (
        detect(root) == LEGACY
        and song is not None
        and song.find("mixer") is not None
        and song.find("fxmixer") is None
    )


def _rename_tags(root: ET.Element, mapping: dict[str, str]) -> None:
    for elem in root.iter():
        new = mapping.get(elem.tag)
        if new:
            elem.tag = new


def _rename_attr(root: ET.Element, old: str, new: str) -> None:
    for tag in _TRACK_ELEMS_WITH_MIXCH:
        for elem in root.iter(tag):
            if old in elem.attrib:
                elem.set(new, elem.attrib.pop(old))


def _shift_keys(root: ET.Element, delta: int, notes: bool = True) -> None:
    """Shift note keys and instrument base notes (attribute or automated child)."""
    if not delta:
        return
    for note in root.iter("note") if notes else ():
        if "key" in note.attrib:
            note.set("key", str(int(float(note.get("key"))) + delta))
    for inst in root.iter("instrumenttrack"):
        if "basenote" in inst.attrib:
            inst.set("basenote", str(int(float(inst.get("basenote"))) + delta))
        child = inst.find("basenote")
        if child is not None and "value" in child.attrib:
            child.set("value", str(float(child.get("value")) + delta))


def _rename_instruments(root: ET.Element, mapping: dict[str, str]) -> None:
    """Rename instrument plugins: <instrument name="a"><a .../></instrument> -> b."""
    for inst in root.iter("instrument"):
        old = inst.get("name")
        new = mapping.get(old)
        if new:
            inst.set("name", new)
            for child in inst.iter(old):
                child.tag = new


def to_internal(root: ET.Element) -> str:
    """Convert a freshly loaded file tree to the internal form, in place.

    Returns the dialect the file was stored in (remember it to save it back the same way).
    """
    dialect = detect(root)
    if dialect == LEGACY:
        if _is_old_mcp_file(root):
            # The original LMMS MCP wrote MIDI keys but LMMS 1.2 base notes (57):
            # only the base notes need converting.
            _shift_keys(root, +KEY_OFFSET, notes=False)
            return LEGACY
        _rename_tags(root, {v: k for k, v in _LEGACY_TAGS.items()})
        _rename_attr(root, "fxch", "mixch")
        _rename_instruments(root, {v: k for k, v in _LEGACY_INSTRUMENTS.items()})
        _shift_keys(root, +KEY_OFFSET)
    else:
        _rename_tags(root, {v: k for k, v in _MODERN_TAGS.items()})
        # 1.3 step notes (type="1") become LMMS 1.2-style step notes the server understands
        for note in root.iter("note"):
            if note.get("type") == "1":
                note.set("len", "-192")
                del note.attrib["type"]
    return dialect


def to_file(root: ET.Element, dialect: str = LEGACY) -> ET.Element:
    """Return a COPY of the internal tree converted to ``dialect`` for writing."""
    out = copy.deepcopy(root)
    if dialect == LEGACY:
        _rename_tags(out, _LEGACY_TAGS)
        _rename_attr(out, "mixch", "fxch")
        _rename_instruments(out, _LEGACY_INSTRUMENTS)
        _shift_keys(out, -KEY_OFFSET)
        out.set("version", "1.0")
        out.set("creatorversion", LEGACY_CREATOR_VERSION)
        out.set("creator", "LMMS")
    else:
        _rename_tags(out, _MODERN_TAGS)
        for note in out.iter("note"):
            if int(float(note.get("len", "0"))) < 0:
                note.set("len", "12")
                note.set("type", "1")
    return out
