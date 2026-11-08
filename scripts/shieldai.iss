; Inno Setup script for ShieldAI - packages dist/shieldai.exe into a
; Start-Menu installer with an uninstaller. Build in CI:
;   choco install innosetup
;   iscc scripts/shieldai.iss
; Output: dist/ShieldAI-Setup-<ver>.exe

#define AppVer "1.0.0"
#ifexist "version.txt"
  #define AppVer FileOpen("version.txt") != -1 ? ReadFile("version.txt") : AppVer
#endif

[Setup]
AppName=ShieldAI
AppVersion={#AppVer}
AppPublisher=shizukutanaka
DefaultDirName={autopf}\ShieldAI
DefaultGroupName=ShieldAI
OutputDir=dist
OutputBaseFilename=ShieldAI-Setup-{#AppVer}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\shieldai.exe

[Files]
Source: "dist\shieldai.exe"; DestDir: "{app}"
Source: "dist\SHA256SUMS.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\ShieldAI"; Filename: "{app}\shieldai.exe"
Name: "{group}\Uninstall ShieldAI"; Filename: "{uninstallexe}"

[Run]
; launch the dashboard after install (frozen exe -> ui)
Filename: "{app}\shieldai.exe"; Description: "Start ShieldAI"; Flags: postinstall nowait skipifsilent
