# Installation (Windows, community preview)

This release reproduces the existing local workflow; it is **not yet a one-click installer**.

1. Install **Python 3.12**, **FFmpeg** (available in `PATH`), and a compatible NVIDIA CUDA/PyTorch stack if using GPU inference.
2. Create `C:\AI-Audio` and copy the two application files from the repository root there.
3. The supplied `.bat` launcher expects `C:\AI-Audio\demucs-env\Scripts\python.exe`. Create a Python 3.12 virtual environment at that path, then install the GUI/audio requirements:

   ```powershell
   py -3.12 -m venv C:\AI-Audio\demucs-env
   C:\AI-Audio\demucs-env\Scripts\python.exe -m pip install numpy soundfile librosa customtkinter matplotlib
   ```

4. Install and configure the separation engines separately. For RoFormer (default), the app expects `C:\AI-Audio\roformer-env\Scripts\audio-separator.exe` and the `BS-Roformer-SW.ckpt` model available to that engine. The Demucs fallback expects a compatible Demucs installation and its model dependencies. **Check each checkpoint's license independently.**
5. Run `AVVIA_LIVE_STEMS_BBEAT_V441_ROFORMER_ALLSTEMS.bat`.
6. Select an audio file, run the analysis, verify BPM/downbeat and export. Outputs are written under `C:\AI-Audio\BBEAT_EXPORT`.

**Known limitations:** Paths are hardcoded, CUDA/toolchain installation varies by GPU, third-party model availability may change, and the export should be auditioned before any live performance. The installation steps have not been verified as a clean-room setup.
