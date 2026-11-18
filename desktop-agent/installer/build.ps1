param(
    [Parameter(Mandatory)] [string] $Python,
    [Parameter(Mandatory)] [string] $InnoCompiler,
    [Parameter(Mandatory)] [string] $OutputDirectory,
    [uri] $ConsumerRelay = [uri]'https://flicker-link-pro.onrender.com',
    [string] $ExpectedSigner = 'Eric Williams',
    [string] $SignToolCommand = 'signtool.exe sign /a /n $qEric Williams$q /fd SHA256 /tr https://timestamp.digicert.com /td SHA256 $f'
)

$ErrorActionPreference = 'Stop'
$expectedOrigin = 'https://flicker-link-pro.onrender.com'
if (!$ConsumerRelay.IsAbsoluteUri -or $ConsumerRelay.GetLeftPart([UriPartial]::Authority) -ne $expectedOrigin -or
    $ConsumerRelay.AbsolutePath -ne '/' -or $ConsumerRelay.Query -or $ConsumerRelay.Fragment -or
    $ConsumerRelay.UserInfo) {
    throw "The consumer installer must target $expectedOrigin."
}
if ([string]::IsNullOrWhiteSpace($ExpectedSigner) -or [string]::IsNullOrWhiteSpace($SignToolCommand)) {
    throw 'A code-signing command and expected publisher name are required.'
}

$agent = Split-Path -Parent $PSScriptRoot
$build = Join-Path ([IO.Path]::GetTempPath()) ('flicker-link-pro-build-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $build, $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

$icon = Join-Path $agent 'flicker-link.ico'
$catalog = Join-Path $agent 'tool_catalog.json'
$entry = Join-Path $PSScriptRoot 'consumer_entry.py'
if (!(Test-Path -LiteralPath $icon) -or !(Test-Path -LiteralPath $catalog) -or !(Test-Path -LiteralPath $entry)) {
    throw 'The installer is missing a required icon, tool catalog, or Windows app entry point.'
}
Copy-Item -LiteralPath $icon -Destination (Join-Path $build 'flicker-link.ico')

$relayFile = Join-Path $build 'consumer-relay.txt'
Set-Content -LiteralPath $relayFile -Value $expectedOrigin -Encoding ascii
$consumerData = @('--add-data', "${relayFile}:." )
$defines = @("/DBuildRoot=$build")
$name = 'FlickerLinkPro'

& $Python -m PyInstaller --noconfirm --clean --onedir --console --name $name @consumerData `
    --icon (Join-Path $build 'flicker-link.ico') `
    --add-data "$(Join-Path $build 'flicker-link.ico'):." `
    --add-data "${catalog}:." --collect-submodules websockets `
    --distpath $build --workpath (Join-Path $build 'work') --specpath $build `
    --paths $agent $entry
if ($LASTEXITCODE -ne 0) { throw 'Could not bundle the Windows app.' }

$signArg = "--signtool=FlickerLinkProSign=$SignToolCommand"
& $InnoCompiler @defines $signArg "/O$OutputDirectory" (Join-Path $PSScriptRoot 'FlickerLinkPro.iss')
if ($LASTEXITCODE -ne 0) { throw 'Could not build and sign the Windows installer.' }

$setup = Join-Path $OutputDirectory 'FlickerLinkPro-Setup-x64.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $setup
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike "*$ExpectedSigner*") {
    throw "The installer signature is not valid for the expected publisher '$ExpectedSigner'."
}
Get-FileHash -Algorithm SHA256 -LiteralPath $setup
Write-Host "Valid Authenticode signature: $($signature.SignerCertificate.Subject)"
