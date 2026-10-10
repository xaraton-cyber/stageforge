# Architecture — v4.4.1

```mermaid
flowchart TD
    A[User audio file] --> B[FFmpeg decode / preparation]
    B --> C{Separation engine}
    C -->|Default| D[BS-RoFormer-SW six stems]
    C -->|Fallback| E[Demucs]
    D --> F[Drums: tempo analysis]
    E --> F
    F --> G[Manual first downbeat + fixed BPM grid]
    G --> H[Phase-locked click + precount]
    D --> I[Aligned six-stem export]
    E --> I
    H --> J[48 kHz PCM24 live package]
    I --> J
```

The GUI is a single Python script (`live_stems_bbeat_v441_roformer_allstems.py`) using CustomTkinter and Matplotlib. Audio processing uses NumPy, librosa, SoundFile and FFmpeg. A constant-tempo beat grid is calibrated against drum transients; the user can correct the first downbeat. Export prepends the same precount to every stem and generates the click from the same time origin.

**Non-goals for this tagged version:** live/real-time source separation, lead/rhythm guitar splitting, cloud/API services, and tempo-map tracking of variable-tempo recordings.
