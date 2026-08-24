param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$scanRoot = [System.IO.Path]::GetFullPath($Root)
$patterns = [ordered]@{
    "private-key-block" = "(?s)-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{80,}-----END"
    "github-token" = "\bgh[pousr]_[A-Za-z0-9_]{20,}\b"
    "openai-style-key" = "\bsk-[A-Za-z0-9_-]{20,}\b"
    "aws-access-key" = "\bAKIA[0-9A-Z]{16}\b"
    "jwt" = "\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    "credential-url" = "(?i)https?://[^\s/:]+:[^\s/@]+@"
}

$files = @(
    Get-ChildItem -LiteralPath $scanRoot -Recurse -File |
        Where-Object {
            $_.FullName -notmatch "\\(node_modules|dist|\.git)\\" -and
            $_.Extension -notmatch "^\.(png|jpg|jpeg|gif|webp|ico|woff|woff2|ttf|mp4|mov|zip|tgz|gz)$"
        }
)

$findings = @()
foreach ($file in $files) {
    $content = [System.IO.File]::ReadAllText($file.FullName)
    foreach ($entry in $patterns.GetEnumerator()) {
        if ([regex]::IsMatch($content, $entry.Value)) {
            $findings += [pscustomobject]@{
                Type = $entry.Key
                Path = $file.FullName.Substring($scanRoot.Length + 1)
            }
        }
    }
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object Path, Type | Format-Table -AutoSize
    throw "Potential secrets found. Values are intentionally not printed."
}

Write-Output "secret_scan=PASS scanned_files=$($files.Count)"
