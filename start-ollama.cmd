@echo off
REM Start the local Ollama daemon for ShieldAI.
REM Portable install on D: (C: is nearly full); models also live on D:.
set OLLAMA_MODELS=D:\ollama\models
set OLLAMA_KEEP_ALIVE=24h
"D:\ollama\ollama.exe" serve
