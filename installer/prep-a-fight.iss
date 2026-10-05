; Windows installer for prep-a-fight, built by tools/build-installer.ps1 (Inno Setup 6).
; It installs for the current user only (no admin rights): an embedded Python (python.org's own build) with the
; app and its libraries, Start menu and desktop shortcuts, and an uninstaller. SimulationCraft and the player's
; data stay in %USERPROFILE%\.paf: the app downloads simc on first launch, and uninstalling keeps the data.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F0B3C1E-4D2A-4C7B-9E1F-2B8C5A7D3E90}
AppName=prep-a-fight
AppVersion={#AppVersion}
AppVerName=prep-a-fight {#AppVersion}
AppPublisher=prep-a-fight contributors
AppPublisherURL=https://github.com/emmanuel-lena/prep-a-fight
AppSupportURL=https://github.com/emmanuel-lena/prep-a-fight/issues
DefaultDirName={localappdata}\Programs\prep-a-fight
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile=..\src\paf\assets\prep-a-fight.ico
UninstallDisplayIcon={app}\prep-a-fight.ico
UninstallDisplayName=prep-a-fight
OutputDir=..\dist
OutputBaseFilename=prep-a-fight-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoDescription=prep-a-fight installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; an upgrade replaces the libraries instead of mixing two versions
Type: filesandordirs; Name: "{app}\python"

[Icons]
Name: "{autoprograms}\prep-a-fight"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m paf.desktop"; \
  WorkingDir: "{userdocs}"; IconFilename: "{app}\prep-a-fight.ico"; AppUserModelID: "prep-a-fight.app"; \
  Comment: "Prepare a boss fight"
Name: "{autodesktop}\prep-a-fight"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m paf.desktop"; \
  WorkingDir: "{userdocs}"; IconFilename: "{app}\prep-a-fight.ico"; AppUserModelID: "prep-a-fight.app"; \
  Comment: "Prepare a boss fight"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-m paf.desktop"; WorkingDir: "{userdocs}"; \
  Description: "{cm:LaunchProgram,prep-a-fight}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; bytecode Python writes next to the libraries at run time
Type: filesandordirs; Name: "{app}\python"
