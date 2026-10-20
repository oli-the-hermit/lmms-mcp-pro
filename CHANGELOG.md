# Changelog

All notable changes to LMMS MCP Pro. Upstream history: [TypeWolf/lmms-mcp](https://github.com/TypeWolf/lmms-mcp).

## Unreleased

Every fix below was checked by rendering projects with real **LMMS 1.2.2 and LMMS 1.3.0-alpha.2**
and measuring the audio (pitch, level, silence, echo timing). `tests/test_phase1.py` repeats those
checks when `LMMS_TEST_BINARIES` points at LMMS.

### Fixed
- **Every note played one octave too high**, in LMMS 1.2 and 1.3. Tools keep using MIDI numbers
  (A4 = 69); files are now written in LMMS 1.2 numbering (A4 = 57), which LMMS 1.3 converts on load.
- **The mixer was invisible to LMMS 1.2**: channels, routing and mixer effects were written with
  LMMS 1.3 names (`mixer`, `mixerchannel`, `mixch`) and silently dropped. Projects are now saved in
  LMMS 1.2 format (`fxmixer`, `fxchannel`, `fxch`), which LMMS 1.3 upgrades automatically.
- **Sample clips vanished in LMMS 1.2** (`sampleclip` is the 1.3 name; 1.2 uses `sampletco`).
- **FreeBoy and OpulenZ tracks were missing in LMMS 1.2**, which knows them as `papu` and `OPL2`.
- **Echo, delay and reverb tails were cut off**: effects were written with LMMS's 1 ms auto-quit.
  They now use 8000 ms.
- **Effects were written with empty settings**, so LMMS filled in odd values (a waveshaper loaded a
  garbage curve). Every setting is now written with its real LMMS default.
- **ZynAddSubFX presets had no effect**: the preset sat where LMMS never reads it. It now goes into
  the plugin's own data, and `set_zyn_params` knobs are marked as modified so LMMS applies them.
- **Instrument envelope and arpeggiator settings used wrong names** (`attack`, `decay`, `amount`,
  `arpspeed`…); now the names LMMS reads (`att`, `dec`, `amt`, `arptime`…).
- **`list_available_plugins` offered LMMS 1.3-only plugins on LMMS 1.2**, and called `opl2` / `papu`
  "custom". It now lists what your LMMS can use, what needs 1.3, and the plugin hosts separately.

### Added
- **Effect settings**: `describe_effect` (every setting with default and range), `set_effect_params`
  (validated against LMMS's own ranges, with friendly aliases such as `time` / `feedback` for Delay,
  and `echo_gains_db` / `echo_lowpass` lists for Multitap Echo), and `params` on `add_effect`.
- Sensible default **dry/wet** per effect (reverb 0.3, delay 0.4, flanger 0.5) instead of fully wet.
- Effects on **sample tracks**.
- **Projects saved by LMMS 1.3 stay in 1.3 format** when loaded and saved again; projects written by
  the original LMMS MCP are recognised and their notes keep their pitch.
- Windows installer scripts, a desktop extension (`.mcpb`) build, and a stdio smoke test (`scripts/`).

### Changed
- The same effect can be added twice (two EQs, two reverbs), as LMMS allows; address them by position.
- Effect recommendations only suggest effects that exist in both LMMS 1.2 and 1.3.
