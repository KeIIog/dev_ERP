# DevERP Client Agent hidden launcher
# Starts the local automation agent and writes detailed logs.

$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $base 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$launcherLog = Join-Path $logDir 'client_agent_launcher.log'
$stdoutLog = Join-Path $logDir 'client_agent_stdout.log'
$stderrLog = Join-Path $logDir 'client_agent_stderr.log'
$depOutLog = Join-Path $logDir 'client_agent_dependency_stdout.log'
$depErrLog = Join-Path $logDir 'client_agent_dependency_stderr.log'
$port = 8765
$healthUrl = "http://127.0.0.1:$port/health"

function Write-LauncherLog([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $launcherLog -Value $line -Encoding UTF8
}

function Test-AgentHealth {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Wait-AgentHealth([int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-AgentHealth) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

Write-LauncherLog "Launcher start. Base=$base Health=$healthUrl User=$env:USERDOMAIN\$env:USERNAME"

if (Test-AgentHealth) {
    Write-LauncherLog 'Already running. Health OK.'
    exit 0
}

# Clean stale listeners on the agent port.
try {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($l in $listeners) {
        try {
            Write-LauncherLog "Killing old listener PID=$($l.OwningProcess)"
            Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
        } catch {}
    }
    Start-Sleep -Milliseconds 500
} catch {
    Write-LauncherLog "WARN: port cleanup failed: $($_.Exception.Message)"
}

# 1) Prefer built EXE if present.
$exeCandidates = @(
    (Join-Path $base 'dist\DevERP_Client_Agent\DevERP_Client_Agent.exe'),
    (Join-Path $base 'dist\DevERP_Client_Agent.exe'),
    (Join-Path $base 'DevERP_Client_Agent.exe'),
    (Join-Path $base 'client_web_agent.exe')
)
foreach ($exe in $exeCandidates) {
    if (Test-Path $exe) {
        Write-LauncherLog "Starting EXE: $exe"
        try {
            Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
            if (Wait-AgentHealth 20) { Write-LauncherLog 'EXE start success. Health OK.'; exit 0 }
            Write-LauncherLog 'EXE launched but health check failed.'
        } catch { Write-LauncherLog ("EXE start failed: " + $_.Exception.Message) }
    }
}

# 2) Source mode: run client_web_agent.py with local Python.
$pyFile = Join-Path $base 'client_web_agent.py'
if (!(Test-Path $pyFile)) {
    Write-LauncherLog "client_web_agent.py not found: $pyFile"
    exit 10
}

$pythonPath = $null
$isPyLauncher = $false
foreach ($name in @('py.exe', 'python.exe')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $pythonPath = $cmd.Source
        $isPyLauncher = ($name -eq 'py.exe')
        break
    }
}
if (-not $pythonPath) {
    Write-LauncherLog 'Python not found. Install Python or build DevERP_Client_Agent.exe.'
    exit 11
}
Write-LauncherLog "Python found: $pythonPath IsPyLauncher=$isPyLauncher"

# 3) Check/install minimum dependencies for Bizbox Selenium automation.
$depArgs = @()
if ($isPyLauncher) { $depArgs += '-3' }
$depArgs += @('-c', 'import selenium, webdriver_manager, bs4')
$p = Start-Process -FilePath $pythonPath -ArgumentList $depArgs -WorkingDirectory $base -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $depOutLog -RedirectStandardError $depErrLog
if ($p.ExitCode -ne 0) {
    Write-LauncherLog 'Missing Python dependencies. Trying pip install.'
    $req = Join-Path $base 'requirements_client_agent.txt'
    if (!(Test-Path $req)) { $req = Join-Path $base 'requirements.txt' }
    if (!(Test-Path $req)) { Write-LauncherLog 'No requirements file found.'; exit 12 }
    $pipArgs = @()
    if ($isPyLauncher) { $pipArgs += '-3' }
    $pipArgs += @('-m', 'pip', 'install', '-r', $req)
    $pip = Start-Process -FilePath $pythonPath -ArgumentList $pipArgs -WorkingDirectory $base -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $depOutLog -RedirectStandardError $depErrLog
    if ($pip.ExitCode -ne 0) { Write-LauncherLog "pip install failed. ExitCode=$($pip.ExitCode)"; exit 13 }
    Write-LauncherLog 'pip install completed.'
}

# 4) Start agent hidden with logs.
$runArgs = @()
if ($isPyLauncher) { $runArgs += '-3' }
$runArgs += @('-u', $pyFile)
Write-LauncherLog "Starting Python agent: $pythonPath $($runArgs -join ' ')"
try {
    Start-Process -FilePath $pythonPath -ArgumentList $runArgs -WorkingDirectory $base -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null
    if (Wait-AgentHealth 20) { Write-LauncherLog 'Python agent start success. Health OK.'; exit 0 }
    Write-LauncherLog 'Python agent was launched but health check failed.'
    exit 14
} catch {
    Write-LauncherLog ("Python agent start failed: " + $_.Exception.Message)
    exit 15
}
