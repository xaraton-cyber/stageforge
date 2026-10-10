@echo off
title Live Stems B.Beat V4.4.1 - RoFormer All Stems
cd /d C:\AI-Audio

if not exist "C:\AI-Audio\demucs-env\Scripts\python.exe" (
    echo ERRORE: non trovo C:\AI-Audio\demucs-env\Scripts\python.exe
    pause
    exit /b 1
)

"C:\AI-Audio\demucs-env\Scripts\python.exe" "C:\AI-Audio\live_stems_bbeat_v441_roformer_allstems.py"
pause
