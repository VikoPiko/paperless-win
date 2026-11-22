; paperless-win installer (Inno Setup 6). Built by windows\build\build.ps1:
;   ISCC /DAppVersion=<ver> /DStageDir=<dist\stage\app> /DOutputDir=<dist> paperless-win.iss
;
; The staged app has no virtual environment. This script creates it on the target machine from the
; bundled wheelhouse (no network), writes paperless.conf with `paperless-ctl setup`, initialises the
; database with `paperless-ctl init`, and registers the Windows service. All real logic lives in
; paperless-ctl (src\paperless_win), so it is tested in Python, not here.
;
; Silent install (used by tests and for deployment), all optional:
;   paperless-win-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /DATADIR=D:\paperless /CONSUMEDIR=D:\inbox
;       /ADMINUSER=admin /ADMINPASSWORD=secret /PORT=8000 /LANGS=deu,fra /TASKS="firewall,ailocal"
;       /NOSERVICE   (do not register the Windows service)   /DELETEDATA (uninstall: also delete the data)
;   Non-administrators can test with /CURRENTUSER together with /NOSERVICE.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef StageDir
  #error StageDir must be defined (the staged app folder made by build.ps1)
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef Compression
  #define Compression "lzma2/max"
#endif

[Setup]
AppId={{B7F0C1D2-3A44-4E5B-9C61-7D2E8A5F1B09}
AppName=paperless-win
AppVersion={#AppVersion}
AppPublisher=paperless-win (unofficial port, not affiliated with paperless-ngx)
AppPublisherURL=https://github.com/VikoPiko/paperless-win
AppSupportURL=https://github.com/VikoPiko/paperless-win/issues
DefaultDirName={autopf}\paperless-win
DefaultGroupName=paperless-win
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile={#StageDir}\..\LICENSE-installer.txt
OutputDir={#OutputDir}
OutputBaseFilename=paperless-win-setup-{#AppVersion}
Compression={#Compression}
SolidCompression=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=paperless-win (unofficial paperless-ngx for Windows)
SetupIconFile=paperless-win.ico
UninstallDisplayIcon={app}\paperless-win.ico
SetupLogging=yes
CloseApplications=no
RestartApplications=no
VersionInfoVersion=0.0.0.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "firewall"; Description: "Let other computers on the network open paperless-win (opens the web port in Windows Firewall, private and domain networks only)"; Flags: unchecked
Name: "ailocal"; Description: "Local AI add-on: embeddings that run on this computer (downloads about 600 MB, needs internet access during setup)"; Flags: unchecked

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "paperless-win.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; an upgrade replaces the code and rebuilds the venv; configuration and data live outside {app}
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\wheelhouse"
Type: filesandordirs; Name: "{app}\bin"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\service"
Type: files; Name: "{app}\paperless-win.url"
Type: files; Name: "{app}\install.log"

[INI]
Filename: "{app}\paperless-win.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{code:GetPort}/"

[Icons]
Name: "{autoprograms}\paperless-win"; Filename: "{app}\paperless-win.url"; IconFilename: "{app}\paperless-win.ico"; Comment: "Open paperless-win in your browser"
Name: "{autoprograms}\paperless-win folder of documents to import"; Filename: "{code:GetConsumeDir}"

[Registry]
Root: HKLM; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey; Check: IsAdminInstallMode
Root: HKLM; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "ConsumeDir"; ValueData: "{code:GetConsumeDir}"; Check: IsAdminInstallMode
Root: HKLM; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "Port"; ValueData: "{code:GetPort}"; Check: IsAdminInstallMode
Root: HKCU; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey; Check: not IsAdminInstallMode
Root: HKCU; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "ConsumeDir"; ValueData: "{code:GetConsumeDir}"; Check: not IsAdminInstallMode
Root: HKCU; Subkey: "Software\paperless-win"; ValueType: string; ValueName: "Port"; ValueData: "{code:GetPort}"; Check: not IsAdminInstallMode

[Run]
Filename: "http://localhost:{code:GetPort}/"; Description: "Open paperless-win in the browser"; Flags: shellexec postinstall skipifsilent nowait

[Code]
// ---- Windows API used for the child environment -------------------------------------------------
function SetEnvironmentVariable(lpName, lpValue: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';
procedure ExitProcess(ExitCode: Cardinal);
  external 'ExitProcess@kernel32.dll stdcall';

const
  LangCount = 5;

var
  DirPage: TInputDirWizardPage;
  AdminPage: TInputQueryWizardPage;
  LangPage: TInputOptionWizardPage;
  Upgrading: Boolean;
  PreviousVersion: String;
  StoredDataDir, StoredConsumeDir, StoredPort: String;

function LangCode(Index: Integer): String;
begin
  case Index of
    0: Result := 'deu';
    1: Result := 'fra';
    2: Result := 'spa';
    3: Result := 'ita';
    4: Result := 'nld';
  end;
end;

function CmdParam(const Name, Default: String): String;
var
  I: Integer;
  S, Prefix: String;
begin
  Result := Default;
  Prefix := '/' + Uppercase(Name) + '=';
  for I := 1 to ParamCount do
  begin
    S := ParamStr(I);
    if Pos(Prefix, Uppercase(S)) = 1 then
    begin
      Result := Copy(S, Length(Prefix) + 1, MaxInt);
      Exit;
    end;
  end;
end;

function RegRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKLM else Result := HKCU;
end;

function ReadStored(const Name: String; var Value: String): Boolean;
begin
  Result := RegQueryStringValue(RegRoot, 'Software\paperless-win', Name, Value);
end;

// ---- values chosen in the wizard (or read back on upgrade) -------------------------------------------------------
function GetDataDir(Param: String): String;
begin
  if Upgrading and (StoredDataDir <> '') then Result := StoredDataDir
  else Result := RemoveBackslashUnlessRoot(DirPage.Values[0]);
end;

function GetConsumeDir(Param: String): String;
begin
  if Upgrading and (StoredConsumeDir <> '') then Result := StoredConsumeDir
  else if Trim(DirPage.Values[1]) <> '' then Result := RemoveBackslashUnlessRoot(DirPage.Values[1])
  else Result := GetDataDir('') + '\consume';
end;

function GetPort(Param: String): String;
begin
  if Upgrading and (StoredPort <> '') then Result := StoredPort
  else Result := Trim(AdminPage.Values[3]);
  if Result = '' then Result := '8000';
end;

function SelectedLanguages: String;
var
  I: Integer;
  Cmd: String;
begin
  Result := 'eng';
  Cmd := ',' + CmdParam('LANGS', '') + ',';
  for I := 0 to LangCount - 1 do
    if LangPage.Values[I] or (Pos(',' + LangCode(I) + ',', Cmd) > 0) then
      Result := Result + '+' + LangCode(I);
end;

// ---- wizard pages --------------------------------------------------------------------------------------------------------------------
procedure InitializeWizard;
var
  I: Integer;
  Cmd, Finished: String;
begin
  // an upgrade is an earlier install that ran to the end: a first install that failed half-way
  // (registry values are written before the set-up steps run) starts over, so the account is created
  Upgrading := ReadStored('DataDir', StoredDataDir) and ReadStored('Complete', Finished) and (Finished = '1');
  if Upgrading then
  begin
    ReadStored('ConsumeDir', StoredConsumeDir);
    ReadStored('Port', StoredPort);
  end;

  DirPage := CreateInputDirPage(wpSelectDir, 'Data folder',
    'Where should paperless-win keep your documents?',
    'The database, your documents, the search index and the logs are stored here. Choose a drive with enough free space.',
    False, 'New Folder');
  DirPage.Add('Data folder:');
  DirPage.Add('Consume folder (files you put here are imported automatically):');
  DirPage.Values[0] := CmdParam('DATADIR', ExpandConstant('{commonappdata}\paperless-win'));
  DirPage.Values[1] := CmdParam('CONSUMEDIR', DirPage.Values[0] + '\consume');

  AdminPage := CreateInputQueryPage(DirPage.ID, 'Administrator account',
    'Create the account you will sign in with.',
    'The password is only used to create the account and is not stored in the configuration.');
  AdminPage.Add('User name:', False);
  AdminPage.Add('Password (at least 8 characters):', True);
  AdminPage.Add('Repeat password:', True);
  AdminPage.Add('Web port:', False);
  AdminPage.Values[0] := CmdParam('ADMINUSER', 'admin');
  AdminPage.Values[1] := CmdParam('ADMINPASSWORD', '');
  AdminPage.Values[2] := CmdParam('ADMINPASSWORD', '');
  AdminPage.Values[3] := CmdParam('PORT', '8000');

  LangPage := CreateInputOptionPage(AdminPage.ID, 'OCR languages',
    'Which languages are your documents in?',
    'English is always installed. Tick any other language you need; more can be added later by copying .traineddata files into the tessdata folder.',
    False, False);
  LangPage.Add('German (deu)');
  LangPage.Add('French (fra)');
  LangPage.Add('Spanish (spa)');
  LangPage.Add('Italian (ita)');
  LangPage.Add('Dutch (nld)');
  Cmd := ',' + CmdParam('LANGS', '') + ',';
  for I := 0 to LangCount - 1 do
    LangPage.Values[I] := Pos(',' + LangCode(I) + ',', Cmd) > 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // an upgrade keeps the folders, account, port and languages chosen the first time
  Result := Upgrading and ((PageID = DirPage.ID) or (PageID = AdminPage.ID) or (PageID = LangPage.ID));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Port: Integer;
begin
  Result := True;
  if CurPageID = AdminPage.ID then
  begin
    if Trim(AdminPage.Values[0]) = '' then
    begin
      MsgBox('Please enter a user name.', mbError, MB_OK);
      Result := False;
    end
    else if Length(AdminPage.Values[1]) < 8 then
    begin
      MsgBox('The password must have at least 8 characters.', mbError, MB_OK);
      Result := False;
    end
    else if AdminPage.Values[1] <> AdminPage.Values[2] then
    begin
      MsgBox('The two passwords are not the same.', mbError, MB_OK);
      Result := False;
    end
    else
    begin
      Port := StrToIntDef(Trim(AdminPage.Values[3]), 0);
      if (Port < 1) or (Port > 65535) then
      begin
        MsgBox('The web port must be a number between 1 and 65535.', mbError, MB_OK);
        Result := False;
      end;
    end;
  end;
end;

// ---- running tools ---------------------------------------------------------------------------------------------------------------------------
function InstallLog: String;
begin
  Result := GetDataDir('') + '\logs\install.log';
end;

// Runs exe with output appended to the install log. Returns the exit code (-1 if it did not start).
function RunLogged(const Exe, Params, Title: String): Integer;
var
  Code: Integer;
begin
  WizardForm.StatusLabel.Caption := Title;
  WizardForm.FilenameLabel.Caption := '';
  SaveStringToFile(InstallLog, #13#10 + '=== ' + Title + #13#10, True);
  if Exec(ExpandConstant('{cmd}'),
          '/S /C ""' + Exe + '" ' + Params + ' >> "' + InstallLog + '" 2>&1"',
          ExpandConstant('{app}\src'), SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := Code
  else
    Result := -1;
  SaveStringToFile(InstallLog, 'exit code ' + IntToStr(Result) + #13#10, True);
end;

// A message box that a silent install skips (it is written to the install log either way).
procedure Tell(const Text: String; Kind: TMsgBoxType);
begin
  SaveStringToFile(InstallLog, Text + #13#10, True);
  if not WizardSilent then MsgBox(Text, Kind, MB_OK);
end;

procedure Fail(const What: String);
begin
  Tell('paperless-win could not be set up: ' + What + #13#10#13#10 +
       'Details are in ' + InstallLog + '.', mbCriticalError);
  // an exception here would end in Inno's runtime-error dialog, which hangs a silent install
  ExitProcess(1);
end;

procedure PrepareChildEnvironment;
begin
  SetEnvironmentVariable('PYTHONPATH', ExpandConstant('{app}\src'));
  SetEnvironmentVariable('PYTHONUTF8', '1');
  SetEnvironmentVariable('PAPERLESS_WIN_APP_DIR', ExpandConstant('{app}'));
  SetEnvironmentVariable('PAPERLESS_ADMIN_USER', '');
  SetEnvironmentVariable('PAPERLESS_ADMIN_PASSWORD', '');
end;

function VenvPython: String;
begin
  Result := ExpandConstant('{app}\venv\Scripts\python.exe');
end;

function Ctl(const Args, Title: String): Integer;
begin
  Result := RunLogged(VenvPython, '-m paperless_win ' + Args, Title);
end;

// ---- upgrade: stop the old service and back up the database --------------------------------------------------------------------
// The OCR languages chosen at the first install live in {app}\bin, which an upgrade replaces:
// set them aside in {tmp} (RestoreLanguages puts them back).
procedure KeepLanguages;
var
  I: Integer;
  Source, Target: String;
begin
  Target := ExpandConstant('{tmp}\languages');
  ForceDirectories(Target);
  for I := 0 to LangCount - 1 do
  begin
    Source := ExpandConstant('{app}\bin\tesseract\tessdata\') + LangCode(I) + '.traineddata';
    if FileExists(Source) then FileCopy(Source, Target + '\' + LangCode(I) + '.traineddata', False);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Db: String;
  OldVersion: AnsiString;
  Dummy: Integer;
begin
  Result := '';
  if not Upgrading then Exit;
  if FileExists(ExpandConstant('{app}\VERSION')) then
  begin
    LoadStringFromFile(ExpandConstant('{app}\VERSION'), OldVersion);
    PreviousVersion := Trim(String(OldVersion));
  end;
  if FileExists(VenvPython) then
  begin
    PrepareChildEnvironment;
    Exec(ExpandConstant('{cmd}'), '/S /C ""' + VenvPython + '" -m paperless_win service stop"',
         ExpandConstant('{app}\src'), SW_HIDE, ewWaitUntilTerminated, Dummy);
    Exec(ExpandConstant('{cmd}'), '/S /C ""' + VenvPython + '" -m paperless_win stop"',
         ExpandConstant('{app}\src'), SW_HIDE, ewWaitUntilTerminated, Dummy);
  end;
  Db := StoredDataDir + '\db.sqlite3';
  if FileExists(Db) then
    if not FileCopy(Db, Db + '.bak-' + PreviousVersion, False) then
    begin
      Result := 'The database could not be backed up to ' + Db + '.bak-' + PreviousVersion + '. Nothing was changed.';
      Exit;
    end;
  KeepLanguages;
end;

// ---- the actual setup ----------------------------------------------------------------------------------------------------------------------------------
procedure CopySelectedLanguages;
var
  I: Integer;
  Cmd, Source, Target: String;
begin
  Cmd := ',' + CmdParam('LANGS', '') + ',';
  for I := 0 to LangCount - 1 do
  begin
    if Upgrading then
      Source := ExpandConstant('{tmp}\languages\') + LangCode(I) + '.traineddata'
    else if LangPage.Values[I] or (Pos(',' + LangCode(I) + ',', Cmd) > 0) then
      Source := ExpandConstant('{app}\tessdata-extra\') + LangCode(I) + '.traineddata'
    else
      Continue;
    Target := ExpandConstant('{app}\bin\tesseract\tessdata\') + LangCode(I) + '.traineddata';
    if FileExists(Source) then FileCopy(Source, Target, False);
  end;
end;

// Waits for the web interface. When it does not answer, the install log gets what is needed to see why.
procedure WaitForWebInterface;
var
  I, Code: Integer;
  ServiceLogs: String;
begin
  WizardForm.StatusLabel.Caption := 'Waiting for paperless-win to start...';
  for I := 1 to 45 do
  begin
    if Exec(ExpandConstant('{sys}\curl.exe'),
            '-s -o NUL --max-time 3 http://127.0.0.1:' + GetPort('') + '/api/',
            '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then Exit;
    Sleep(2000);
  end;
  SaveStringToFile(InstallLog, 'The web interface did not answer within 90 s.' + #13#10, True);
  RunLogged(ExpandConstant('{sys}\sc.exe'), 'queryex paperless-win', 'State of the service');
  ServiceLogs := GetDataDir('') + '\logs\service';
  RunLogged(ExpandConstant('{cmd}'), '/C "type "' + ServiceLogs + '\paperless-win-service.wrapper.log" & type "' + ServiceLogs + '\paperless-win-service.err.log""',
            'Logs of the service');
  Tell('paperless-win was installed, but its web interface did not answer within 90 seconds.' + #13#10 +
       'Details are in ' + InstallLog + '.', mbError);
end;

procedure SetUpApplication;
var
  App, PwFile, Bind, Params: String;
  Code: Integer;
  Elevated: Boolean;
begin
  App := ExpandConstant('{app}');
  Elevated := IsAdminInstallMode and (CmdParam('NOSERVICE', 'x') = 'x') and (Pos('/NOSERVICE', Uppercase(GetCmdTail)) = 0);
  ForceDirectories(GetDataDir('') + '\logs');
  PrepareChildEnvironment;

  // 1. the virtual environment, from the bundled wheels (offline)
  Code := RunLogged(App + '\uv.exe', 'venv --python "' + App + '\python\python.exe" "' + App + '\venv"',
                    'Creating the Python environment...');
  if Code <> 0 then Fail('creating the Python environment');
  Code := RunLogged(App + '\uv.exe',
                    'pip install --python "' + VenvPython + '" --no-index --find-links "' + App + '\wheelhouse\base" --no-cache --link-mode copy --no-deps -r "' + App + '\requirements.txt"',
                    'Installing paperless-win (this takes a minute)...');
  if Code <> 0 then Fail('installing the Python packages');
  // Every file below the app folder gets the permissions of its folder again. The service account must
  // read the venv; a file that kept the permissions of the place it was made in (a user's temp folder)
  // is not readable by it ("Permission denied" when the service starts).
  Code := RunLogged(ExpandConstant('{sys}\icacls.exe'), '"' + App + '" /reset /T /C /Q',
                    'Setting the permissions of the program files...');
  if Code <> 0 then Fail('setting the permissions of the program files');

  // 2. OCR languages, configuration
  CopySelectedLanguages;
  if WizardIsTaskSelected('firewall') then Bind := '0.0.0.0' else Bind := '127.0.0.1';
  if Upgrading then Params := 'setup --data-dir "' + GetDataDir('') + '"'
  else Params := 'setup --data-dir "' + GetDataDir('') + '" --consume-dir "' + GetConsumeDir('') + '" --ocr-languages ' + SelectedLanguages +
                 ' --port ' + GetPort('') + ' --bind ' + Bind;
  if Ctl(Params, 'Writing the configuration...') <> 0 then Fail('writing paperless.conf');

  // 3. optional Local AI add-on (network)
  if WizardIsTaskSelected('ailocal') then
  begin
    Code := RunLogged(App + '\uv.exe',
                      'pip install --python "' + VenvPython + '" --no-cache --link-mode copy --require-hashes --no-deps -r "' + App + '\requirements-ai-local.txt"',
                      'Downloading the Local AI add-on (about 600 MB)...');
    if Code <> 0 then
      Tell('The Local AI add-on could not be installed (no internet access?). paperless-win works without it; run the installer again to retry.' + #13#10 +
           'Details are in ' + InstallLog + '.', mbError);
  end;

  // 4. database, indexes, administrator account (the password goes through a file, never a command line)
  Params := 'init';
  if not Upgrading then
  begin
    PwFile := ExpandConstant('{tmp}\pw-') + GetDateTimeString('yyyymmddhhnnss', #0, #0) + '.txt';
    SaveStringsToUTF8File(PwFile, [AdminPage.Values[1]], False);
    Params := Params + ' --admin-user "' + AdminPage.Values[0] + '" --admin-password-file "' + PwFile + '"';
  end;
  Code := Ctl(Params, 'Setting up the database and indexes (this takes a few minutes the first time)...');
  if (PwFile <> '') and FileExists(PwFile) then DeleteFile(PwFile);
  if Code <> 0 then Fail('initialising the database');

  // 5. the service
  if Elevated then
  begin
    Params := 'service install --force --start';
    if WizardIsTaskSelected('firewall') then Params := Params + ' --firewall';
    if Ctl(Params, 'Installing the Windows service...') <> 0 then Fail('installing the Windows service');
    WaitForWebInterface;
  end
  else
    SaveStringToFile(InstallLog, 'Service not installed (no administrator rights or /NOSERVICE). Start it with: paperless-ctl run' + #13#10, True);

  // every step worked (a failing step ends the installer in Fail): later runs are upgrades
  RegWriteStringValue(RegRoot, 'Software\paperless-win', 'Complete', '1');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then SetUpApplication;
end;

// ---- uninstall ---------------------------------------------------------------------------------------------------------------------------------------------
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
  Data, Root: String;
  Delete: Boolean;
begin
  if CurUninstallStep = usUninstall then
  begin
    SetEnvironmentVariable('PYTHONPATH', ExpandConstant('{app}\src'));
    SetEnvironmentVariable('PYTHONUTF8', '1');
    SetEnvironmentVariable('PAPERLESS_WIN_APP_DIR', ExpandConstant('{app}'));
    if FileExists(ExpandConstant('{app}\venv\Scripts\python.exe')) then
    begin
      Exec(ExpandConstant('{cmd}'), '/S /C ""' + ExpandConstant('{app}\venv\Scripts\python.exe') + '" -m paperless_win service uninstall"',
           ExpandConstant('{app}\src'), SW_HIDE, ewWaitUntilTerminated, Code);
      Exec(ExpandConstant('{cmd}'), '/S /C ""' + ExpandConstant('{app}\venv\Scripts\python.exe') + '" -m paperless_win stop"',
           ExpandConstant('{app}\src'), SW_HIDE, ewWaitUntilTerminated, Code);
    end;
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    Data := '';
    if not RegQueryStringValue(HKLM, 'Software\paperless-win', 'DataDir', Data) then
      RegQueryStringValue(HKCU, 'Software\paperless-win', 'DataDir', Data);
    Root := ExpandConstant('{commonappdata}\paperless-win');
    Delete := False;
    if UninstallSilent then
      Delete := Pos('/DELETEDATA', Uppercase(GetCmdTail)) > 0
    else if Data <> '' then
      Delete := MsgBox('Do you also want to delete your documents, database and settings?' + #13#10#13#10 + Data + #13#10#13#10 +
                       'Choose No to keep them: a later installation will pick up the same library.',
                       mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
    if Delete then
    begin
      if Data <> '' then DelTree(Data, True, True, True);
      DelTree(Root, True, True, True);
    end;
  end;
end;
