[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PackageRoot = $PSScriptRoot
$Launcher = Join-Path $PackageRoot 'bin\NoAceUnityLauncher.exe'
$OptionalPatch = Join-Path $PackageRoot 'payload\il2cppscripts_0_optional_update_fix.ab'
$OptionalOriginalPayload = Join-Path $PackageRoot 'payload\il2cppscripts_0_res795_original.ab'
$LogDir = Join-Path $PackageRoot 'logs'
$StatusLog = Join-Path $LogDir 'launcher_status.log'

# Wildcard patterns for auto-detection after game updates
$BundlePattern = 'updatescript_*.dll.ab_u_*'
$OptionalPlainPattern = 'il2cppscripts_*.dll.ab'
$OptionalHashedPattern = 'il2cppscripts_*.dll.ab_u_*'

# Supported version hashes for updatescript_500.dll.ab
# Each entry: Label, OriginalHash, PatchHash, PatchFile
$UpdatescriptVersions = @(
    @{
        Label = 'V1_res500'
        OriginalHash = 'D0E7CCEABB57AD5A05C072ED4D9FF3B82D5D9F4364803E13169089BAB21BF6A0'
        PatchHash = 'F25AB3ADABCEC20CEF0EC25E19A6BEFC086C1950F1677D44A80B68C837555666'
        PatchFile = Join-Path $PackageRoot 'payload\updatescript_500_forcequit_fix.ab'
    },
    @{
        Label = 'V2_res500'
        OriginalHash = 'B40A4A7F9286F047B2D3E0BF9C19D7B4967C2F01B726FF9A47EBB3097A65FC08'
        PatchHash = '1DFEDA8362E627E5A5F620099D4174922DBCB8AD062D50B387C758B992130613'
        PatchFile = Join-Path $PackageRoot 'payload\updatescript_500_v2_forcequit_fix.ab'
    }
)

$OptionalHash = 'D9032C445FED9206D8F11238A6721F0F3BEAD9857610A579AED087B9A47A1B55'
$OptionalPatchHash = 'ED9DA6D2B0161A16B3FCCD8578A46032455729969EA73D373F83F5D6CFE2077F'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $StatusLog -Value $line -Encoding UTF8
    Write-Host $line
}

function Hash {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

function Find-One-Pattern {
    param([string]$Root, [string]$Pattern)
    $items = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $Pattern -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) {
        Log "WARNING: No files matching '$Pattern' under $Root"
        return $null
    }
    if ($items.Count -gt 1) {
        Log "WARNING: Multiple files match '$Pattern', using first: $($items[0].Name)"
    }
    return $items[0].FullName
}

function Install-CheckedPatch {
    param(
        [string]$Target,
        [hashtable[]]$Versions,
        [string]$BackupPrefix
    )
    $currentHash = Hash $Target
    $backupDir = Join-Path $PackageRoot 'backups'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    foreach ($v in $Versions) {
        if ($currentHash -eq $v.PatchHash) {
            Log "Patch already installed ($($v.Label)): $(Split-Path $Target -Leaf)"
            return $true
        }
    }
    foreach ($v in $Versions) {
        if ($currentHash -eq $v.OriginalHash) {
            $backup = Join-Path $backupDir ($BackupPrefix + '_' + $v.Label + '.bak')
            if (-not (Test-Path -LiteralPath $backup)) {
                Copy-Item -LiteralPath $Target -Destination $backup
            }
            if ((Hash $backup) -ne $v.OriginalHash) { throw "Backup hash mismatch: $backup" }
            $staged = $Target + '.codex-new'
            Copy-Item -LiteralPath $v.PatchFile -Destination $staged -Force
            if ((Hash $staged) -ne $v.PatchHash) { throw "Staged patch hash mismatch: $staged" }
            Move-Item -LiteralPath $staged -Destination $Target -Force
            Log "Patched bundle ($($v.Label)): $(Split-Path $Target -Leaf)"
            return $true
        }
    }
    Log "WARNING: Skipping patch for $(Split-Path $Target -Leaf) -- hash unknown (game updated). Actual=$currentHash"
    return $false
}

# Pre-flight checks
if (-not (Test-Path -LiteralPath $Launcher)) { throw "Missing launcher: $Launcher" }
if (-not (Test-Path -LiteralPath $OptionalPatch)) { throw "Missing optional patch: $OptionalPatch" }
if ((Hash $OptionalPatch) -ne $OptionalPatchHash) { throw 'Optional patch hash mismatch.' }
if ((Hash $OptionalOriginalPayload) -ne $OptionalHash) { throw 'Optional original hash mismatch.' }
foreach ($v in $UpdatescriptVersions) {
    if (Test-Path -LiteralPath $v.PatchFile) {
        if ((Hash $v.PatchFile) -ne $v.PatchHash) { throw "Patch payload hash mismatch for $($v.Label)" }
    }
}

# Locate game
$gameRoot = $env:PRETERNATURAL_GAME_ROOT
if (-not $gameRoot) { $gameRoot = 'C:\Program Files (x86)\preternatural' }
if (-not (Test-Path -LiteralPath (Join-Path $gameRoot 'UnityPlayer.dll'))) {
    throw "UnityPlayer.dll not found under $gameRoot. Set PRETERNATURAL_GAME_ROOT."
}
$codeRoot = Join-Path $env:USERPROFILE 'AppData\LocalLow\pi'

# Scan for bundles
Log 'Scanning for bundles ...'
$target = Find-One-Pattern $codeRoot $BundlePattern
if (-not $target) {
    throw "Cannot find updatescript bundle matching '$BundlePattern'. Has the game been launched at least once?"
}
Log "Found updatescript bundle: $(Split-Path $target -Leaf)"

$optionalPlainTarget = Find-One-Pattern $codeRoot $OptionalPlainPattern
$optionalHashedTarget = Find-One-Pattern $codeRoot $OptionalHashedPattern
if ($optionalPlainTarget) { Log "Found plain il2cppscripts bundle: $(Split-Path $optionalPlainTarget -Leaf)" }
if ($optionalHashedTarget) { Log "Found hashed il2cppscripts bundle: $(Split-Path $optionalHashedTarget -Leaf)" }
if ((-not $optionalPlainTarget) -and (-not $optionalHashedTarget)) {
    Log 'WARNING: No il2cppscripts bundles found. Optional update patch will be skipped.'
}

# Check running processes
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.ProcessName -match 'NoAceUnityLauncher|UnityCrashHandler64') -or
    ($_.Path -like "$gameRoot\*")
}
if ($running) { throw "Close the running game before starting. PID: $($running.Id -join ', ')" }

# Apply patches
$patchesApplied = 0
$patchesSkipped = 0

$r1 = Install-CheckedPatch $target $UpdatescriptVersions 'updatescript_500_original'
if ($r1) { $patchesApplied++ } else { $patchesSkipped++ }

if ($optionalPlainTarget) {
    $optVersions = @(@{
        Label = 'V1_res795'
        OriginalHash = $OptionalHash
        PatchHash = $OptionalPatchHash
        PatchFile = $OptionalPatch
    })
    $r2 = Install-CheckedPatch $optionalPlainTarget $optVersions 'il2cppscripts_0_original'
    if ($r2) { $patchesApplied++ } else { $patchesSkipped++ }
}
if ($optionalHashedTarget) {
    $optVersions = @(@{
        Label = 'V1_res795'
        OriginalHash = $OptionalHash
        PatchHash = $OptionalPatchHash
        PatchFile = $OptionalPatch
    })
    $r3 = Install-CheckedPatch $optionalHashedTarget $optVersions 'il2cppscripts_0_original'
    if ($r3) { $patchesApplied++ } else { $patchesSkipped++ }
}

if ($patchesSkipped -gt 0) {
    Log "SUMMARY: $patchesApplied applied, $patchesSkipped skipped (version mismatch). Game will still launch via NoACE stubs."
}

# Launch
$dataDirs = @(Get-ChildItem -LiteralPath $gameRoot -Directory -Filter '*_Data')
if ($dataDirs.Count -lt 1) { throw "No Unity *_Data directory found under $gameRoot" }
Log "Starting game root=$gameRoot data=$($dataDirs[0].FullName)"
Start-Process -FilePath $Launcher -WorkingDirectory $gameRoot
Start-Sleep -Seconds 5
$process = Get-Process -Name 'NoAceUnityLauncher' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $process) { throw 'Launcher exited during the first 5 seconds. Check logs.' }
Log "Started PID=$($process.Id) bundle_hash=$(Hash $target)"
