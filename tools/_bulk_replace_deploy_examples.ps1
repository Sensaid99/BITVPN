$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root ".git"))) { $root = "d:\VPN BOT" }
$enc = [System.Text.UTF8Encoding]::new($false)
Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $_.FullName -notmatch '\\\.git\\' -and (
        $_.Extension -match '\.(md|txt|conf|example|cmd|bat)$' -or $_.Name -eq '.env.example'
    )
} | ForEach-Object {
    $p = $_.FullName
    try {
        $c = [System.IO.File]::ReadAllText($p, $enc)
    } catch { return }
    $n = $c `
        -replace '155\.212\.164\.135', '213.165.38.222' `
        -replace 'nikolay\.lisobyk\.fvds\.ru', 'bitecosystem.ru' `
        -replace 'николай\.lisobyk\.fvds\.ru', 'bitecosystem.ru' `
        -replace 'Николай\.lisobyk\.fvds\.ru', 'bitecosystem.ru'
    if ($n -ne $c) {
        [System.IO.File]::WriteAllText($p, $n, $enc)
        Write-Output $p
    }
}
