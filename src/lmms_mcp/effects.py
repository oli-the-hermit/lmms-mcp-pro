"""Effect chain (fxchain) handling for LMMS projects.

Provides the list of built-in LMMS effect plugins and functions to
manipulate fxchain elements on tracks and mixer channels.
"""

import base64
import struct
import xml.etree.ElementTree as ET

from .effect_params import EFFECT_PARAMS

# Built-in LMMS effects: plugin name -> (description, controls node name).
# Names verified against LMMS source (plugin descriptors + nodeName()).
KNOWN_EFFECTS = {
    "amplifier": ("Volume/gain control", "AmplifierControls"),
    "bassbooster": ("Low frequency booster", "bassboostercontrols"),
    "bitcrush": ("Bit crusher for lo-fi sound", "bitcrushcontrols"),
    "compressor": ("Dynamic range compressor", "CompressorControls"),
    "crossovereq": ("3-band crossover EQ", "crossoevereqcontrols"),
    "delay": ("Tempo-synced delay/echo", "Delay"),
    "dispersion": ("Dispersion/phaser effect", "DispersionControls"),
    "dualfilter": ("Dual filter (2 filters in parallel/serial)", "DualFilterControls"),
    "dynamicsprocessor": ("Dynamics processor (compressor/expander)", "dynamicsprocessor_controls"),
    "eq": ("Parametric equalizer", "Eq"),
    "flanger": ("Flanger modulation effect", "Flanger"),
    "frequencyshifter": ("Frequency shifter", "FrequencyShifterControls"),
    "multitapecho": ("Multi-tap echo", "multitapechocontrols"),
    "reverbsc": ("Studio-quality reverb (Schroeder)", "ReverbSCControls"),
    "slewdistortion": ("Slew-rate distortion", "SlewDistortionControls"),
    "stereoenhancer": ("Stereo width enhancer", "stereoenhancercontrols"),
    "stereomatrix": ("Stereo channel matrix", "stereomatrixcontrols"),
    "waveshaper": ("Waveshaping distortion", "waveshapercontrols"),
}

# Effects that require external hosts/libraries - listed separately so
# agents know they may not work on every system.
EXTERNAL_EFFECTS = {
    "ladspaeffect": "LADSPA plugin host (depends on installed LADSPA libs)",
    "lv2effect": "LV2 plugin host (depends on installed LV2 plugins)",
    "vsteffect": "VST plugin host (Windows/macOS, requires VST DLLs)",
}

#: Effects that only exist in LMMS 1.3 and later.
LMMS_13_ONLY = {"compressor", "dispersion", "frequencyshifter", "slewdistortion"}

# Recommended effects per use case (all available in LMMS 1.2 and 1.3)
EFFECT_RECOMMENDATIONS = {
    "vocals": ["eq", "dynamicsprocessor", "reverbsc", "multitapecho"],
    "drums": ["eq", "dynamicsprocessor", "waveshaper"],
    "bass": ["eq", "bassbooster", "dynamicsprocessor"],
    "synth": ["multitapecho", "reverbsc", "flanger", "bitcrush"],
    "master": ["eq", "dynamicsprocessor", "stereoenhancer", "amplifier"],
    "send_bus_reverb": ["reverbsc (wet=1 on a mixer channel fed by sends)"],
}

#: LMMS stops processing an effect after its input has been silent for "auto-quit"
#: milliseconds. LMMS' own default is 1 ms, which cuts echo and reverb tails, so every
#: effect is written with the maximum.
AUTOQUIT_MS = 8000

#: Default dry/wet when the caller gives none. ``wet`` is a crossfade: 1.0 removes the
#: dry signal entirely, which is right for distortion or EQ but wrong for a reverb or
#: delay inserted on a track. (For a reverb on a send/return mixer channel use wet=1.)
DEFAULT_WET = {"reverbsc": 0.3, "delay": 0.4, "flanger": 0.5}

#: Friendly aliases for awkward LMMS attribute names, per effect.
PARAM_ALIASES = {
    "delay": {"time": "DelayTimeSamples", "delay_time": "DelayTimeSamples",
              "feedback": "FeebackAmount", "lfo_rate": "LfoFrequency",
              "lfo_amount": "LfoAmount", "gain": "OutGain", "output_gain": "OutGain"},
    "flanger": {"delay_time": "DelayTimeSamples", "lfo_rate": "LfoFrequency",
                "lfo_amount": "LfoAmount", "feedback": "Feedback", "noise": "WhiteNoise"},
    "multitapecho": {"step_length": "steplength", "dry_gain": "drygain",
                     "lowpass_stages": "stages", "swap_inputs": "swapinputs"},
    "reverbsc": {"input": "input_gain", "output": "output_gain"},
}

_GRAPH_LEN = 200     # waveshaper / dynamics processor curve length


def get_fxchain(parent: ET.Element, create: bool = True) -> ET.Element:
    """Get or create the fxchain element under a track or mixer channel."""
    fxchain = parent.find("fxchain")
    if fxchain is None and create:
        fxchain = ET.SubElement(parent, "fxchain", {
            "numofeffects": "0", "enabled": "0",
        })
    return fxchain


def _b64_floats(values: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode()


def _floats_from_b64(text: str) -> list[float]:
    raw = base64.b64decode(text or "")
    return list(struct.unpack(f"<{len(raw) // 4}f", raw)) if raw else []


def _fmt(kind: str, value) -> str:
    if kind == "bool":
        return "1" if value else "0"
    if kind == "int":
        return str(int(round(float(value))))
    return repr(float(value))


def _default_controls(name: str) -> dict[str, str]:
    """Every setting of an effect at its LMMS default, as XML attributes."""
    spec = EFFECT_PARAMS.get(name, {}).get("params", {})
    attrs = {attr: _fmt(kind, default) for attr, (kind, default, _lo, _hi) in spec.items()}
    if name == "multitapecho":
        steps = int(spec["steps"][1])
        attrs["ampsteps"] = _b64_floats([0.0] * steps)      # 0 dB per tap
        attrs["lpsteps"] = _b64_floats([3.0] * steps)       # 3 = no low-pass
    if name in ("waveshaper", "dynamicsprocessor"):
        attrs["waveShape"] = _b64_floats([(i + 1) / _GRAPH_LEN for i in range(_GRAPH_LEN)])
    return attrs


def add_effect(
    parent: ET.Element,
    effect_name: str,
    wet: float | None = None,
    enabled: bool = True,
    position: int | None = None,
    params: dict | None = None,
) -> dict:
    """Add an effect to a fxchain element, with every setting written explicitly.

    Args:
        parent: The track or mixer channel element containing fxchain.
        effect_name: Built-in LMMS effect plugin name.
        wet: Dry/wet mix (0.0-1.0). None picks a sensible default per effect
            (reverb 0.3, delay 0.4, flanger 0.5, others 1.0).
        enabled: Whether the effect is active.
        position: Insert position in chain (None=append at end).
        params: Optional settings to apply right away (see set_effect_params).

    Raises:
        ValueError: If effect name is unknown or a parameter is invalid.
    """
    normalized = effect_name.strip().lower()
    if normalized not in KNOWN_EFFECTS:
        if normalized in EXTERNAL_EFFECTS:
            raise ValueError(
                f"Effect '{effect_name}' requires external plugins "
                f"({EXTERNAL_EFFECTS[normalized]}). Use a built-in effect instead."
            )
        valid = ", ".join(sorted(KNOWN_EFFECTS.keys()))
        raise ValueError(f"Unknown effect '{effect_name}'. Valid effects: {valid}")

    if wet is None:
        wet = DEFAULT_WET.get(normalized, 1.0)
    if not 0.0 <= float(wet) <= 1.0:
        raise ValueError("wet must be between 0.0 and 1.0")

    fxchain = get_fxchain(parent)
    effect = ET.Element("effect", {
        "on": "1" if enabled else "0",
        "wet": repr(float(wet)),
        "gate": "0",
        "autoquit": str(AUTOQUIT_MS),
        "autoquit_denominator": "4",
        "autoquit_numerator": "4",
        "syncmode": "0",
        "name": normalized,
    })
    controls_name = KNOWN_EFFECTS[normalized][1]
    ET.SubElement(effect, controls_name, _default_controls(normalized))
    ET.SubElement(effect, "key")

    existing = fxchain.findall("effect")
    if position is None or position >= len(existing):
        fxchain.append(effect)
        final_pos = len(existing)
    else:
        position = max(0, position)
        fxchain.insert(list(fxchain).index(existing[position]), effect)
        final_pos = position

    num = len(fxchain.findall("effect"))
    fxchain.set("numofeffects", str(num))
    fxchain.set("enabled", "1")

    applied = set_effect_params(parent, final_pos, params)["applied"] if params else {}

    note = ""
    if normalized in LMMS_13_ONLY:
        note = " NOTE: this effect only exists in LMMS 1.3+; LMMS 1.2 will skip it."
    return {
        "effect": normalized,
        "position": final_pos,
        "wet": float(wet),
        "enabled": enabled,
        "chain_size": num,
        "params": applied,
        "message": f"Added {normalized} at position {final_pos} "
                   f"(chain now has {num} effects).{note}",
    }


def _find_effect(parent: ET.Element, identifier: str | int) -> ET.Element:
    fxchain = parent.find("fxchain")
    effects = fxchain.findall("effect") if fxchain is not None else []
    if isinstance(identifier, int) or str(identifier).isdigit():
        idx = int(identifier)
        if 0 <= idx < len(effects):
            return effects[idx]
    else:
        for eff in effects:
            if eff.get("name", "").lower() == str(identifier).lower():
                return eff
    names = [e.get("name", "?") for e in effects]
    raise ValueError(f"Effect '{identifier}' not found. Effects here: {names}")


def describe_params(effect_name: str) -> dict:
    """Settings of one effect: name -> {default, min, max, kind} (plus aliases)."""
    name = effect_name.strip().lower()
    spec = EFFECT_PARAMS.get(name, {}).get("params", {})
    out = {attr: {"kind": k, "default": d, "min": lo, "max": hi}
           for attr, (k, d, lo, hi) in sorted(spec.items())}
    if name == "multitapecho":
        out["echo_gains_db"] = {"kind": "list[float]", "min": -60.0, "max": 0.0,
                                "help": "loudness of each repeat in dB, one value per step"}
        out["echo_lowpass"] = {"kind": "list[float]", "min": 0.0, "max": 3.0,
                               "help": "brightness of each repeat: 3 = untouched, 0 = darkest"}
    return {"effect": name, "params": out, "aliases": PARAM_ALIASES.get(name, {}),
            "lmms_13_only": name in LMMS_13_ONLY}


def set_effect_params(parent: ET.Element, identifier: str | int, params: dict | None) -> dict:
    """Change settings of an effect already in a chain (validated against LMMS ranges).

    ``params`` may also contain ``wet`` (0-1) and ``enabled``. Multitap Echo accepts
    ``echo_gains_db`` and ``echo_lowpass`` lists (one value per step).
    """
    effect = _find_effect(parent, identifier)
    name = effect.get("name", "")
    controls_tag = KNOWN_EFFECTS.get(name, ("", ""))[1]
    controls = effect.find(controls_tag) if controls_tag else None
    if controls is None:
        controls = ET.SubElement(effect, controls_tag or "controls")
        controls.attrib.update(_default_controls(name))
    spec = EFFECT_PARAMS.get(name, {}).get("params", {})
    aliases = PARAM_ALIASES.get(name, {})
    applied: dict = {}
    for key, value in (params or {}).items():
        if key == "wet":
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("wet must be between 0.0 and 1.0")
            effect.set("wet", repr(float(value)))
            applied["wet"] = float(value)
            continue
        if key == "enabled":
            effect.set("on", "1" if value else "0")
            applied["enabled"] = bool(value)
            continue
        if name == "multitapecho" and key in ("echo_gains_db", "echo_lowpass"):
            values = [float(v) for v in value]
            lo, hi = (-60.0, 0.0) if key == "echo_gains_db" else (0.0, 3.0)
            if not 4 <= len(values) <= 32:
                raise ValueError(f"{key} needs 4 to 32 values (one per echo step)")
            if any(not lo <= v <= hi for v in values):
                raise ValueError(f"{key} values must be between {lo} and {hi}")
            attr = "ampsteps" if key == "echo_gains_db" else "lpsteps"
            controls.set(attr, _b64_floats(values))
            # keep both graphs and the step count the same length
            other = "lpsteps" if attr == "ampsteps" else "ampsteps"
            fill = 3.0 if other == "lpsteps" else 0.0
            current = _floats_from_b64(controls.get(other, ""))
            controls.set(other, _b64_floats((current + [fill] * len(values))[:len(values)]))
            controls.set("steps", str(len(values)))
            applied[key] = values
            continue
        attr = aliases.get(key, key)
        if attr not in spec:
            valid = sorted(list(spec) + list(aliases) + ["wet", "enabled"])
            raise ValueError(f"Unknown setting '{key}' for {name}. Valid: {valid}")
        kind, _default, lo, hi = spec[attr]
        if kind != "bool" and not lo <= float(value) <= hi:
            raise ValueError(f"{name}.{attr} must be between {lo} and {hi} (got {value})")
        controls.set(attr, _fmt(kind, value))
        applied[attr] = value
    return {"effect": name, "applied": applied,
            "message": f"Updated {name}: " + ", ".join(f"{k}={v}" for k, v in applied.items())}


def remove_effect(parent: ET.Element, identifier: str | int) -> dict:
    """Remove an effect from a fxchain by name or position.

    Args:
        parent: Track or mixer channel element containing fxchain.
        identifier: Effect name (str) or chain position (int).

    Returns:
        Dict with result info.

    Raises:
        ValueError: If effect not found.
    """
    fxchain = parent.find("fxchain")
    if fxchain is None:
        raise ValueError("This target has no effect chain.")

    effects = fxchain.findall("effect")
    target = None
    if isinstance(identifier, int):
        if 0 <= identifier < len(effects):
            target = effects[identifier]
    else:
        for eff in effects:
            if eff.get("name", "").lower() == str(identifier).lower():
                target = eff
                break

    if target is None:
        names = [e.get("name", "?") for e in effects]
        raise ValueError(
            f"Effect '{identifier}' not found. Existing effects: {names}"
        )

    removed_name = target.get("name")
    fxchain.remove(target)
    remaining = fxchain.findall("effect")
    fxchain.set("numofeffects", str(len(remaining)))
    if len(remaining) == 0:
        fxchain.set("enabled", "0")

    return {
        "removed": removed_name,
        "chain_size": len(remaining),
        "message": f"Removed {removed_name} ({len(remaining)} effects remain)",
    }


def list_effects(parent: ET.Element) -> list[dict]:
    """List all effects in a fxchain element."""
    fxchain = parent.find("fxchain")
    if fxchain is None:
        return []
    result = []
    for pos, eff in enumerate(fxchain.findall("effect")):
        result.append({
            "position": pos,
            "name": eff.get("name", "unknown"),
            "enabled": eff.get("on", "1") == "1",
            "wet": float(eff.get("wet", "1")),
            "settings": _current_settings(eff),
        })
    return result


def _current_settings(eff: ET.Element) -> dict:
    name = eff.get("name", "")
    tag = KNOWN_EFFECTS.get(name, ("", ""))[1]
    controls = eff.find(tag) if tag else None
    if controls is None:
        return {}
    spec = EFFECT_PARAMS.get(name, {}).get("params", {})
    out = {}
    for attr, raw in controls.attrib.items():
        if attr in ("ampsteps", "lpsteps"):
            key = "echo_gains_db" if attr == "ampsteps" else "echo_lowpass"
            out[key] = [round(v, 3) for v in _floats_from_b64(raw)]
        elif attr == "waveShape":
            continue
        elif attr in spec and spec[attr][0] == "bool":
            out[attr] = raw == "1"
        else:
            try:
                out[attr] = float(raw)
            except ValueError:
                out[attr] = raw
    return out


def set_effect_enabled(parent: ET.Element, identifier: str | int, enabled: bool) -> dict:
    """Enable/disable an effect in a fxchain by name or position."""
    fxchain = parent.find("fxchain")
    if fxchain is None:
        raise ValueError("This target has no effect chain.")
    effects = fxchain.findall("effect")
    target = None
    if isinstance(identifier, int):
        if 0 <= identifier < len(effects):
            target = effects[identifier]
    else:
        for eff in effects:
            if eff.get("name", "").lower() == str(identifier).lower():
                target = eff
                break
    if target is None:
        raise ValueError(f"Effect '{identifier}' not found.")
    target.set("on", "1" if enabled else "0")
    return {
        "effect": target.get("name"),
        "enabled": enabled,
        "message": f"{target.get('name')} {'enabled' if enabled else 'disabled'}",
    }
