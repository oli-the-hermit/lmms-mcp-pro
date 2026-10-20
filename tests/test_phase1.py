"""Phase 1 regression tests: file format for LMMS 1.2 + 1.3, effects, ZynAddSubFX, plugins.

The first part is pure Python. The second part renders projects with real LMMS
binaries and measures the audio; it runs only when they are available:

    LMMS_TEST_BINARIES="lmms12,lmms13" pytest tests/test_phase1.py

Each entry is a command that accepts ``render <project> -o <wav> -f wav``
(for example a wrapper that runs ``lmms --allowroot`` with ``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import wave
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from lmms_mcp import dialect
from lmms_mcp.effects import add_effect, list_effects, set_effect_params
from lmms_mcp.project import LMMSProject
from lmms_mcp.xml_parser import (
    add_instrument_track,
    add_mixer_channel,
    add_note_to_track,
    add_sample_clip,
    add_sample_track,
    create_empty_project,
    embed_zyn_preset,
    find_tracks,
    load_project_with_dialect,
    save_project,
    set_instrument_params,
)


# ───────────────────────────── file format ─────────────────────────────

def _saved_xml(root: ET.Element, tmp_path: Path, dialect_name: str = "legacy") -> ET.Element:
    path = tmp_path / "p.mmp"
    save_project(path, root, compressed=False, dialect=dialect_name)
    return ET.parse(path).getroot()


class TestLegacyFormat:
    def test_notes_are_written_with_lmms12_numbering(self, tmp_path):
        root = create_empty_project()
        add_instrument_track(root, "Lead")
        add_note_to_track(root, 0, key=69)            # MIDI A4
        out = _saved_xml(root, tmp_path)
        assert out.find(".//note").get("key") == "57"  # LMMS 1.2 A4
        assert out.find(".//instrumenttrack").get("basenote") == "57"

    def test_in_memory_tree_is_not_changed_by_saving(self, tmp_path):
        root = create_empty_project()
        add_instrument_track(root, "Lead")
        add_note_to_track(root, 0, key=69)
        _saved_xml(root, tmp_path)
        assert root.find(".//note").get("key") == "69"
        assert root.find("song/mixer") is not None

    def test_mixer_and_routing_use_lmms12_names(self, tmp_path):
        root = create_empty_project()
        add_mixer_channel(root, "Bus")
        add_instrument_track(root, "Lead", mixer_channel=1)
        out = _saved_xml(root, tmp_path)
        assert out.find("song/fxmixer") is not None
        assert out.find("song/mixer") is None
        assert len(out.findall("song/fxmixer/fxchannel")) == 2
        inst = out.find(".//instrumenttrack")
        assert inst.get("fxch") == "1" and inst.get("mixch") is None

    def test_sample_clips_use_lmms12_tag(self, tmp_path):
        root = create_empty_project()
        add_sample_track(root, "Kick")
        add_sample_clip(root, 0, "drums/kick01.ogg", 0, 192)
        out = _saved_xml(root, tmp_path)
        assert out.find(".//sampletco") is not None
        assert out.find(".//sampleclip") is None

    def test_renamed_instruments_use_lmms12_names(self, tmp_path):
        root = create_empty_project()
        add_instrument_track(root, "GB", instrument="freeboy")
        add_instrument_track(root, "FM", instrument="opulenz")
        out = _saved_xml(root, tmp_path)
        names = [i.get("name") for i in out.iter("instrument")]
        assert names == ["papu", "OPL2"]
        assert out.find(".//papu") is not None and out.find(".//OPL2") is not None

    def test_stamped_so_lmms13_upgrades_it(self, tmp_path):
        out = _saved_xml(create_empty_project(), tmp_path)
        assert out.get("version") == "1.0"
        assert out.get("creatorversion") == "1.2.2"   # below 1.3.0 => 1.3 runs its upgrades

    def test_roundtrip_restores_internal_form(self, tmp_path):
        root = create_empty_project()
        add_mixer_channel(root, "Bus")
        add_instrument_track(root, "GB", instrument="freeboy", mixer_channel=1)
        add_note_to_track(root, 0, key=60)
        path = tmp_path / "rt.mmpz"
        save_project(path, root)
        loaded, found = load_project_with_dialect(path)
        assert found == "legacy"
        assert loaded.find(".//note").get("key") == "60"
        assert loaded.find(".//instrumenttrack").get("mixch") == "1"
        assert loaded.find(".//instrument").get("name") == "freeboy"


class TestModernAndOldFiles:
    MODERN = """<?xml version="1.0"?><lmms-project type="song" version="31" creator="LMMS"
      creatorversion="1.3.0-alpha.2"><head bpm="120"/><song>
      <trackcontainer type="song"><track type="0" name="Lead"><instrumenttrack mixch="1" basenote="69">
      <instrument name="tripleoscillator"><tripleoscillator/></instrument></instrumenttrack>
      <midiclip pos="0" len="192" type="1"><note pos="0" key="69" len="12" type="1"/></midiclip>
      </track></trackcontainer><mixer><mixerchannel num="0" name="Master"/></mixer></song></lmms-project>"""

    OLD_MCP = """<?xml version="1.0"?><lmms-project version="1.0" creator="LMMS MCP Server"
      creatorversion="1.2.0" type="song"><head bpm="140"/><song><trackcontainer type="song">
      <track type="0" name="Lead"><instrumenttrack mixch="0" basenote="57">
      <instrument name="tripleoscillator"><tripleoscillator/></instrument></instrumenttrack>
      <pattern pos="0" len="192" type="1"><note pos="0" key="69" len="192"/></pattern>
      </track></trackcontainer><mixer><mixerchannel num="0" name="Master"/></mixer></song></lmms-project>"""

    def test_lmms13_file_loads_and_saves_back_as_13(self, tmp_path):
        src = tmp_path / "m.mmp"
        src.write_text(self.MODERN)
        proj = LMMSProject()
        proj.load(src)
        assert proj.dialect == "modern"
        note = proj.root.find(".//pattern/note")          # internal names
        assert note.get("key") == "69" and note.get("len") == "-192"
        out = tmp_path / "m2.mmp"
        proj.save(out, compressed=False)
        saved = ET.parse(out).getroot()
        assert saved.get("version") == "31"
        assert saved.find(".//midiclip/note").get("type") == "1"
        assert saved.find("song/mixer") is not None

    def test_file_from_original_lmms_mcp_keeps_its_notes(self, tmp_path):
        # It wrote MIDI keys with LMMS 1.2 base notes: only the base note is converted.
        src = tmp_path / "old.mmp"
        src.write_text(self.OLD_MCP)
        root, found = load_project_with_dialect(src)
        assert found == "legacy"
        assert root.find(".//note").get("key") == "69"
        assert root.find(".//instrumenttrack").get("basenote") == "69"
        out = _saved_xml(root, tmp_path)
        assert out.find(".//note").get("key") == "57"
        assert out.find(".//instrumenttrack").get("basenote") == "57"
        assert out.find("song/fxmixer") is not None

    def test_detect(self):
        assert dialect.detect(ET.fromstring(self.MODERN.split("?>", 1)[1])) == "modern"
        assert dialect.detect(ET.fromstring(self.OLD_MCP.split("?>", 1)[1])) == "legacy"


# ─────────────────────────────── effects ───────────────────────────────

def _track():
    root = create_empty_project()
    add_instrument_track(root, "Lead")
    return root, find_tracks(root)[0].find("instrumenttrack")


class TestEffects:
    def test_every_setting_is_written_with_long_autoquit(self):
        _, inst = _track()
        add_effect(inst, "reverbsc")
        eff = inst.find("fxchain/effect")
        assert eff.get("autoquit") == "8000"           # LMMS default 1 ms cuts tails
        ctrl = eff.find("ReverbSCControls")
        assert set(ctrl.attrib) == {"input_gain", "size", "color", "output_gain"}
        assert eff.find("key") is not None

    def test_default_wet_keeps_dry_signal_for_reverb_and_delay(self):
        _, inst = _track()
        add_effect(inst, "reverbsc")
        add_effect(inst, "delay")
        add_effect(inst, "bitcrush")
        wets = [e["wet"] for e in list_effects(inst)]
        assert wets == [0.3, 0.4, 1.0]

    def test_waveshaper_gets_its_curve(self):
        _, inst = _track()
        add_effect(inst, "waveshaper")
        assert inst.find(".//waveshapercontrols").get("waveShape")   # missing => garbage curve

    def test_set_params_with_aliases_and_ranges(self):
        _, inst = _track()
        add_effect(inst, "delay")
        set_effect_params(inst, "delay", {"time": 0.75, "feedback": 0.6, "wet": 0.5})
        ctrl = inst.find(".//Delay")
        assert ctrl.get("DelayTimeSamples") == "0.75" and ctrl.get("FeebackAmount") == "0.6"
        assert inst.find("fxchain/effect").get("wet") == "0.5"
        with pytest.raises(ValueError, match="between"):
            set_effect_params(inst, "delay", {"feedback": 2})
        with pytest.raises(ValueError, match="Unknown setting"):
            set_effect_params(inst, "delay", {"size": 1})

    def test_multitap_echo_graphs(self):
        _, inst = _track()
        add_effect(inst, "multitapecho", params={
            "echo_gains_db": [-6, -10, -14, -18], "echo_lowpass": [3, 2, 1, 0.5]})
        settings = list_effects(inst)[0]["settings"]
        assert settings["steps"] == 4.0
        assert settings["echo_gains_db"] == [-6.0, -10.0, -14.0, -18.0]
        assert settings["echo_lowpass"] == [3.0, 2.0, 1.0, 0.5]


# ───────────────────────────── ZynAddSubFX ─────────────────────────────

ZYN_XIZ = """<?xml version="1.0"?><ZynAddSubFX-data version-major="1"><INSTRUMENT>
<INFO><string name="name">TestPatch</string></INFO></INSTRUMENT></ZynAddSubFX-data>"""


class TestZyn:
    def test_preset_goes_into_master_part0(self):
        root = create_empty_project()
        add_instrument_track(root, "Z", instrument="zynaddsubfx")
        embed_zyn_preset(root, 0, ZYN_XIZ)
        zyn = root.find(".//instrument/zynaddsubfx")
        assert zyn.find("ZynAddSubFX-data/MASTER/PART[@id='0']/INSTRUMENT") is not None

    def test_knobs_are_marked_as_modified_controllers(self):
        root = create_empty_project()
        add_instrument_track(root, "Z", instrument="zynaddsubfx")
        set_instrument_params(root, 0, {"filterfreq": 20, "portamento": 10})
        zyn = root.find(".//instrument/zynaddsubfx")
        assert zyn.get("filterfreq") == "20"
        assert set(zyn.get("modifiedcontrollers").strip(",").split(",")) == {"74", "65"}


# ───────────────────────────── plugin list ─────────────────────────────

def test_plugin_classification_maps_lmms12_dll_names(tmp_path, monkeypatch):
    from lmms_mcp import lmms_app
    for dll in ("papu", "opl2", "reverbsc", "tripleoscillator", "carlarack", "midiimport",
                "spectrumanalyzer", "mystery"):
        (tmp_path / f"{dll}.dll").touch()
    monkeypatch.setattr(lmms_app, "get_plugins_dir", lambda: tmp_path)
    got = lmms_app.classify_installed_plugins(
        {"freeboy", "opulenz", "tripleoscillator"}, {"reverbsc"})
    assert got["instruments"] == ["opulenz", "freeboy", "tripleoscillator"]
    assert got["effects"] == ["reverbsc", "spectrumanalyzer"]
    assert got["hosts"] == ["carlarack"]
    assert got["other"] == ["midiimport"]
    assert got["unknown"] == ["mystery"]


# ─────────────────────── rendering with real LMMS ───────────────────────

BINARIES = [b for b in os.environ.get("LMMS_TEST_BINARIES", "").split(",") if b]
needs_lmms = pytest.mark.skipif(
    not BINARIES or not all(shutil.which(b) for b in BINARIES),
    reason="set LMMS_TEST_BINARIES to LMMS commands to run render tests")


def _render(binary: str, project: Path, tmp_path: Path):
    import numpy as np
    out = tmp_path / f"{binary}.wav"
    subprocess.run([binary, "render", str(project), "-o", str(out), "-f", "wav"],
                   capture_output=True, timeout=600, check=False)
    assert out.exists(), f"{binary} did not render {project}"
    with wave.open(str(out)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.reshape(-1, 2).astype(float).mean(1) / 32768, sr


def _pitch(signal, sr, t0=0.1, t1=0.9):
    import numpy as np
    seg = signal[int(t0 * sr):int(t1 * sr)] * np.hanning(int(t1 * sr) - int(t0 * sr))
    spec = np.abs(np.fft.rfft(seg, n=len(seg) * 8))
    freqs = np.fft.rfftfreq(len(seg) * 8, 1 / sr)
    mask = freqs > 20
    return float(freqs[mask][np.argmax(spec[mask])])


@needs_lmms
@pytest.mark.parametrize("binary", BINARIES)
class TestRendering:
    def _sine_project(self, tmp_path, channel_volume=1.0, effect=None, params=None):
        root = create_empty_project(bpm=120)
        add_mixer_channel(root, "Bus", volume=channel_volume)
        track = add_instrument_track(root, "Sine", mixer_channel=1)
        osc = track.find(".//tripleoscillator")
        osc.attrib.update({"wavetype0": "0", "vol0": "100", "vol1": "0", "vol2": "0"})
        add_note_to_track(root, 0, key=69, pos=0, length=12 if effect else 192)
        if effect:
            add_effect(track.find("instrumenttrack"), effect, params=params)
        path = tmp_path / "sine.mmp"
        save_project(path, root, compressed=False)
        return path

    def test_a4_is_440_hz(self, binary, tmp_path):
        sig, sr = _render(binary, self._sine_project(tmp_path), tmp_path)
        assert abs(_pitch(sig, sr) - 440) < 3

    def test_mixer_routing_is_honoured(self, binary, tmp_path):
        sig, _ = _render(binary, self._sine_project(tmp_path, channel_volume=0.0), tmp_path)
        assert abs(sig).max() < 1e-4

    def test_echo_tail_survives(self, binary, tmp_path):
        project = self._sine_project(tmp_path, effect="multitapecho", params={
            "steplength": 500, "echo_gains_db": [-6, -10, -14, -18]})
        sig, sr = _render(binary, project, tmp_path)
        assert abs(sig[int(1.0 * sr):int(1.2 * sr)]).max() > 0.05    # 2nd echo at 1.0 s
