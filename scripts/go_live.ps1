# Go_Live.ps1 - ek click me sab kuch chalu karke public live link deta hai
$proj     = "C:\Users\ahmedbanday\classroom_ai_agent"
$tunnelLog = Join-Path $env:TEMP "classroom_tunnel.log"
$linkFile  = Join-Path $env:USERPROFILE "Documents\live_link.txt"
$sshExe    = "C:\WINDOWS\System32\OpenSSH\ssh.exe"
$sshArgs   = @("-o","StrictHostKeyChecking=no","-o","UserKnownHostsFile=NUL",
               "-o","LogLevel=ERROR","-o","ServerAliveInterval=30",
               "-o","ServerAliveCountMax=6","-R","80:localhost:5000",
               "nokey@localhost.run")

function Start-Tunnel {
    Remove-Item $tunnelLog, "$tunnelLog.err" -ErrorAction SilentlyContinue
    Start-Process -FilePath $sshExe -ArgumentList $sshArgs `
        -RedirectStandardOutput $tunnelLog -RedirectStandardError "$tunnelLog.err" `
        -WindowStyle Hidden
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 750
        $txt = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($txt -match "https://[a-z0-9\-]+\.lhr\.life") { return $Matches[0] }
    }
    return ""
}

function Test-SshAlive {
    $p = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like "*localhost.run*" }
    return [bool]$p
}

function Stop-OurSsh {
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*localhost.run*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

Write-Host "[1/4] Checking Ollama..." -ForegroundColor Cyan
if (-not (Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue)) {
    $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $ollama) { Start-Process $ollama; Start-Sleep 3 }
    Write-Host "      Ollama started."
}

Write-Host "[2/4] Checking web server (port 5000)..." -ForegroundColor Cyan
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 5000 -WarningAction SilentlyContinue).TcpTestSucceeded) {
    Start-Process -FilePath "$proj\venv\Scripts\python.exe" `
        -ArgumentList "-u","-m","app.web" -WorkingDirectory $proj -WindowStyle Hidden
    Start-Sleep 5
    Write-Host "      Web server started."
} else {
    Write-Host "      Web server already running."
}

Write-Host "[3/4] Starting live tunnel..." -ForegroundColor Cyan
Stop-OurSsh
$url = Start-Tunnel
if (-not $url) {
    Write-Host "      TUNNEL FAILED - see $tunnelLog.err" -ForegroundColor Red
    Get-Content "$tunnelLog.err" -ErrorAction SilentlyContinue | Select-Object -Last 3
    Read-Host "Press Enter to close"
    exit 1
}

$code = & curl.exe -s -o NUL -w "%{http_code}" --max-time 30 "$url/login"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Set-Content -Path $linkFile -Value "LIVE LINK : $url`r`nHTTP      : $code`r`nUPDATED   : $stamp"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " LIVE LINK : $url" -ForegroundColor Yellow
Write-Host " HTTP      : $code" -ForegroundColor Yellow
Write-Host " PASSWORD  : classroom" -ForegroundColor Yellow
Write-Host " SAVED TO  : $linkFile" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

Start-Process $url

Write-Host "[4/4] Keep-alive running - window khula rakho (band karoge to link maregi)" -ForegroundColor Cyan
while ($true) {
    Start-Sleep -Seconds 90
    if (-not (Test-SshAlive)) {
        Write-Host "[$(Get-Date -Format HH:mm:ss)] Tunnel died - restarting..." -ForegroundColor DarkYellow
        Stop-OurSsh
        $newUrl = Start-Tunnel
        if ($newUrl) { $url = $newUrl; Write-Host "[$(Get-Date -Format HH:mm:ss)] New link: $url" -ForegroundColor Yellow }
    }
    $code = "000"
    try { $code = & curl.exe -s -o NUL -w "%{http_code}" --max-time 20 "$url/login" } catch {}
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Set-Content -Path $linkFile -Value "LIVE LINK : $url`r`nHTTP      : $code`r`nUPDATED   : $stamp"
    Write-Host "[$stamp] keep-alive ping -> $code" -ForegroundColor DarkGray
}
