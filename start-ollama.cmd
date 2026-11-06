@echo off
REM Start the local Ollama daemon for ShieldAI.
REM Portable install on D: (C: is nearly full); models also live on D:.
set OLLAMA_MODELS=D:\ollama\models
"D:\ollama\ollama.exe" serve
