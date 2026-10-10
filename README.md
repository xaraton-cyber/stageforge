<div align="center">

# 🎛️ Live Stems → B.Beat
### AI-assisted stem preparation for live bands

**v4.4.1 · Windows desktop · RoFormer by default · Demucs fallback**

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Platform](https://img.shields.io/badge/Platform-Windows-0078D4) ![Status](https://img.shields.io/badge/Status-Community%20preview-orange) ![Contributors](https://img.shields.io/badge/Contributors-Welcome-brightgreen)

*From a studio recording to synchronized, editable live-performance stems and click tracks.*

**[Getting started](docs/INSTALLATION.md) · [How it works](docs/ARCHITECTURE.md) · [Roadmap](ROADMAP.md) · [Contribute](CONTRIBUTING.md)**

</div>

---

## Why this project?

Live bands often need to preserve synths, pads, samples and other production layers while performing guitars, bass, drums and lead vocals themselves. This experimental desktop tool helps prepare separate, time-aligned audio tracks for an M-Live B.Beat-style live workflow.

## Features in v4.4.1

- **Six-stem separation:** vocals, drums, bass, guitar, piano and other (renamed **SYNTH_FX** for export)
- **RoFormer default**, optional Demucs alternative
- **BPM analysis and fine calibration** using the drum stem
- **Constant-tempo, phase-locked click** with editable first downbeat
- **Precount** and configurable meter/accent
- **48 kHz / 24-bit WAV** output, common start and duration across all seven tracks
- **Windows GUI** with waveform/grid inspection

## Output

```text
BBEAT_EXPORT/<SONG>_BBEAT_V441/
├── 01_<SONG>_SYNTH_FX.wav
├── 02_<SONG>_PIANO.wav
├── 03_<SONG>_GUITAR.wav
├── 04_<SONG>_BASS.wav
├── 05_<SONG>_DRUMS.wav
├── 06_<SONG>_VOCALS.wav
├── 07_<SONG>_CLICK.wav
└── INFO.txt
```

## Current scope

This repository intentionally preserves **only the v4.4.1 All Stems release**. It does **not** include later experiments, lead/rhythm guitar separation, cloud processing, payments, or MVSep integrations. This is a **community preview**, not a production-ready commercial service. The current code uses Windows-specific absolute paths under `C:\AI-Audio`.

## Join the project

We welcome contributors interested in DSP, Python desktop UX, GPU inference, music production, testing and documentation. Start with [CONTRIBUTING.md](CONTRIBUTING.md), open an issue describing your proposal, or share reproducible bug reports and test results. Please do not upload copyrighted recordings or stems to issues.

## Rights and model licensing

**Source code and model weights are separate assets.** This repository does not bundle AI checkpoints or third-party audio. In particular, the commercial-use rights for the community checkpoint `BS-Roformer-SW.ckpt` have not been established. Review the applicable model licenses and obtain permission where necessary. Process only audio you are authorized to use. **No open-source license has yet been granted for this project's own source code; contributions and redistribution require permission until a license is selected.** See [LEGAL.md](LEGAL.md).

