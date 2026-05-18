$env:ENV_FILE = ".env.gemini"
Write-Host "[use-gemini] ENV_FILE=.env.gemini" -ForegroundColor Cyan
& $args[0] $args[1..($args.Length - 1)]
