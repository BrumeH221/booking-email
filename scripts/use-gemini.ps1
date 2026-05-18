$env:ENV_FILE = ".env.gemini"
$env:DB_BACKEND = "supabase"
$env:LLM_PROVIDER = "gemini"

Write-Host "[use-gemini] ENV_FILE=$env:ENV_FILE"
Write-Host "[use-gemini] DB_BACKEND=$env:DB_BACKEND"
Write-Host "[use-gemini] LLM_PROVIDER=$env:LLM_PROVIDER"

if ($args.Count -eq 0) {
    Write-Host "Usage: .\use-gemini.ps1 python main.py"
    exit 1
}

$cmd = $args[0]
$cmdArgs = @($args | Select-Object -Skip 1)

& $cmd @cmdArgs