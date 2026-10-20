"""Detect the installed LMMS application and its available plugins.

The MCP server manipulates project files directly without launching
LMMS. However, knowing which plugins the installed LMMS actually ships
prevents generating projects with missing-plugin warnings.

LMMS 1.2.x and 1.3.x differ in plugin availability, e.g.:
- SlicerT, Xpressive: 1.3+ only
- Compressor, Dispersion, FrequencyShifter, SlewDistortion effects: 1.3+ only
"""

import os
import re
import subprocess
from pathlib import Path

_CANDIDATE_EXES = [
    Path(os.environ.get("LMMS_EXECUTABLE", "")) if os.environ.get("LMMS_EXECUTABLE") else None,
    Path("C:/Program Files/LMMS/lmms.exe"),
    Path("C:/Program Files (x86)/LMMS/lmms.exe"),
    Path.home() / "AppData/Local/Programs/LMMS/lmms.exe",
]


def find_lmms_exe() -> Path | None:
    """Locate the installed LMMS executable."""
    for candidate in _CANDIDATE_EXES:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def get_plugins_dir() -> Path | None:
    """Return the plugins directory of the installed LMMS."""
    exe = find_lmms_exe()
    if exe is None:
        return None
    plugins = exe.parent / "plugins"
    return plugins if plugins.is_dir() else None


def get_installed_plugins() -> set[str]:
    """Set of plugin library names shipped with the installed LMMS.

    Names are lowercase DLL basenames (e.g. "tripleoscillator",
    "reverbsc"). Returns an empty set if LMMS is not found.
    """
    plugins_dir = get_plugins_dir()
    if plugins_dir is None:
        return set()
    return {
        f.stem.lower() for f in plugins_dir.glob("*.dll")
    }


def get_lmms_version() -> str | None:
    """Version string of the installed LMMS (e.g. '1.2.2'), or None."""
    exe = find_lmms_exe()
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout + out.stderr)
        return match.group(1) if match else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# Known aliases across versions (XML name -> possible DLL names).
# Some instruments are statically linked into lmms.exe and have no DLL;
# those are listed in STATIC_PLUGINS.
STATIC_PLUGINS = {
    # Official Windows builds link FreeBoy into the main binary
    "freeboy",
}

# XML/plugin name -> DLL names it can have. LMMS 1.2 ships FreeBoy as papu.dll and
# OpulenZ as opl2.dll (1.3 renamed both); the stk folder builds malletsstk.dll.
PLUGIN_ALIASES = {
    "freeboy": {"freeboy", "papu"},
    "opulenz": {"opulenz", "opl2"},
    "nes": {"nes", "nescaline"},
    "malletsstk": {"malletsstk", "stk"},
    "sf2player": {"sf2player", "fluidsynth"},
}

#: Plugins that only exist in LMMS 1.3 and later.
LMMS_13_ONLY = {"slicert", "xpressive", "compressor", "dispersion",
                "frequencyshifter", "slewdistortion"}

#: DLLs in LMMS's plugins folder that are not instruments or effects you add by name.
PLUGIN_HOSTS = {
    "carlarack": "Carla Rack instrument (needs Carla installed)",
    "carlapatchbay": "Carla Patchbay instrument (needs Carla installed)",
    "ladspaeffect": "LADSPA effect host",
    "lv2effect": "LV2 effect host",
    "lv2instrument": "LV2 instrument host",
    "vsteffect": "VST effect host",
    "vestige": "VST instrument host (use add_vst_track)",
}
EXTRA_EFFECTS = {
    "spectrumanalyzer": "Spectrum analyzer (display only)",
    "peakcontrollereffect": "Peak controller (drives automation from a signal)",
}
NON_PLUGINS = {
    "carlabase", "vstbase", "libzynaddsubfxcore", "zynaddsubfxcore",
    "hydrogenimport", "midiimport", "midiexport", "ladspabrowser",
    "remotezynaddsubfx", "remotevstplugin",
}


def check_plugin_available(plugin_name: str) -> tuple[bool, str]:
    """Check whether a plugin exists in the installed LMMS.

    Returns (available, reason). If no LMMS installation is detected,
    everything is considered available (cannot verify).
    """
    name = plugin_name.lower()
    if name in STATIC_PLUGINS:
        return True, "built-in"
    installed = get_installed_plugins()
    if not installed:
        return True, "LMMS installation not found - cannot verify"
    if name in installed:
        return True, "installed"
    if any(alias in installed for alias in PLUGIN_ALIASES.get(name, {name})):
        return True, "installed (alias)"
    return False, (
        f"'{plugin_name}' is not included in your installed LMMS "
        f"(found {len(installed)} plugins). It may require a newer "
        f"LMMS version."
    )


def classify_installed_plugins(
    known_instruments: set[str],
    known_effects: set[str],
) -> dict[str, list[str]]:
    """Classify the installed plugin DLLs.

    Returns dict with keys "instruments", "effects", "hosts", "other" and "unknown"
    (unknown = custom or newer plugins whose type the file name doesn't tell).
    Instruments and effects are reported by the name you use in the tools
    (e.g. papu.dll -> "freeboy").
    """
    installed = get_installed_plugins()
    dll_to_name = {}
    for name, dlls in PLUGIN_ALIASES.items():
        for dll in dlls:
            dll_to_name.setdefault(dll, name)
    result: dict[str, list[str]] = {
        "instruments": [], "effects": [], "hosts": [], "other": [], "unknown": []}
    for dll in sorted(installed):
        name = dll_to_name.get(dll, dll)
        if dll in NON_PLUGINS or dll.startswith("lib"):
            result["other"].append(dll)
        elif dll in PLUGIN_HOSTS:
            result["hosts"].append(dll)
        elif name in known_instruments:
            result["instruments"].append(name)
        elif name in known_effects or dll in EXTRA_EFFECTS:
            result["effects"].append(name)
        else:
            result["unknown"].append(dll)
    return result


def find_vst_plugins(directory: str | Path, recursive: bool = True) -> list[dict]:
    """Scan a directory for VST plugin DLLs.

    Returns list of dicts with name and path. Note: any .dll could be a
    VST effect or instrument - LMMS decides on load.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Directory not found: {directory}")
    it = root.rglob("*.dll") if recursive else root.glob("*.dll")
    skip = {"lmms.exe", "remotevstplugin.exe", "32bitvsthelper.exe"}
    results = []
    for dll in sorted(it):
        if dll.stem.lower() in skip:
            continue
        results.append({
            "name": dll.stem,
            "path": str(dll),
            "size_kb": round(dll.stat().st_size / 1024),
        })
    return results
