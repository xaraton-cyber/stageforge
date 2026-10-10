import os
import math
import sys
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa
import customtkinter as ctk
from tkinter import filedialog, messagebox

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

APP = "Live Stems → B.Beat V4.4.1 — ROFORMER DEFAULT • ALL STEMS • PHASE LOCKED"
TARGET_SR = 48000
ONSET_HOP = 128

def fmt(sec):
    if sec is None:
        return "-"
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m:02d}:{s:06.3f}"

def safe(p):
    return Path(p).stem.replace("\\", "_").replace("/", "_")

def robust_grid_score(onset_env, sr, hop, duration, t0, bpm, tolerance_s=0.030):
    """Score a CONSTANT quarter-note grid against drum transients."""
    period = 60.0 / bpm
    k0 = math.ceil((0.0 - t0) / period)
    k1 = math.floor((duration - t0) / period)
    if k1 < k0:
        return -1e9

    ks = np.arange(k0, k1 + 1, dtype=np.int64)
    ts = t0 + ks * period
    idx = np.rint(ts * sr / hop).astype(np.int64)

    radius = max(1, int(round(tolerance_s * sr / hop)))
    vals = np.empty(len(idx), dtype=np.float32)

    n = len(onset_env)
    for j, i in enumerate(idx):
        lo = max(0, int(i) - radius)
        hi = min(n, int(i) + radius + 1)
        vals[j] = float(np.max(onset_env[lo:hi])) if hi > lo else 0.0

    if len(vals) < 8:
        return float(np.mean(vals)) if len(vals) else -1e9

    vals.sort()
    a = int(len(vals) * 0.10)
    b = max(a + 1, int(len(vals) * 0.90))
    return float(np.mean(vals[a:b]))

def calibrate_constant_bpm(onset_env, sr, hop, duration, t0, center_bpm):
    """Three-pass fine search for the fixed BPM that best fits the full drums track."""
    # Pass 1: broad search.
    lo = max(30.0, center_bpm - 3.0)
    hi = min(240.0, center_bpm + 3.0)
    cand1 = np.arange(lo, hi + 1e-9, 0.02)
    sc1 = np.array([robust_grid_score(onset_env, sr, hop, duration, t0, b, 0.035) for b in cand1])
    b1 = float(cand1[int(np.argmax(sc1))])

    # Pass 2.
    cand2 = np.arange(b1 - 0.10, b1 + 0.100001, 0.001)
    sc2 = np.array([robust_grid_score(onset_env, sr, hop, duration, t0, b, 0.028) for b in cand2])
    b2 = float(cand2[int(np.argmax(sc2))])

    # Pass 3.
    cand3 = np.arange(b2 - 0.006, b2 + 0.006001, 0.0001)
    sc3 = np.array([robust_grid_score(onset_env, sr, hop, duration, t0, b, 0.024) for b in cand3])
    best_i = int(np.argmax(sc3))
    b3 = float(cand3[best_i])

    # Simple confidence: compare best score to local competitors.
    best = float(sc3[best_i])
    p10 = float(np.percentile(sc3, 10))
    conf = max(0.0, min(100.0, 100.0 * (best - p10) / max(abs(best), 1e-6)))
    return b3, conf, best

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("1180x900")
        self.minsize(950, 720)

        self.source = None
        self.drums = None
        self.other = None
        self.y = None
        self.sr = None
        self.duration = 0.0
        self.onset_env = None
        self.raw_bpm = None
        self.t0 = None
        self.manual_t0 = False
        self.view_start = 0.0
        self.view_len = 20.0

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.build()

    def build(self):
        root = ctk.CTkScrollableFrame(self)
        root.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 0))
        root.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            root, text=APP, font=ctk.CTkFont(size=28, weight="bold")
        ).grid(row=0, column=0, pady=(8, 2))

        ctk.CTkLabel(
            root,
            text="Clock fisso • calibrazione BPM sull'intero drums.wav • griglia click visibile • precount senza tagliare intro",
        ).grid(row=1, column=0, pady=(0, 10))

        f = ctk.CTkFrame(root)
        f.grid(row=2, column=0, sticky="ew", padx=8, pady=5)
        f.grid_columnconfigure(1, weight=1)

        self.srcv = ctk.StringVar()
        self.stemv = ctk.StringVar()

        ctk.CTkLabel(f, text="Brano").grid(row=0, column=0, padx=10, pady=7, sticky="w")
        ctk.CTkEntry(f, textvariable=self.srcv).grid(row=0, column=1, padx=10, pady=7, sticky="ew")
        ctk.CTkButton(f, text="Scegli brano", command=self.pick_source).grid(row=0, column=2, padx=10, pady=7)

        ctk.CTkLabel(f, text="Cartella stems").grid(row=1, column=0, padx=10, pady=7, sticky="w")
        ctk.CTkEntry(f, textvariable=self.stemv).grid(row=1, column=1, padx=10, pady=7, sticky="ew")
        ctk.CTkButton(f, text="Scegli stems", command=self.pick_stems).grid(row=1, column=2, padx=10, pady=7)

        a = ctk.CTkFrame(root)
        a.grid(row=3, column=0, sticky="ew", padx=8, pady=5)
        for i in range(4):
            a.grid_columnconfigure(i, weight=1)

        ctk.CTkButton(a, text="1. ANALIZZA DRUMS", command=self.analyze).grid(row=0, column=0, padx=5, pady=9, sticky="ew")
        ctk.CTkButton(a, text="2. CALIBRA BPM", command=self.calibrate).grid(row=0, column=1, padx=5, pady=9, sticky="ew")
        ctk.CTkButton(a, text="3. CREA TEST CLICK", command=self.test).grid(row=0, column=2, padx=5, pady=9, sticky="ew")
        ctk.CTkButton(a, text="4. CREA PER B.BEAT", command=self.export).grid(row=0, column=3, padx=5, pady=9, sticky="ew")

        g = ctk.CTkFrame(root)
        g.grid(row=4, column=0, sticky="ew", padx=8, pady=5)
        g.grid_columnconfigure(1, weight=1)

        self.rawv = ctk.StringVar(value="-")
        self.bpmv = ctk.StringVar(value="")
        self.t0v = ctk.StringVar(value="-")
        self.confv = ctk.StringVar(value="-")

        ctk.CTkLabel(g, text="BPM preliminare").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkLabel(g, textvariable=self.rawv).grid(row=0, column=1, padx=10, pady=6, sticky="w")

        ctk.CTkLabel(g, text="BPM usato").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        br = ctk.CTkFrame(g, fg_color="transparent")
        br.grid(row=1, column=1, padx=10, pady=6, sticky="w")
        self.bpme = ctk.CTkEntry(br, textvariable=self.bpmv, width=130)
        self.bpme.pack(side="left", padx=(0, 6))
        self.bpme.bind("<Return>", lambda e: self.redraw())
        self.bpme.bind("<FocusOut>", lambda e: self.redraw())
        ctk.CTkButton(br, text="Aggiorna griglia", width=120, command=self.redraw).pack(side="left", padx=3)
        ctk.CTkButton(br, text="x2", width=45, command=lambda: self.scale(2)).pack(side="left", padx=3)
        ctk.CTkButton(br, text="/2", width=45, command=lambda: self.scale(.5)).pack(side="left", padx=3)

        ctk.CTkLabel(g, text="Calibrazione").grid(row=2, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkLabel(g, textvariable=self.confv).grid(row=2, column=1, padx=10, pady=6, sticky="w")

        ctk.CTkLabel(g, text="Primo UNO").grid(row=3, column=0, padx=10, pady=6, sticky="w")
        r2 = ctk.CTkFrame(g, fg_color="transparent")
        r2.grid(row=3, column=1, padx=10, pady=6, sticky="w")
        ctk.CTkLabel(r2, textvariable=self.t0v, width=100).pack(side="left")
        ctk.CTkButton(r2, text="-10 ms", width=70, command=lambda: self.nudge(-.010)).pack(side="left", padx=3)
        ctk.CTkButton(r2, text="+10 ms", width=70, command=lambda: self.nudge(.010)).pack(side="left", padx=3)

        ctk.CTkLabel(g, text="Misura").grid(row=4, column=0, padx=10, pady=6, sticky="w")
        self.meterv = ctk.StringVar(value="4/4")
        ctk.CTkOptionMenu(
            g, values=["4/4", "3/4"], variable=self.meterv,
            command=lambda _: (self.refresh_accent(), self.redraw())
        ).grid(row=4, column=1, padx=10, pady=6, sticky="w")

        ctk.CTkLabel(g, text="Accento").grid(row=5, column=0, padx=10, pady=6, sticky="w")
        ar = ctk.CTkFrame(g, fg_color="transparent")
        ar.grid(row=5, column=1, padx=10, pady=6, sticky="w")
        self.acc_on = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(ar, text="ON", variable=self.acc_on, command=self.redraw).pack(side="left", padx=(0, 8))
        self.accpos = ctk.StringVar(value="1")
        self.accmenu = ctk.CTkOptionMenu(
            ar, values=["1", "2", "3", "4"], variable=self.accpos,
            width=70, command=lambda _: self.redraw()
        )
        self.accmenu.pack(side="left")

        ctk.CTkLabel(g, text="Precount").grid(row=6, column=0, padx=10, pady=6, sticky="w")
        self.pre = ctk.StringVar(value="3")
        ctk.CTkOptionMenu(g, values=["1", "2", "3", "4"], variable=self.pre, width=70).grid(row=6, column=1, padx=10, pady=6, sticky="w")

        q = ctk.CTkFrame(root)
        q.grid(row=5, column=0, sticky="ew", padx=8, pady=5)
        q.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(q, text="Motore separazione").grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.enginev = ctk.StringVar(value="RoFormer (consigliato)")
        ctk.CTkOptionMenu(
            q, values=["RoFormer (consigliato)", "Demucs (vecchio)"], variable=self.enginev, width=220
        ).grid(row=0, column=1, padx=10, pady=8, sticky="w")
        ctk.CTkLabel(
            q,
            text="RoFormer BS-RoFormer-SW è il default. Demucs resta disponibile come fallback. Gli stems già creati vengono riutilizzati.",
        ).grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        w = ctk.CTkFrame(root)
        w.grid(row=6, column=0, sticky="ew", padx=8, pady=5)
        w.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            w,
            text="WAVEFORM DRUMS + GRIGLIA CLICK — clicca un transiente che sia il PRIMO UNO",
        ).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")

        self.fig = Figure(figsize=(10.5, 3.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Analizza drums.wav")
        self.canvas = FigureCanvasTkAgg(self.fig, master=w)
        self.canvas.get_tk_widget().grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.canvas.mpl_connect("button_press_event", self.wave_click)

        nr = ctk.CTkFrame(w, fg_color="transparent")
        nr.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        for txt, cmd in [
            ("◀ 10 s", lambda: self.move(-10)),
            ("10 s ▶", lambda: self.move(10)),
            ("INIZIO", lambda: self.goto(0)),
            ("METÀ", lambda: self.goto(max(0.0, self.duration / 2.0 - self.view_len / 2.0))),
            ("FINE", lambda: self.goto(max(0.0, self.duration - self.view_len))),
        ]:
            ctk.CTkButton(nr, text=txt, width=80, command=cmd).pack(side="left", padx=3)

        ctk.CTkLabel(
            w,
            text="Linee sottili = beat • linee più marcate = accento/battuta • linea molto marcata = UNO manuale",
        ).grid(row=3, column=0, padx=10, pady=(0, 8), sticky="w")

        self.log = ctk.CTkTextbox(root, height=120)
        self.log.grid(row=7, column=0, sticky="ew", padx=8, pady=(5, 12))
        self.write("Pronto.")

        foot = ctk.CTkFrame(self)
        foot.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        foot.grid_columnconfigure(0, weight=1)
        self.prog = ctk.CTkProgressBar(foot)
        self.prog.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        self.prog.set(0)
        self.status = ctk.StringVar(value="Pronto.")
        ctk.CTkLabel(foot, textvariable=self.status).grid(row=1, column=0, sticky="w", padx=10, pady=(2, 8))

    def write(self, s):
        self.log.insert("end", str(s) + "\n")
        self.log.see("end")

    def pick_source(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio", "*.flac *.wav *.mp3 *.mpeg *.m4a *.ogg"), ("Tutti", "*.*")]
        )
        if p:
            self.source = Path(p)
            self.srcv.set(p)
            # Reset song-specific analysis. Stems will be found/created automatically by ANALIZZA.
            self.drums = None
            self.other = None
            self.y = None
            self.onset_env = None
            self.raw_bpm = None
            self.t0 = None
            self.manual_t0 = False
            self.t0v.set("-")
            self.rawv.set("-")
            self.confv.set("-")
            self.stemv.set("")
            self.write(f"Brano selezionato: {self.source}")
            self.write("Premi ANALIZZA DRUMS: RoFormer è predefinito; gli stems esistenti vengono riutilizzati automaticamente.")

    def pick_stems(self):
        d = filedialog.askdirectory(title="Cartella con drums.wav e other.wav")
        if not d:
            return
        d = Path(d)
        dr = d / "drums.wav"
        ot = d / "other.wav"
        if not dr.exists() or not ot.exists():
            messagebox.showerror("Stems", "La cartella deve contenere drums.wav e other.wav.")
            return

        # New stems = new song analysis.
        if self.drums is None or dr.resolve() != self.drums.resolve():
            self.t0 = None
            self.manual_t0 = False
            self.raw_bpm = None
            self.onset_env = None

        self.drums = dr
        self.other = ot
        self.stemv.set(str(d))
        self.write(f"drums: {dr}")
        self.write(f"other: {ot}")

    def ensure_demucs_stems(self):
        """Find/create legacy Demucs htdemucs_ft stems."""
        if not self.source:
            raise ValueError("Prima scegli il brano originale.")

        # Preferred/current automatic output root.
        roots = [
            Path(r"C:\AI-Audio\gui_separated"),
            Path(r"C:\AI-Audio\separated"),
            Path(r"C:\AI-Audio\separated_cut"),
        ]

        # Search exact/common Demucs output locations first.
        candidates = []
        for root in roots:
            candidates.append(root / "htdemucs_ft" / self.source.stem)

        # Also accept an already selected valid stem folder.
        if self.stemv.get().strip():
            candidates.insert(0, Path(self.stemv.get().strip()))

        for folder in candidates:
            if (folder / "drums.wav").exists() and (folder / "other.wav").exists():
                self.drums = folder / "drums.wav"
                self.other = folder / "other.wav"
                self.stemv.set(str(folder))
                self.write(f"Stems esistenti riutilizzati: {folder}")
                return folder

        # No usable stems: create htdemucs_ft automatically.
        outroot = Path(r"C:\AI-Audio\gui_separated")
        outroot.mkdir(parents=True, exist_ok=True)

        exe = shutil.which("demucs")
        if exe:
            cmd = [
                exe, "-n", "htdemucs_ft", "-d", "cuda",
                "--shifts", "5", "--overlap", "0.5", "--float32",
                "-o", str(outroot), str(self.source),
            ]
        else:
            cmd = [
                sys.executable, "-m", "demucs",
                "-n", "htdemucs_ft", "-d", "cuda",
                "--shifts", "5", "--overlap", "0.5", "--float32",
                "-o", str(outroot), str(self.source),
            ]

        self.status.set("Stems non trovati: separazione htdemucs_ft alta qualità…")
        self.prog.set(.05)
        self.write("Stems non presenti. Avvio automaticamente Demucs htdemucs_ft…")
        self.write("Comando: " + " ".join(f'"{x}"' if " " in str(x) else str(x) for x in cmd))
        self.update_idletasks()

        subprocess.run(cmd, check=True)

        folder = outroot / "htdemucs_ft" / self.source.stem
        if not (folder / "drums.wav").exists() or not (folder / "other.wav").exists():
            raise RuntimeError(
                "Demucs ha terminato, ma non trovo drums.wav/other.wav in:\n" + str(folder)
            )

        self.drums = folder / "drums.wav"
        self.other = folder / "other.wav"
        self.stemv.set(str(folder))
        self.write(f"Separazione completata: {folder}")
        return folder

    def roformer_folder(self):
        """Create/reuse canonical 6-stem BS-RoFormer-SW output."""
        if not self.source:
            raise ValueError("Prima scegli il brano originale.")

        folder = Path(r"C:\AI-Audio\roformer_stems") / self.source.stem
        required = ["vocals.wav", "drums.wav", "bass.wav", "guitar.wav", "piano.wav", "other.wav"]
        if all((folder / x).exists() for x in required):
            self.write(f"RoFormer: riutilizzo 6 stems esistenti: {folder}")
            return folder

        sep = Path(r"C:\AI-Audio\roformer-env\Scripts\audio-separator.exe")
        if not sep.exists():
            raise RuntimeError(
                "RoFormer non installato. Non trovo:\n" + str(sep) +
                "\nSeleziona Demucs oppure ripristina roformer-env."
            )
        folder.mkdir(parents=True, exist_ok=True)

        # Decode to a plain WAV first: avoids MP3-in-.mpeg and attached-cover quirks.
        clean = folder / "_MASTER_48K.wav"
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg non trovato nel PATH.")
        if not clean.exists():
            self.status.set("RoFormer: preparo MASTER WAV 48 kHz…")
            self.update_idletasks()
            subprocess.run([
                ffmpeg, "-y", "-i", str(self.source), "-map", "0:a:0", "-vn",
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(clean)
            ], check=True)

        self.status.set("RoFormer BS-RoFormer-SW: separazione 6 stems su GPU…")
        self.prog.set(.05)
        self.write("Avvio RoFormer BS-RoFormer-SW (6 stems)…")
        self.update_idletasks()
        subprocess.run([
            str(sep), str(clean), "-m", "BS-Roformer-SW.ckpt",
            "--output_dir", str(folder), "--output_format", "WAV", "--use_autocast"
        ], check=True)

        # audio-separator names files with the stem name in parentheses.
        # Normalize them once to the canonical names used by the rest of this app.
        aliases = {
            "vocals": "vocals.wav", "drums": "drums.wav", "bass": "bass.wav",
            "guitar": "guitar.wav", "piano": "piano.wav", "other": "other.wav"
        }
        for wav in folder.glob("*.wav"):
            if wav.name == clean.name or wav.name.lower() in aliases.values():
                continue
            low = wav.name.lower()
            for token, canon in aliases.items():
                if f"({token})" in low or f"_{token}_" in low or low.startswith(token + "_"):
                    shutil.copy2(wav, folder / canon)
                    break

        missing = [x for x in required if not (folder / x).exists()]
        if missing:
            found = "\n".join(x.name for x in folder.glob("*.wav"))
            raise RuntimeError(
                "RoFormer ha terminato ma non riesco a normalizzare questi stems: " +
                ", ".join(missing) + "\n\nWAV trovati:\n" + found
            )
        self.write(f"RoFormer completato: {folder}")
        return folder

    def ensure_stems(self):
        """Use the engine selected in the GUI; RoFormer is the default."""
        if self.enginev.get().startswith("RoFormer"):
            folder = self.roformer_folder()
            self.drums = folder / "drums.wav"
            self.other = folder / "other.wav"
        else:
            folder = self.ensure_demucs_stems()
        self.stemv.set(str(folder))
        return folder

    def analyze(self):
        try:
            if not self.drums:
                self.ensure_stems()

            self.status.set("Analisi drums ad alta risoluzione…")
            self.prog.set(.10)
            self.update_idletasks()

            y, sr = librosa.load(str(self.drums), sr=None, mono=True)
            self.y = y
            self.sr = sr
            self.duration = len(y) / sr

            self.onset_env = librosa.onset.onset_strength(
                y=y, sr=sr, hop_length=ONSET_HOP
            )

            # Coarse estimate only; fine value comes from CALIBRA BPM.
            tempo = librosa.feature.tempo(
                onset_envelope=self.onset_env,
                sr=sr,
                hop_length=ONSET_HOP,
                aggregate=np.median,
            )
            self.raw_bpm = float(np.asarray(tempo).reshape(-1)[0])

            # Keep common half-time rock range practical.
            if self.raw_bpm > 150:
                self.raw_bpm /= 2.0
            elif self.raw_bpm < 55:
                self.raw_bpm *= 2.0

            self.rawv.set(f"{self.raw_bpm:.6f}")
            self.bpmv.set(f"{self.raw_bpm:.6f}")
            self.confv.set("Preliminare — scegli l'UNO e premi CALIBRA BPM")

            # Auto UNO is only a suggestion and never overwrites a manually selected UNO.
            if self.t0 is None:
                _, frames = librosa.beat.beat_track(
                    onset_envelope=self.onset_env,
                    sr=sr,
                    hop_length=ONSET_HOP,
                    trim=False,
                    bpm=self.raw_bpm,
                )
                beats = librosa.frames_to_time(frames, sr=sr, hop_length=ONSET_HOP)
                self.t0 = float(beats[0]) if len(beats) else 0.0
                self.manual_t0 = False

            self.t0v.set(fmt(self.t0))
            self.write(f"BPM preliminare drums: {self.raw_bpm:.6f}")
            self.write("Scegli un UNO chiaro sulla waveform, poi premi CALIBRA BPM.")
            self.redraw()
            self.prog.set(1)
            self.status.set("Analisi completata. Ora scegli l'UNO e calibra il BPM.")
        except Exception as e:
            messagebox.showerror("Analisi", str(e))
            self.prog.set(0)

    def calibrate(self):
        try:
            if self.onset_env is None or self.y is None:
                raise ValueError("Prima esegui ANALIZZA DRUMS.")
            if self.t0 is None:
                raise ValueError("Prima scegli il PRIMO UNO sulla waveform.")

            try:
                center = self.bpm()
            except Exception:
                center = self.raw_bpm

            self.status.set("Calibrazione BPM sull'intero brano…")
            self.prog.set(.20)
            self.update_idletasks()

            best, conf, score = calibrate_constant_bpm(
                self.onset_env, self.sr, ONSET_HOP,
                self.duration, self.t0, center
            )

            self.bpmv.set(f"{best:.4f}")
            self.confv.set(f"BPM fisso {best:.4f} • indice {conf:.1f}%")
            self.write(f"CALIBRAZIONE: BPM fisso = {best:.4f} | score={score:.4f} | indice={conf:.1f}%")
            self.write("Il valore è ottenuto cercando la griglia costante che meglio coincide coi transienti sull'intero drums.wav.")
            self.redraw()
            self.prog.set(1)
            self.status.set("Calibrazione completata. Controlla INIZIO / METÀ / FINE.")
        except Exception as e:
            messagebox.showerror("Calibrazione", str(e))
            self.prog.set(0)

    def bpm(self):
        try:
            b = float(self.bpmv.get().replace(",", "."))
        except Exception:
            raise ValueError("BPM non valido")
        if not 20 <= b <= 300:
            raise ValueError("BPM fuori intervallo")
        return b

    def scale(self, f):
        try:
            self.bpmv.set(f"{self.bpm() * f:.6f}")
            self.redraw()
        except Exception as e:
            messagebox.showerror("BPM", str(e))

    def nudge(self, d):
        if self.t0 is None:
            return
        self.t0 = max(0.0, self.t0 + d)
        self.manual_t0 = True
        self.t0v.set(fmt(self.t0))
        self.redraw()

    def refresh_accent(self):
        vals = ["1", "2", "3"] if self.meterv.get() == "3/4" else ["1", "2", "3", "4"]
        self.accmenu.configure(values=vals)
        if self.accpos.get() not in vals:
            self.accpos.set("1")

    def bpb(self):
        return 3 if self.meterv.get() == "3/4" else 4

    def accented(self, k):
        return self.acc_on.get() and (k % self.bpb() == int(self.accpos.get()) - 1)

    def redraw(self):
        if self.y is None:
            return

        st = max(0.0, min(self.view_start, max(0.0, self.duration - self.view_len)))
        en = min(self.duration, st + self.view_len)

        i0 = int(st * self.sr)
        i1 = int(en * self.sr)
        seg = self.y[i0:i1]
        step = max(1, len(seg) // 7000)
        ys = seg[::step]
        xs = st + np.arange(len(ys)) * step / self.sr

        self.ax.clear()
        self.ax.plot(xs, ys, linewidth=.65)
        self.ax.set_xlim(st, en)
        self.ax.set_xlabel("secondi")
        self.ax.set_title("DRUMS + griglia del CLICK")

        if self.t0 is not None:
            try:
                b = self.bpm()
                p = 60.0 / b
                k0 = math.floor((st - self.t0) / p)
                k1 = math.ceil((en - self.t0) / p)

                for k in range(k0, k1 + 1):
                    t = self.t0 + k * p
                    if st <= t <= en:
                        if self.accented(k):
                            self.ax.axvline(t, linewidth=1.35, alpha=.78)
                        else:
                            self.ax.axvline(t, linewidth=.55, alpha=.48)
            except Exception:
                pass

            if st <= self.t0 <= en:
                self.ax.axvline(self.t0, linewidth=2.4, alpha=.95)

        self.fig.tight_layout()
        self.canvas.draw_idle()

    def wave_click(self, e):
        if self.y is None or e.inaxes != self.ax or e.xdata is None:
            return
        self.t0 = max(0.0, min(float(e.xdata), self.duration))
        self.manual_t0 = True
        self.t0v.set(fmt(self.t0))
        self.write(f"Primo UNO manuale: {self.t0:.6f} s")
        self.redraw()

    def goto(self, x):
        if self.y is None:
            return
        self.view_start = max(0.0, min(float(x), max(0.0, self.duration - self.view_len)))
        self.redraw()

    def move(self, d):
        self.goto(self.view_start + d)

    @staticmethod
    def add_click(buf, sr, t, accent):
        i = int(round(t * sr))
        if i < 0 or i >= len(buf):
            return
        n = min(int(.045 * sr), len(buf) - i)
        tt = np.arange(n, dtype=np.float32) / sr
        freq = 1800.0 if accent else 900.0
        amp = .85 if accent else .50
        buf[i:i+n] += np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 65) * amp

    def add_countin(self, buf, sr, bars, bpm):
        """Count-in pulito: ogni battuta parte sempre da 1."""
        period = 60.0 / bpm
        for bar in range(bars):
            for beat in range(self.bpb()):
                self.add_click(buf, sr, (bar*self.bpb()+beat)*period, beat == 0)

    def add_song_start_cue(self, buf, sr, t):
        """Cue distinto esattamente all'inizio del file originale."""
        i = int(round(t*sr))
        if i < 0 or i >= len(buf): return
        n = min(int(.075*sr), len(buf)-i)
        tt = np.arange(n, dtype=np.float32)/sr
        buf[i:i+n] += ((.72*np.sin(2*np.pi*2400*tt)+.28*np.sin(2*np.pi*1200*tt))*np.exp(-tt*48)).astype(np.float32)

    def grid(self, duration, t0=None):
        b = self.bpm()
        anchor = self.t0 if t0 is None else t0
        if anchor is None:
            raise ValueError("Imposta il primo UNO")
        p = 60.0 / b
        k0 = math.floor((0.0 - anchor) / p)
        k1 = math.ceil((duration - anchor) / p)
        ks = np.arange(k0, k1 + 1, dtype=int)
        ts = anchor + ks * p
        m = (ts >= 0.0) & (ts < duration)
        return ts[m], ks[m]

    def test(self):
        try:
            if not self.source:
                raise ValueError("Scegli il brano")
            if self.t0 is None:
                raise ValueError("Imposta il primo UNO")

            self.status.set("Creo test click…")
            self.prog.set(.25)
            self.update_idletasks()

            # Robust source decode. Some MPEG/MP3 files and some FLAC cuts can
            # trigger libsndfile "Internal psf_fseek() failed". First try
            # soundfile; if it cannot seek/decode, use FFmpeg to a temporary WAV.
            try:
                yy, sr = sf.read(str(self.source), always_2d=True, dtype="float32")
            except Exception as first_error:
                temp_dir = Path(r"C:\AI-Audio\temp")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_wav = temp_dir / f"{safe(self.source)}_V42_DECODE.wav"
                ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
                cmd = [
                    ffmpeg, "-y", "-v", "error",
                    "-i", str(self.source),
                    "-vn", "-c:a", "pcm_f32le",
                    str(temp_wav)
                ]
                self.write(f"Decoder audio diretto non disponibile ({first_error}). Uso FFmpeg…")
                subprocess.run(cmd, check=True)
                yy, sr = sf.read(str(temp_wav), always_2d=True, dtype="float32")

            # Internal layout used by the click mixer: channels x samples.
            y = yy.T
            if y.shape[0] == 1:
                y = np.vstack([y, y])
            elif y.shape[0] > 2:
                y = y[:2, :]

            # TEST V4.2.2: include lo stesso PRECOUNT dell'export B.Beat.
            # Non si taglia l'intro del brano: si aggiunge il count-in davanti.
            b = self.bpm()
            period = 60.0 / b
            bars = int(self.pre.get())
            pre_duration = bars * self.bpb() * period
            pad_samples = int(round(pre_duration * sr))

            # Source audio starts only after the full precount.
            padded_y = np.pad(
                y.astype(np.float32),
                ((0, 0), (pad_samples, 0)),
                mode="constant"
            )

            total_n = padded_y.shape[-1]
            total_dur = total_n / sr

            # PHASE-LOCKED GRID:
            # the manually selected song downbeat (t0) is the absolute musical anchor.
            # Generate the SAME mathematical grid backward through the precount and
            # forward through the complete song. No restart at source start.
            shifted_t0 = pre_duration + self.t0
            c = np.zeros(total_n, dtype=np.float32)
            period = 60.0 / b
            k0 = math.ceil((0.0 - shifted_t0) / period)
            k1 = math.floor((total_dur - shifted_t0) / period)
            for k in range(k0, k1 + 1):
                t = shifted_t0 + k * period
                if t < -1e-9:
                    continue
                # k=0 is the chosen musical UNO; multiples of the meter are bar 1s.
                self.add_click(c, sr, float(t), self.accented(int(k)))

            mix = padded_y * .58 + np.vstack([c, c]) * .42
            pk = np.max(np.abs(mix))
            if pk > .99:
                mix *= .99 / pk

            outd = Path(r"C:\AI-Audio\tests")
            outd.mkdir(parents=True, exist_ok=True)
            out = outd / f"{safe(self.source)}_PHASE_LOCKED_CLICK_V44.wav"
            sf.write(out, mix.T, sr, subtype="PCM_24")

            self.write(
                f"Test con precount: {out} | "
                f"{bars} battute = {pre_duration:.3f}s | "
                f"UNO nel test = {shifted_t0:.3f}s"
            )
            self.prog.set(1)
            self.status.set("Test con precount creato.")
            if os.name == "nt":
                os.startfile(str(out))
        except Exception as e:
            messagebox.showerror("Test", str(e))
            self.prog.set(0)

    def demucs6_folder(self):
        if not self.source:
            raise ValueError("Scegli il brano originale.")

        root = Path(r"C:\AI-Audio\separated_6s")
        folder = root / "htdemucs_6s" / self.source.stem
        if (folder / "other.wav").exists():
            self.write(f"Riutilizzo 6 stems: {folder}")
            return folder

        root.mkdir(parents=True, exist_ok=True)

        exe = shutil.which("demucs")
        if exe:
            cmd = [
                exe, "-n", "htdemucs_6s", "-d", "cuda",
                "--shifts", "5", "--overlap", "0.5", "--float32",
                "-o", str(root), str(self.source),
            ]
        else:
            cmd = [
                sys.executable, "-m", "demucs",
                "-n", "htdemucs_6s", "-d", "cuda",
                "--shifts", "5", "--overlap", "0.5", "--float32",
                "-o", str(root), str(self.source),
            ]

        self.write("Avvio htdemucs_6s alta qualità per FX puliti…")
        self.status.set("Separazione htdemucs_6s… può richiedere alcuni minuti.")
        self.update_idletasks()
        subprocess.run(cmd, check=True)

        required = ["other.wav", "piano.wav", "guitar.wav", "bass.wav", "drums.wav", "vocals.wav"]
        missing = [name for name in required if not (folder / name).exists()]
        if missing:
            raise RuntimeError("Separazione HQ incompleta. Mancano: " + ", ".join(missing))

        # Verify the processing stems. Demucs --float32 should generate FLOAT WAVs.
        try:
            inf = sf.info(str(folder / "other.wav"))
            self.write(f"HQ other.wav: {inf.samplerate} Hz • {inf.subtype}")
        except Exception:
            pass
        return folder

    @staticmethod
    def resample_2d(a, sr):
        if sr == TARGET_SR:
            return a.astype(np.float32), sr
        channels = [
            librosa.resample(
                a[:, i], orig_sr=sr, target_sr=TARGET_SR, res_type="soxr_hq"
            )
            for i in range(a.shape[1])
        ]
        m = min(map(len, channels))
        return np.column_stack([x[:m] for x in channels]).astype(np.float32), TARGET_SR

    def export_track_with_pad(self, src, out, pad_samples):
        a, sr = sf.read(str(src), always_2d=True, dtype="float32")
        a, sr = self.resample_2d(a, sr)
        a = np.vstack([np.zeros((pad_samples, a.shape[1]), dtype=np.float32), a])
        sf.write(out, a, sr, subtype="PCM_24")
        return len(a), sr

    def export(self):
        try:
            if not self.other:
                raise ValueError("Scegli la cartella stems")
            if self.t0 is None:
                raise ValueError("Imposta il primo UNO")

            b = self.bpm()
            p = 60.0 / b
            bars = int(self.pre.get())
            pre_duration = bars * self.bpb() * p
            pad = pre_duration

            self.status.set("Creo export B.Beat completo…")
            self.prog.set(.15)
            self.update_idletasks()

            use_roformer = self.enginev.get().startswith("RoFormer")
            stem_folder = self.roformer_folder() if use_roformer else self.demucs6_folder()

            # Export ALL 6 stems into the SAME B.Beat folder.
            # 'other' is renamed SYNTH_FX for clarity.
            sources = [
                ("SYNTH_FX", stem_folder / "other.wav"),
                ("PIANO", stem_folder / "piano.wav"),
                ("GUITAR", stem_folder / "guitar.wav"),
                ("BASS", stem_folder / "bass.wav"),
                ("DRUMS", stem_folder / "drums.wav"),
                ("VOCALS", stem_folder / "vocals.wav"),
            ]
            missing = [str(path) for _, path in sources if not path.exists()]
            if missing:
                raise FileNotFoundError("Mancano stem 6-stem:\n" + "\n".join(missing))

            # SYNTH_FX establishes exact common output duration after resampling.
            fx_a, fx_sr = sf.read(str(sources[0][1]), always_2d=True, dtype="float32")
            fx_a, fx_sr = self.resample_2d(fx_a, fx_sr)
            pn = int(round(pad * fx_sr))
            fx = np.vstack([np.zeros((pn, fx_a.shape[1]), dtype=np.float32), fx_a])
            target_len = len(fx)

            shifted_t0 = pad + self.t0
            c = np.zeros(target_len, dtype=np.float32)
            total_dur = target_len / fx_sr
            k0 = math.ceil((0.0 - shifted_t0) / p)
            k1 = math.floor((total_dur - shifted_t0) / p)
            for k in range(k0, k1 + 1):
                t = shifted_t0 + k * p
                if t < -1e-9:
                    continue
                self.add_click(c, fx_sr, float(t), self.accented(int(k)))

            song = safe(self.source or self.other).upper()
            od = Path(r"C:\AI-Audio\BBEAT_EXPORT") / f"{song}_BBEAT_V441"
            od.mkdir(parents=True, exist_ok=True)

            # 01..06 = all RoFormer/Demucs stems, 07 = click.
            # Every file gets exactly the same leading precount and total length.
            for idx, (label, path) in enumerate(sources, start=1):
                if label == "SYNTH_FX":
                    x = fx
                    xsr = fx_sr
                else:
                    x, xsr = sf.read(str(path), always_2d=True, dtype="float32")
                    x, xsr = self.resample_2d(x, xsr)
                    if xsr != fx_sr:
                        raise RuntimeError(f"Sample-rate alignment error: {label}")
                    x = np.vstack([np.zeros((pn, x.shape[1]), dtype=np.float32), x])
                    if len(x) < target_len:
                        x = np.vstack([x, np.zeros((target_len-len(x), x.shape[1]), dtype=np.float32)])
                    elif len(x) > target_len:
                        x = x[:target_len]
                sf.write(od / f"{idx:02d}_{song}_{label}.wav", x, xsr, subtype="PCM_24")
                self.prog.set(.15 + .65 * (idx / len(sources)))
                self.update_idletasks()

            sf.write(od / f"07_{song}_CLICK.wav", c, fx_sr, subtype="PCM_24")

            info = (
                f"{APP}\n"
                f"BPM_FIXED={b:.6f}\n"
                f"FIRST_ONE_SOURCE={self.t0:.6f}\n"
                f"FIRST_ONE_EXPORT={shifted_t0:.6f}\n"
                f"METER={self.meterv.get()}\n"
                f"ACCENT={'ON' if self.acc_on.get() else 'OFF'} {self.accpos.get()}\n"
                f"PRECOUNT_BARS={bars}\n"
                f"PREPENDED_SILENCE={pad:.6f}\n"
                f"FORMAT=PCM24 48000Hz\n"
                f"STEM_ENGINE={'RoFormer BS-RoFormer-SW 6-stem' if use_roformer else 'Demucs htdemucs_6s'}\n"
                f"TRACKS=01 SYNTH_FX(other); 02 PIANO; 03 GUITAR; 04 BASS; 05 DRUMS; 06 VOCALS; 07 CLICK\n"
                f"ALL_TRACKS_SAME_PRECOUNT_AND_LENGTH=YES\n"
            )
            (od / "INFO.txt").write_text(info, encoding="utf-8")

            self.write(f"Export completo: {od}")
            self.write(f"Precount: {pad:.3f} s | UNO export: {shifted_t0:.3f} s")
            self.write("Esportati nella stessa cartella: SYNTH_FX, PIANO, GUITAR, BASS, DRUMS, VOCALS, CLICK.")

            self.prog.set(1)
            self.status.set("Export B.Beat completo.")
            if os.name == "nt":
                os.startfile(str(od))
        except Exception as e:
            messagebox.showerror("Export", str(e))
            self.prog.set(0)

if __name__ == "__main__":
    App().mainloop()
