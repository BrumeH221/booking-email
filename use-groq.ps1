$env:ENV_FILE = ".env.groq"
Write-Host "[use-groq] ENV_FILE=.env.groq" -ForegroundColor Cyan
& $args[0] $args[1..($args.Length - 1)]
