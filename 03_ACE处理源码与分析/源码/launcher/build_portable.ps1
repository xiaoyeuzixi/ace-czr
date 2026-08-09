[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vswhere = 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'vswhere.exe was not found.' }
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual C++ x64 tools were not found.' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
$bin = Join-Path $root 'bin'
New-Item -ItemType Directory -Force -Path $bin,(Join-Path $bin 'AntiCheatExpert') | Out-Null
$cmd = '"{0}" && cd /d "{1}" && cl /nologo /O2 /EHsc /utf-8 combined_stub.cpp /link /DEF:combined_stub.def /MACHINE:X64 /OUT:"{2}\combined_stub.dll" && cl /nologo /O2 /EHsc /utf-8 NoAceUnityLauncher.cpp /link /SUBSYSTEM:WINDOWS /MACHINE:X64 user32.lib /OUT:"{2}\NoAceUnityLauncher.exe"' -f $vcvars,$PSScriptRoot,$bin
cmd.exe /d /s /c $cmd
if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
$names = @('ACE-Base64.dll','ACE-SDK.dll','ACE-TP.dll','tersafe.dll','tersafe2.dll','TP2.dll','tp2_stub.dll','TPHelper.dll','tsssdk.dll','tss_sdk.dll','TenProtect.dll','TenProtect64.dll','TPShell64.dll')
foreach ($name in $names) { Copy-Item -LiteralPath (Join-Path $bin 'combined_stub.dll') -Destination (Join-Path $bin "AntiCheatExpert\$name") -Force }
Write-Host 'Portable build complete.'
