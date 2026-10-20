# Read-only host inventory. Does not read auth.json, edit settings, or run a model.
param([string]$CodexExe)
$ErrorActionPreference = 'Stop'
$extensionRoots = @(
    (Join-Path $env:USERPROFILE '.vscode/extensions'),
    (Join-Path $env:USERPROFILE '.vscode-insiders/extensions')
)
$extensions = @()
foreach ($root in $extensionRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    foreach ($directory in Get-ChildItem -LiteralPath $root -Directory -Filter 'openai.chatgpt-*') {
        $manifest = Join-Path $directory.FullName 'package.json'
        if (-not (Test-Path -LiteralPath $manifest)) { continue }
        $package = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        $bins = @(Get-ChildItem -LiteralPath $directory.FullName -Recurse -File -Filter 'codex.exe' | ForEach-Object FullName)
        $extensions += [ordered]@{path=$directory.FullName; version=$package.version; codexCandidates=$bins}
    }
}
$result = [ordered]@{
    os=[System.Environment]::OSVersion.VersionString
    powershell=$PSVersionTable.PSVersion.ToString()
    extensions=$extensions
    note='Candidates are not proof of which binary the active IDE session owns. Select and verify explicitly.'
    modelAccessVerified=$false
    ideAutoWakeVerified=$false
}
if ($CodexExe) {
    $resolved = (Resolve-Path -LiteralPath $CodexExe).Path
    if ([System.IO.Path]::GetExtension($resolved) -ne '.exe') { throw 'Use a native codex.exe.' }
    $result['codexPath']=$resolved
    $result['codexVersion']=(& $resolved --version 2>&1 | Out-String)
    $result['codexVersionExit']=$LASTEXITCODE
    $result['queueHelp']=(& $resolved queue --help 2>&1 | Out-String)
    $result['queueHelpExit']=$LASTEXITCODE
}
$result | ConvertTo-Json -Depth 8
