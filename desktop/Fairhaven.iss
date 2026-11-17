#ifndef Payload
  #error Payload directory is required
#endif
#ifndef Output
  #error Output directory is required
#endif
#ifndef AwsMsi
  #error AwsMsi is required
#endif
[Setup]
AppId={{FA130012-2012-4E50-A1AA-6F6E6C696E65}
AppName=Fairhaven Private Racing
AppVersion=2.1.0
AppPublisher=Fairhaven Community
DefaultDirName={localappdata}\Programs\Fairhaven
DefaultGroupName=Fairhaven Private Racing
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Output}
OutputBaseFilename=setup
SetupIconFile={#Payload}\Fairhaven.ico
UninstallDisplayIcon={app}\Fairhaven.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
LicenseFile={#Payload}\source\LICENSE
InfoAfterFile={#Payload}\Start here.txt
DisableProgramGroupPage=yes
CloseApplications=no

[Types]
Name: full; Description: "Host and player (both apps)"
Name: player; Description: "Player only (for friends)"
Name: custom; Description: "Choose components"; Flags: iscustom

[Components]
Name: player; Description: "Player launcher, local save backups and identity tools"; Types: full player custom; Flags: fixed
Name: host; Description: "Server controller, AWS hosting and host prerequisites"; Types: full

[Tasks]
Name: desktopicon; Description: "Create desktop shortcuts"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#Payload}\NFS13Player.exe"; DestDir: "{app}"; Components: player; Flags: ignoreversion
Source: "{#Payload}\NFS13ServerControl.exe"; DestDir: "{app}"; Components: host; Flags: ignoreversion
Source: "{#Payload}\Fairhaven.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Payload}\Start here.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Payload}\source\*"; DestDir: "{app}\source"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Payload}\source\install\setup_prereqs.ps1"; DestDir: "{app}\install"; Components: host; Flags: ignoreversion
Source: "{#AwsMsi}"; DestDir: "{tmp}"; DestName: "AWSCLIV2.msi"; Components: host; Check: NeedsAWS; Flags: deleteafterinstall

[Icons]
Name: "{group}\Fairhaven Player"; Filename: "{app}\NFS13Player.exe"; Components: player
Name: "{group}\Fairhaven Server Control"; Filename: "{app}\NFS13ServerControl.exe"; Components: host
Name: "{group}\Uninstall Fairhaven"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Fairhaven Player"; Filename: "{app}\NFS13Player.exe"; Tasks: desktopicon; Components: player
Name: "{autodesktop}\Fairhaven Server Control"; Filename: "{app}\NFS13ServerControl.exe"; Tasks: desktopicon; Components: host

[Run]
Filename: "{code:NativePowerShell}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install\setup_prereqs.ps1"" -AwsInstaller ""{tmp}\AWSCLIV2.msi"""; Description: "Set up AWS CLI and OpenSSH"; Components: host; Check: NeedsHostTools; Verb: runas; Flags: shellexec waituntilterminated
Filename: "{app}\NFS13Player.exe"; Description: "Open Fairhaven Player"; Components: player; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\NFS13ServerControl.exe"; Parameters: "--setup"; Description: "Set up your AWS server"; Components: host; Flags: nowait postinstall skipifsilent

[Code]
function NativeSystemFile(const RelativePath: String): String;
begin
  Result := ExpandConstant('{sys}') + '\' + RelativePath;
  if IsWin64 and FileExists(ExpandConstant('{sysnative}') + '\' + RelativePath) then
    Result := ExpandConstant('{sysnative}') + '\' + RelativePath;
end;

function NativePowerShell(Param: String): String;
begin
  Result := NativeSystemFile('WindowsPowerShell\v1.0\powershell.exe');
end;

function NeedsAWS: Boolean;
begin
  Result := not (FileExists(ExpandConstant('{localappdata}\Programs\Amazon\AWSCLIV2\aws.exe')) or
                 FileExists(ExpandConstant('{pf}\Amazon\AWSCLIV2\aws.exe')));
end;

function NeedsHostTools: Boolean;
begin
  Result := NeedsAWS or not FileExists(NativeSystemFile('OpenSSH\ssh.exe'));
  Log(Format('Host prerequisite installation needed: %d', [Ord(Result)]));
end;
