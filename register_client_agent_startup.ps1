# DevERP Client Agent startup registration helper
# Registers all reliable auto-start methods for the current Windows user.

$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $base 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'client_agent_startup_register.log'

function Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $msg
}

$taskNames = @('DevERP_Client_Agent', 'DevERP Client Agent')
$vbsPath = Join-Path $base 'run_client_agent_hidden.vbs'
$ps1Path = Join-Path $base 'run_client_agent_hidden.ps1'
$startupDir = [Environment]::GetFolderPath('Startup')
$startupVbs = Join-Path $startupDir 'DevERP_Client_Agent.vbs'

Log "Register startup. Base=$base User=$env:USERDOMAIN\$env:USERNAME"

# Create a fixed-path VBS launcher. It works even if copied to the Startup folder.
$vbs = @"
Option Explicit
Dim sh, base, ps1, cmd
Set sh = CreateObject("WScript.Shell")
base = "$base"
ps1 = base & "\run_client_agent_hidden.ps1"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Chr(34) & ps1 & Chr(34)
sh.CurrentDirectory = base
sh.Run cmd, 0, False
"@
try {
    Set-Content -Path $vbsPath -Value $vbs -Encoding Default -Force
    Log "VBS launcher written: $vbsPath"
} catch {
    Log "WARN: failed to write VBS launcher: $($_.Exception.Message)"
}

# 1) HKCU Run: safest non-admin auto-start for the logged-in user.
$hkcuOk = $false
try {
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    New-Item -Path $runKey -Force | Out-Null
    $runCmd = 'wscript.exe //B "' + $vbsPath + '"'
    New-ItemProperty -Path $runKey -Name 'DevERP_Client_Agent' -Value $runCmd -PropertyType String -Force | Out-Null
    $hkcuOk = $true
    Log "HKCU Run registered: $runCmd"
} catch {
    Log "WARN: HKCU Run registration failed: $($_.Exception.Message)"
}

# 2) Startup folder VBS: fallback when task scheduler policy blocks registration.
$startupOk = $false
try {
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    Set-Content -Path $startupVbs -Value $vbs -Encoding Default -Force
    $startupOk = $true
    Log "Startup folder launcher written: $startupVbs"
} catch {
    Log "WARN: Startup folder registration failed: $($_.Exception.Message)"
}

# 3) Task Scheduler: best when Windows delays Startup apps. Not fatal if blocked by policy.
$taskOk = $false
foreach ($tn in $taskNames) {
    try { Unregister-ScheduledTask -TaskName $tn -Confirm:$false -ErrorAction SilentlyContinue | Out-Null } catch {}
    try { schtasks.exe /Delete /TN $tn /F | Out-Null } catch {}
}
try {
    $action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument ('//B "' + $vbsPath + '"')
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DisallowStartIfOnBatteries:$false -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 0)
    Register-ScheduledTask -TaskName 'DevERP_Client_Agent' -Action $action -Trigger $trigger -Settings $settings -Description 'DevERP local Bizbox automation agent' -Force | Out-Null
    $taskOk = $true
    Log "Scheduled task registered with Register-ScheduledTask: DevERP_Client_Agent"
} catch {
    Log "WARN: Register-ScheduledTask failed: $($_.Exception.Message)"
    try {
        $tr = '"' + "$env:WINDIR\System32\wscript.exe" + '" //B "' + $vbsPath + '"'
        schtasks.exe /Create /TN 'DevERP_Client_Agent' /TR $tr /SC ONLOGON /RL LIMITED /F | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $taskOk = $true
            Log "Scheduled task registered with schtasks.exe: DevERP_Client_Agent"
        } else {
            Log "WARN: schtasks.exe failed. ExitCode=$LASTEXITCODE"
        }
    } catch {
        Log "WARN: schtasks.exe exception: $($_.Exception.Message)"
    }
}

Log "Registration result: HKCU=$hkcuOk Startup=$startupOk Task=$taskOk"
if ($hkcuOk -or $startupOk -or $taskOk) { exit 0 }
exit 20
