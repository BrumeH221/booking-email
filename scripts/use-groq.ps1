$env:ENV_FILE = ".env.groq"
$env:DB_BACKEND = "supabase"
$env:LLM_PROVIDER = "groq"

Write-Host "[use-groq] ENV_FILE=$env:ENV_FILE"
Write-Host "[use-groq] DB_BACKEND=$env:DB_BACKEND"
Write-Host "[use-groq] LLM_PROVIDER=$env:LLM_PROVIDER"

if ($args.Count -eq 0) {
    Write-Host "Usage: .\use-groq.ps1 python main.py"
    exit 1
}

$cmd = $args[0]
$cmdArgs = @($args | Select-Object -Skip 1)

& $cmd @cmdArgs
