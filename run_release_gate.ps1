param(
  [string]$ApiHost = "127.0.0.1",
  [int]$Port = 8877,
  [string]$ApiKey = "",
  [string]$AdminKey = "",
  [string]$TenantId = "",
  [string]$TenantHeaderName = "x-tenant-id",
  [string]$ViewerKey = "",
  [string]$OperatorKey = "",
  [string]$RoleTenant = "",
  [string]$WrongTenant = "tenant-not-allowed",
  [double]$SloAvailabilityTarget = 99.5,
  [double]$SloP95TargetMs = 1200,
  [switch]$SkipRoleBoundary,
  [switch]$RequireRoleBoundary,
  [switch]$RequireSloHealthy,
  [switch]$StrictAlertTest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$baseUrl = "http://$ApiHost`:$Port"
$argsList = @(
  "run_release_gate.py",
  "--base-url", $baseUrl
)

if ($ApiKey) { $argsList += @("--api-key", $ApiKey) }
if ($AdminKey) { $argsList += @("--admin-key", $AdminKey) }
if ($TenantId) { $argsList += @("--tenant-id", $TenantId, "--tenant-header", $TenantHeaderName) }
if ($ViewerKey) { $argsList += @("--viewer-key", $ViewerKey) }
if ($OperatorKey) { $argsList += @("--operator-key", $OperatorKey) }
if ($RoleTenant) { $argsList += @("--role-tenant", $RoleTenant) }
if ($WrongTenant) { $argsList += @("--wrong-tenant", $WrongTenant) }
if ($SloAvailabilityTarget) { $argsList += @("--slo-availability-target", $SloAvailabilityTarget) }
if ($SloP95TargetMs) { $argsList += @("--slo-p95-target-ms", $SloP95TargetMs) }
if ($SkipRoleBoundary) { $argsList += "--skip-role-boundary" }
if ($RequireRoleBoundary) { $argsList += "--require-role-boundary" }
if ($RequireSloHealthy) { $argsList += "--require-slo-healthy" }
if ($StrictAlertTest) { $argsList += "--strict-alert-test" }

Write-Host "Running release gate against $baseUrl"
python @argsList
