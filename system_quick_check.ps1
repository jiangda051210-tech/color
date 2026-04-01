param(
  [string]$ApiHost = "127.0.0.1",
  [int]$Port = 8877,
  [string]$ApiKey = "",
  [string]$AdminKey = "",
  [string]$HistoryDbPath = "",
  [string]$TenantId = "",
  [string]$TenantHeaderName = "x-tenant-id"
)

$ErrorActionPreference = "Stop"
$base = "http://$ApiHost`:$Port"
if (-not $HistoryDbPath) {
  $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $HistoryDbPath = Join-Path $scriptDir "quality_history.sqlite"
}

function Check-Endpoint {
  param(
    [string]$Path,
    [hashtable]$HeadersExtra = @{}
  )
  $url = "$base$Path"
  try {
    $headers = @{}
    if ($ApiKey) { $headers["x-api-key"] = $ApiKey }
    if ($TenantId) { $headers[$TenantHeaderName] = $TenantId }
    foreach ($kv in $HeadersExtra.GetEnumerator()) { $headers[$kv.Key] = $kv.Value }
    $resp = Invoke-RestMethod -Uri $url -Method Get -Headers $headers -TimeoutSec 20
    Write-Host "[OK] $Path"
    return @{ ok = $true; body = $resp; status = 200 }
  } catch {
    $status = 0
    if ($_.Exception.Response) {
      try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = 0 }
    }
    Write-Host "[FAIL] $Path -> $($_.Exception.Message)"
    return @{ ok = $false; body = $null; status = $status }
  }
}

Write-Host "Checking Elite API at $base ..."
$h = Check-Endpoint "/health"
$r = Check-Endpoint "/ready"
$s = Check-Endpoint "/v1/system/status"
$adminHeaders = @{}
if ($AdminKey) { $adminHeaders["x-api-key"] = $AdminKey }
if ($TenantId) { $adminHeaders[$TenantHeaderName] = $TenantId }
$t = Check-Endpoint "/v1/system/self-test" -HeadersExtra $adminHeaders
$d = Check-Endpoint "/v1/system/alert-dead-letter" -HeadersExtra $adminHeaders
$x = Check-Endpoint "/v1/system/metrics"
$l = Check-Endpoint "/v1/system/slo"
$a = Check-Endpoint "/v1/system/auth-info"
$n = Check-Endpoint "/v1/system/tenant-info"
$o = Check-Endpoint ("/v1/system/ops-summary?db_path=" + [uri]::EscapeDataString($HistoryDbPath) + "&window=120&audit_limit=20")
$b = Check-Endpoint ("/v1/system/executive-brief?db_path=" + [uri]::EscapeDataString($HistoryDbPath) + "&window=120")
$w = Check-Endpoint ("/v1/web/executive-brief?db_path=" + [uri]::EscapeDataString($HistoryDbPath))
$g = Check-Endpoint "/v1/system/release-gate-report"
$m = Check-Endpoint "/v1/innovation/manifest"

if (-not $t.ok -and $t.status -eq 403 -and -not $AdminKey) {
  Write-Host "[SKIP] /v1/system/self-test -> admin role required (no -AdminKey provided)"
  $t = @{ ok = $true; body = $null; status = 403 }
}
if (-not $d.ok -and $d.status -eq 403 -and -not $AdminKey) {
  Write-Host "[SKIP] /v1/system/alert-dead-letter -> admin role required (no -AdminKey provided)"
  $d = @{ ok = $true; body = $null; status = 403 }
}

if ($t.ok -and $t.body -and -not $t.body.ok) {
  Write-Host "[FAIL] /v1/system/self-test -> one or more checks failed"
  $t = @{ ok = $false; body = $t.body; status = 200 }
}

if ($s.ok -and $s.body) {
  Write-Host ("Version: " + $s.body.service.version)
  Write-Host ("Uptime: " + $s.body.service.uptime_sec + " sec")
  Write-Host ("Route count: " + $s.body.routes.count)
  Write-Host ("Recent RPM: " + $s.body.metrics_brief.recent_requests_per_min)
}

if ($h.ok -and $r.ok -and $s.ok -and $m.ok -and $t.ok -and $d.ok -and $x.ok -and $l.ok -and $a.ok -and $n.ok -and $o.ok -and $b.ok -and $w.ok -and $g.ok) {
  Write-Host "Quick check PASSED"
  exit 0
}

Write-Host "Quick check FAILED"
exit 1
