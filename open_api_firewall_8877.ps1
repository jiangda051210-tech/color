param(
  [int]$Port = 8877,
  [string]$RuleName = "SENIA Elite API 8877"
)

$ErrorActionPreference = "Stop"

Write-Host "Adding firewall inbound rule for TCP $Port ..."
$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Rule already exists: $RuleName"
  exit 0
}

New-NetFirewallRule `
  -DisplayName $RuleName `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort $Port `
  -Profile Any | Out-Null

Write-Host "Firewall rule created: $RuleName"
