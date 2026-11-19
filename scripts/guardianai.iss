; Inno Setup script for GuardianAI - packages dist/guardianai.exe into a
; Start-Menu installer with an uninstaller. Build in CI:
;   choco install innosetup
;   iscc scripts/guardianai.iss
; Output: dist/GuardianAI-Setup-<ver>.exe

#define AppVer "1.0.0"
#ifexist "version.txt"
  #define AppVer FileOpen("version.txt") != -1 ? ReadFile("version.txt") : AppVer
#endif

[Setup]
; AppId stays the pre-rename name so the installer upgrades an
; existing ShieldAI install in place instead of installing a second copy.
AppId=ShieldAI
AppName=GuardianAI
AppVersion={#AppVer}
AppPublisher=shizukutanaka
DefaultDirName={autopf}\GuardianAI
DefaultGroupName=GuardianAI
; paths resolve relative to THIS script's directory - dist/ lives at
; the repo root, one level up.
OutputDir=..\dist
OutputBaseFilename=GuardianAI-Setup-{#AppVer}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\guardianai.exe

[Files]
Source: "..\dist\guardianai.exe"; DestDir: "{app}"
Source: "..\dist\SHA256SUMS.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\GuardianAI"; Filename: "{app}\guardianai.exe"
Name: "{group}\Uninstall GuardianAI"; Filename: "{uninstallexe}"

[Run]
; launch the dashboard after install (frozen exe -> ui)
Filename: "{app}\guardianai.exe"; Description: "Start GuardianAI"; Flags: postinstall nowait skipifsilent
