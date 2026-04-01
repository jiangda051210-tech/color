param(
  [int]$Port = 8877
)

$ErrorActionPreference = "Stop"

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
  Write-Host "No listening process found on TCP port $Port"
  exit 0
}

$procIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $procIds) {
  try {
    $proc = Get-Process -Id $procId -ErrorAction Stop
    Stop-Process -Id $procId -Force -ErrorAction Stop
    Write-Host "Stopped process $($proc.ProcessName) (PID=$procId) on port $Port"
  } catch {
    Write-Host "Failed to stop PID ${procId}: $($_.Exception.Message)"
  }
}
