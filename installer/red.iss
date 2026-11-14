; Inno Setup script for Red. Compiled by installer\build.ps1:
;   ISCC /DAppVersion=0.1.0 /DStage=<staged files> /DOutDir=<output folder> red.iss
; Per-user, no admin: everything goes to %LOCALAPPDATA%\Red (Red's RED_HOME, so its models, memory and
; settings live there too). The models are not in the installer; Red downloads them on first run.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Stage
  #error Pass /DStage=<folder with python and app>
#endif
#ifndef OutDir
  #define OutDir "out"
#endif

[Setup]
AppId={{8F3C2B1E-6A41-4D0C-9C55-52E0D4A7B3A1}
AppName=Red
AppVersion={#AppVersion}
AppPublisher=Red
AppPublisherURL=https://github.com/AryanLanke/Red
DefaultDirName={localappdata}\Red
DefaultGroupName=Red
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=Red-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Red
LicenseFile={#Stage}\app\LICENSE
CloseApplications=no
RestartApplications=no
UsePreviousTasks=yes

[Tasks]
Name: "startup"; Description: "Start Red when I sign in to Windows"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Put a Red icon on the desktop"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#Stage}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Red"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m red.app.launch"; WorkingDir: "{app}\app"; Comment: "Start Red (sets Red up the first time)"
Name: "{autoprograms}\Red settings"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m red --home ""{app}"" app"; WorkingDir: "{app}\app"; Comment: "Companions, voice and everything else Red can be set to"
Name: "{autodesktop}\Red"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m red.app.launch"; WorkingDir: "{app}\app"; Tasks: desktopicon

[Run]
; Start with Windows: the sign-in shortcut Red makes itself (red startup on).
Filename: "{app}\python\pythonw.exe"; Parameters: "-m red --home ""{app}"" startup on"; WorkingDir: "{app}\app"; Flags: runhidden; Tasks: startup
Filename: "{app}\python\pythonw.exe"; Parameters: "-m red.app.launch"; WorkingDir: "{app}\app"; Description: "Set up Red now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Stop Red and remove its sign-in shortcut before the files go.
Filename: "{app}\python\pythonw.exe"; Parameters: "-m red --home ""{app}"" stop"; WorkingDir: "{app}\app"; Flags: runhidden; RunOnceId: "StopRed"
Filename: "{app}\python\pythonw.exe"; Parameters: "-m red --home ""{app}"" startup off"; WorkingDir: "{app}\app"; Flags: runhidden; RunOnceId: "StartupOff"

[UninstallDelete]
; What Red wrote inside its own program folders (compiled files and the like).
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[Code]
// Your memory, settings and downloaded models are yours: ask before deleting them. A silent uninstall keeps
// them unless it is run with /DELETEDATA=1.
const
  UserFolders = 'memory;config;models;companions;sounds;cache;logs;bin;searxng;plugins;worktrees';

function DataExists(): Boolean;
begin
  Result := DirExists(ExpandConstant('{app}\memory')) or DirExists(ExpandConstant('{app}\models')) or
            DirExists(ExpandConstant('{app}\config'));
end;

procedure DeleteUserData();
var
  Rest, Name: String;
  P: Integer;
begin
  Rest := UserFolders;
  while Rest <> '' do begin
    P := Pos(';', Rest);
    if P = 0 then begin
      Name := Rest;
      Rest := '';
    end else begin
      Name := Copy(Rest, 1, P - 1);
      Rest := Copy(Rest, P + 1, Length(Rest));
    end;
    DelTree(ExpandConstant('{app}\') + Name, True, True, True);
  end;
  DeleteFile(ExpandConstant('{app}\.installed'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Delete: Boolean;
begin
  if (CurUninstallStep = usPostUninstall) and DataExists() then begin
    if UninstallSilent then
      Delete := ExpandConstant('{param:DELETEDATA|0}') = '1'
    else
      Delete := MsgBox('Keep your memory, settings, companions and downloaded models?' + #13#10 + #13#10 +
                       'Yes keeps them in ' + ExpandConstant('{app}') + ' so a later install picks up where ' +
                       'you left off.' + #13#10 + 'No deletes all of it.',
                       mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDNO;
    if Delete then begin
      DeleteUserData();
      RemoveDir(ExpandConstant('{app}'));
    end;
  end;
end;
