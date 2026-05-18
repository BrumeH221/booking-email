# scripts/cleanup.ps1
# Cleanup helper. Run from project root:  .\scripts\cleanup.ps1 [-Force]

param([switch]$Force)

$root = Split-Path -Parent $PSScriptRoot   # one level up: project root
$TO_DELETE = @(
    ".env",            # legacy from older versions
    "__pycache__",
    "*.pyc",
    "_test_dir"        # leftover from sandbox testing
)

Write-Host "Cleanup root: $root" -ForegroundColor Cyan
$found = @()
foreach ($pattern in $TO_DELETE) {
    $items = Get-ChildItem -Path $root -Recurse -Force -Filter $pattern `
        -ErrorAction SilentlyContinue | Where-Object {
            $_.FullName -notmatch "\\\.venv\\"
        }
    foreach ($it in $items) { $found += $it }
}

if ($found.Count -eq 0) { Write-Host "Nothing to delete." -ForegroundColor Green; exit 0 }

Write-Host "Will delete $($found.Count) item(s):" -ForegroundColor Yellow
$found | ForEach-Object { Write-Host "  $($_.FullName.Substring($root.Length + 1))" }

if (-not $Force) {
    Write-Host "`nDry run. Run with -Force to delete." -ForegroundColor Yellow
    exit 0
}

foreach ($it in $found) {
    try {
        Remove-Item -Path $it.FullName -Recurse -Force -ErrorAction Stop
        Write-Host "  ✓ Deleted: $($it.Name)" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed: $($it.Name) — $($_.Exception.Message)" -ForegroundColor Red
    }
}
