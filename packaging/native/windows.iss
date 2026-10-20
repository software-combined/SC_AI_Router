#define ResourcesDir "@RESOURCES@"
#define OutputDir "@OUTPUT@"
#define ProductVersion "@VERSION@"

[Setup]
AppId=SCG.Router.Installer
AppName=SCG Router
AppVersion={#ProductVersion}
DefaultDirName={localappdata}\Programs\SCG Router Installer
DefaultGroupName=SCG Router
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=SCG-Router-Installer-{#ProductVersion}-Windows
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=@ICON@
; Microsoft's licence requires users to accept terms protecting its runtime files.
LicenseFile=@TERMS@
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
Uninstallable=no

[Files]
Source: "{#ResourcesDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Install SCG Router"; Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\router\packaging\native_setup.py"" --resources ""{app}"""

[Run]
Filename: "{app}\runtime\python\pythonw.exe"; Parameters: """{app}\router\packaging\native_setup.py"" --resources ""{app}"""; Description: "Set up SCG Router"; Flags: postinstall skipifsilent

[Code]
procedure InitializeWizard;
begin
  WizardForm.Caption := 'SCG Router';
end;
