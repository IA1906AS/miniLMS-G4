$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}
$dockerCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin')
)
foreach ($dockerBin in $dockerCandidates) {
    if (Test-Path -LiteralPath (Join-Path $dockerBin 'docker.exe')) {
        $env:PATH = $dockerBin + ';' + $env:PATH
        break
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed. Install Docker Desktop or configure DATABASE_URL for an existing PostgreSQL server."
}
docker compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL did not start." }
if (-not (Test-Path -LiteralPath ".venv/Scripts/python.exe")) {
    throw "Install project dependencies first: uv sync --dev"
}
& .venv/Scripts/python.exe -m flask --app app run --debug
