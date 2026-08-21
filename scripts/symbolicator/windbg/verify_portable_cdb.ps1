[CmdletBinding()]
param(
    [string]$CdbPath = 'scripts\symbolicator\.tools\windbg\x64-package\unpacked\amd64\cdb.exe',
    [string]$PackagePath = 'scripts\symbolicator\.tools\windbg\WinDbg_1.2606.22001.0_X64_msix_en-US.msix',
    [string]$X64PackagePath = 'scripts\symbolicator\.tools\windbg\x64-package\windbg_win-x64.msix',
    [string]$DumpPath = 'fixtures\p0-b01-null-read\generated\null-read.dmp',
    [string]$SymbolsPath = 'fixtures\p0-b01-null-read\generated',
    [string]$CommandsPath = 'scripts\symbolicator\windbg\cdb-p0-b01.commands',
    [string]$ManifestPath = 'fixtures\p0-b01-null-read\generated\manifest.json',
    [string]$VerifierPath = 'fixtures\p0-b01-null-read\generated\verifier-result.json',
    [string]$MetadataPath = 'fixtures\p0-b01-null-read\generated\pe-metadata.json',
    [string]$OutputPath = 'docs\evidence\windbg-p0-b01.json'
)

$ErrorActionPreference = 'Continue'
$ExpectedPackageVersion = '1.2606.22001.0'
$ExpectedPackageSha256 = '12e63fb884347567bdd35f67f7aad61b26a08f8404553dad6951a10776f7d771'
$ExpectedX64PackageSha256 = 'ae309d63724c72b9918ecc72f94a594e6dbfa4631757a7138943ac3367767ae0'
$ExpectedCdbVersion = '10.0.29617.1000'

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
}

function Get-FullPath([string]$Path, [string]$RepositoryRoot) {
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepositoryRoot $Path))
}

function Get-Sha256IfPresent([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Invoke-Captured([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $output = @()
    $exitCode = $null
    $errorText = $null
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        return [pscustomobject]@{
            exit_code = $null
            output = ''
            error = "executable not found: $FilePath"
        }
    }
    Push-Location $WorkingDirectory
    try {
        try {
            $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { $_.ToString() })
            $exitCode = $LASTEXITCODE
        }
        catch {
            $errorText = $_.Exception.Message
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        Pop-Location
    }
    [pscustomobject]@{
        exit_code = $exitCode
        output = ($output -join [Environment]::NewLine)
        error = $errorText
    }
}

function Get-FirstRegexValue([string]$Text, [string]$Pattern, [string]$Group = 'value') {
    $match = [regex]::Match($Text, $Pattern, [Text.RegularExpressions.RegexOptions]::Multiline)
    if ($match.Success -and $match.Groups[$Group].Success) {
        return $match.Groups[$Group].Value
    }
    return $null
}

function Read-JsonObject([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $json = $Value | ConvertTo-Json -Depth 16
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}

$repo = Get-RepositoryRoot
$cdb = Get-FullPath $CdbPath $repo
$package = Get-FullPath $PackagePath $repo
$x64Package = Get-FullPath $X64PackagePath $repo
$dump = Get-FullPath $DumpPath $repo
$symbols = Get-FullPath $SymbolsPath $repo
$commands = Get-FullPath $CommandsPath $repo
$manifestFile = Get-FullPath $ManifestPath $repo
$verifierFile = Get-FullPath $VerifierPath $repo
$metadataFile = Get-FullPath $MetadataPath $repo
$evidenceFile = Get-FullPath $OutputPath $repo

$failures = New-Object 'System.Collections.Generic.List[string]'
$packageHash = Get-Sha256IfPresent $package
$x64PackageHash = Get-Sha256IfPresent $x64Package
$packageStatus = if (-not $packageHash) {
    'not_present'
}
elseif ($packageHash -eq $ExpectedPackageSha256) {
    'present_verified'
}
else {
    $failures.Add("WinDbg package SHA-256 mismatch: expected $ExpectedPackageSha256, observed $packageHash")
    'present_hash_mismatch'
}
if ($x64PackageHash -and $x64PackageHash -ne $ExpectedX64PackageSha256) {
    $failures.Add("WinDbg x64 MSIX SHA-256 mismatch: expected $ExpectedX64PackageSha256, observed $x64PackageHash")
}

foreach ($required in @(
        @{ name = 'CDB'; path = $cdb },
        @{ name = 'dump'; path = $dump },
        @{ name = 'symbols'; path = $symbols },
        @{ name = 'command file'; path = $commands },
        @{ name = 'manifest'; path = $manifestFile },
        @{ name = 'verifier'; path = $verifierFile },
        @{ name = 'PE metadata'; path = $metadataFile }
    )) {
    if (-not (Test-Path -LiteralPath $required.path)) {
        $failures.Add("$($required.name) path does not exist: $($required.path)")
    }
}

$versionProbe = Invoke-Captured $cdb @('-version') (Split-Path -Parent $cdb)
$versionLine = ($versionProbe.output -split [Environment]::NewLine | Where-Object { $_ -match '^cdb version ' } | Select-Object -First 1)
$cdbVersion = if ($versionLine) { ($versionLine -replace '^cdb version\s+', '').Trim() } else { $null }
if ($versionProbe.exit_code -ne 0 -or -not $cdbVersion) {
    $failures.Add("CDB version probe failed: exit=$($versionProbe.exit_code)")
}

$manifest = Read-JsonObject $manifestFile
$verifier = Read-JsonObject $verifierFile
$metadata = Read-JsonObject $metadataFile
$analysisArgs = @('-z', $dump, '-y', $symbols, '-lines', '-cf', $commands)
$analysisProbe = if (Test-Path -LiteralPath $cdb -PathType Leaf) {
    Invoke-Captured $cdb $analysisArgs (Split-Path -Parent $cdb)
}
else {
    [pscustomobject]@{ exit_code = $null; output = ''; error = 'CDB unavailable; analysis was not run.' }
}
$analysisText = [string]$analysisProbe.output

$exceptionCode = Get-FirstRegexValue $analysisText 'Access violation\s+- code\s+(?<value>[0-9A-Fa-f]+)'
$exceptionAddressRaw = Get-FirstRegexValue $analysisText 'ExceptionAddress:\s+(?<value>[0-9A-Fa-f`]+)'
$exceptionAddress = if ($exceptionAddressRaw) { '0x' + ($exceptionAddressRaw -replace '`', '').ToUpperInvariant() } else { $null }
$function = Get-FirstRegexValue $analysisText '(?<value>[^\s]+!crashcap::trigger_null_read)\+0x[0-9A-Fa-f]+'
$sourceMatch = [regex]::Match($analysisText, '\[(?<source>[^\]]*null_read_target\.cpp)\s+@\s+(?<line>\d+)\]')
$sourcePath = if ($sourceMatch.Success) { $sourceMatch.Groups['source'].Value } else { $null }
$sourceLine = if ($sourceMatch.Success) { [int]$sourceMatch.Groups['line'].Value } else { $null }
$wrongOsSymbols = $analysisText -match 'OS symbols are WRONG|WRONG_SYMBOLS'
$symbolLoadErrors = @(
    $analysisText -split '\r?\n' |
        Where-Object { $_ -match '^\s*[A-Za-z0-9_]+\s+The system cannot find the file specified\s*$' } |
        ForEach-Object { $_.Trim() }
)
$importantOutput = @(
    $analysisText -split '\r?\n' |
        Where-Object {
            $_ -match 'cdb version|Windows Debugger Version|Access violation|ExceptionAddress:|trigger_null_read|@\s+\d+\]|OS symbols are WRONG|WRONG_SYMBOLS|Symbol search path is:|EXCEPTION_CODE_STR|STACK_TEXT|Child-SP'
        } |
        Select-Object -First 120
)

$expectedExceptionCode = if ($verifier -and $verifier.exception) { [string]$verifier.exception.code -replace '^0x', '' } else { $null }
$expectedFunction = 'crashcap::trigger_null_read'
$expectedSourceLine = 76
if ($analysisProbe.exit_code -ne 0) {
    $failures.Add("CDB dump analysis returned exit code $($analysisProbe.exit_code)")
}
if ($expectedExceptionCode -and $exceptionCode -and $expectedExceptionCode.ToLowerInvariant() -ne $exceptionCode.ToLowerInvariant()) {
    $failures.Add("CDB exception code $exceptionCode does not match verifier $expectedExceptionCode")
}
if (-not $exceptionCode) {
    $failures.Add('CDB output did not expose an access-violation code')
}
if (-not $function -or $function -notmatch [regex]::Escape($expectedFunction)) {
    $failures.Add("CDB output did not resolve $expectedFunction")
}
if (-not $sourcePath -or $sourceLine -ne $expectedSourceLine) {
    $failures.Add("CDB output did not resolve null_read_target.cpp line $expectedSourceLine")
}

$status = if ($failures.Count -eq 0) {
    if ($wrongOsSymbols) { 'PASS_WITH_OS_SYMBOL_BOUNDARY' } else { 'PASS' }
}
else {
    'FAIL'
}
$record = [ordered]@{
    schema_version = 'portable-cdb-evidence-v0.1'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    status = $status
    repository = $repo
    official_package = [ordered]@{
        package_id = 'Microsoft.WinDbg'
        version = $ExpectedPackageVersion
        source = 'winget'
        package_path = $package
        expected_sha256 = $ExpectedPackageSha256
        observed_sha256 = $packageHash
        status = $packageStatus
        x64_package_path = $x64Package
        x64_package_expected_sha256 = $ExpectedX64PackageSha256
        x64_package_observed_sha256 = $x64PackageHash
        x64_package_status = if (-not $x64PackageHash) { 'not_present' } elseif ($x64PackageHash -eq $ExpectedX64PackageSha256) { 'present_verified' } else { 'present_hash_mismatch' }
        installation = 'not_installed; extracted from official MSIX into ignored .tools'
    }
    cdb = [ordered]@{
        path = $cdb
        sha256 = Get-Sha256IfPresent $cdb
        version = $cdbVersion
        expected_version = $ExpectedCdbVersion
        version_probe_exit_code = $versionProbe.exit_code
        version_probe_output = $versionProbe.output
    }
    inputs = [ordered]@{
        dump = $dump
        symbols_path = $symbols
        command_file = $commands
        manifest = $manifestFile
        verifier = $verifierFile
        pe_metadata = $metadataFile
        code_id = if ($metadata) { $metadata.code_id } else { $null }
        debug_id = if ($metadata) { $metadata.debug_id } else { $null }
    }
    command = [ordered]@{
        executable = $cdb
        arguments = $analysisArgs
        working_directory = (Split-Path -Parent $cdb)
    }
    result = [ordered]@{
        exit_code = $analysisProbe.exit_code
        exception_code = if ($exceptionCode) { '0x' + $exceptionCode.ToUpperInvariant() } else { $null }
        exception_address = $exceptionAddress
        function = $function
        source = if ($sourcePath) { [ordered]@{ path = $sourcePath; line = $sourceLine } } else { $null }
        os_symbols_wrong = $wrongOsSymbols
        missing_os_symbol_modules = $symbolLoadErrors
        important_output = $importantOutput
    }
    validation = [ordered]@{
        passed = ($failures.Count -eq 0)
        failures = $failures.ToArray()
        application_pe_pdb_symbols_resolved = [bool]($function -and $sourcePath)
        local_dbghelp_verifier_agrees = [bool]($expectedExceptionCode -and $exceptionCode -and $expectedExceptionCode.ToLowerInvariant() -eq $exceptionCode.ToLowerInvariant())
        boundary = 'CDB resolved the fixture PE/PDB function and source line. Windows OS symbols were not supplied, so !analyze reports WRONG_SYMBOLS for ntdll; this does not invalidate the application-symbol result.'
    }
}
Write-Utf8Json $evidenceFile $record
$record | ConvertTo-Json -Depth 16
if ($failures.Count -eq 0) { exit 0 } else { exit 2 }
