param(
  [string]$ApiHost = "0.0.0.0",
  [int]$Port = 8877
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Starting Elite Color Match API at http://$ApiHost`:$Port"
Write-Host "Swagger docs: http://$ApiHost`:$Port/docs"
Write-Host "System status: http://$ApiHost`:$Port/v1/system/status"
Write-Host "Readiness: http://$ApiHost`:$Port/ready"
Write-Host "System metrics: http://$ApiHost`:$Port/v1/system/metrics"
Write-Host "SLO: http://$ApiHost`:$Port/v1/system/slo"
Write-Host "Auth info: http://$ApiHost`:$Port/v1/system/auth-info"
Write-Host "Tenant info: http://$ApiHost`:$Port/v1/system/tenant-info"
Write-Host "Alert test: http://$ApiHost`:$Port/v1/system/alert-test?level=warning&title=test&message=hello"
Write-Host "Alert dead-letter: http://$ApiHost`:$Port/v1/system/alert-dead-letter"
Write-Host "Alert replay: http://$ApiHost`:$Port/v1/system/alert-replay?limit=20&prune_on_success=true"
Write-Host "Ops summary: http://$ApiHost`:$Port/v1/system/ops-summary?db_path=D:/color%20match/autocolor/quality_history.sqlite"
Write-Host "Executive brief: http://$ApiHost`:$Port/v1/system/executive-brief?db_path=D:/color%20match/autocolor/quality_history.sqlite"
Write-Host "Release gate report: http://$ApiHost`:$Port/v1/system/release-gate-report"
Write-Host "Executive dashboard: http://$ApiHost`:$Port/v1/web/executive-dashboard"
Write-Host "Executive brief page: http://$ApiHost`:$Port/v1/web/executive-brief"
Write-Host "Executive export: http://$ApiHost`:$Port/v1/history/executive-export?db_path=D:/color%20match/autocolor/quality_history.sqlite"

try {
  $ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notmatch '^127\\.|^169\\.254\\.' } |
    Select-Object -ExpandProperty IPAddress -Unique
  foreach ($ip in $ips) {
    Write-Host "LAN entry: http://$ip`:$Port/"
  }
} catch {
  Write-Host "LAN IP lookup skipped: $($_.Exception.Message)"
}

python -m uvicorn elite_api:app --host $ApiHost --port $Port
