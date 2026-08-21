[CmdletBinding()]
param(
    [string]$CdbPath = 'scripts\symbolicator\.tools\windbg\x64-package\unpacked\amd64\cdb.exe',
    [string[]]$Only
)

$ErrorActionPreference = 'Continue'

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Get-FullPath([string]$Path, [string]$Root) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $Root $Path))
}

function Write-Utf8([string]$Path, [string]$Content) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding($false)))
}

function Get-First([string]$Text, [string]$Pattern, [string]$Group = 'value') {
    $match = [regex]::Match($Text, $Pattern, [Text.RegularExpressions.RegexOptions]::Multiline)
    if ($match.Success -and $match.Groups[$Group].Success) { return $match.Groups[$Group].Value }
    return $null
}

$repo = Get-RepositoryRoot
$cdb = Get-FullPath $CdbPath $repo
$commands = Get-FullPath 'scripts\fixtures\cdb-golden.commands' $repo
$fixturesRoot = Join-Path $repo 'fixtures'
$complete = @(
    'p0-b01-null-read', 'p0-d03-null-write', 'p0-d03-illegal-execute',
    'p0-d03-cpp-uncaught', 'p0-d03-std-terminate', 'p0-d03-abort',
    'p0-d04-stack-overflow', 'p0-d04-multithread', 'p0-d04-release-inline',
    'p0-d04-async-thread-pool', 'p0-d04-deep-business-stack'
)
$selected = if ($Only -and $Only.Count -gt 0) { @($complete | Where-Object { $_ -in $Only }) } else { $complete }
if ($selected.Count -eq 0) { throw 'No complete Golden fixtures selected.' }
if (-not (Test-Path -LiteralPath $cdb -PathType Leaf)) { throw "CDB not found: $cdb" }

$versionOutput = @(& $cdb '-version' 2>&1 | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
$version = Get-First $versionOutput '^cdb version\s+(?<value>.+)$'
$failures = New-Object 'System.Collections.Generic.List[string]'
foreach ($fixtureId in $selected) {
    $fixtureDirectory = Join-Path $fixturesRoot $fixtureId
    $generated = Join-Path $fixtureDirectory 'generated'
    $dump = if (Test-Path -LiteralPath (Join-Path $generated 'dump.dmp')) { Join-Path $generated 'dump.dmp' } else { Join-Path $generated 'null-read.dmp' }
    $target = if (Test-Path -LiteralPath (Join-Path $generated 'target.exe')) { Join-Path $generated 'target.exe' } else { Join-Path $generated 'null_read_target.exe' }
    $pdb = if (Test-Path -LiteralPath (Join-Path $generated 'target.pdb')) { Join-Path $generated 'target.pdb' } else { Join-Path $generated 'null_read_target.pdb' }
    $expected = Get-Content -LiteralPath (Join-Path $fixtureDirectory 'expected.json') -Raw | ConvertFrom-Json
    $businessFrames = @($expected.expected.business_frames)
    $output = @(& $cdb '-z' $dump '-y' $generated '-lines' '-cf' $commands 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    $text = $output -join [Environment]::NewLine
    $frameLines = New-Object 'System.Collections.Generic.List[string]'
    foreach ($frame in $businessFrames) {
        $line = $output | Where-Object { $_ -match [regex]::Escape([string]$frame) } | Select-Object -First 1
        if ($line) {
            # Keep the declared symbol identity but omit raw addresses, stack
            # arguments, usernames and absolute paths from the transcript.
            $frameLines.Add("resolved: $frame")
        }
    }
    $sourceMatches = @(
        [regex]::Matches($text, '\[[^\]]*\\(?<file>[^\\\]]+\.cpp)\s+@\s+(?<line>\d+)\]') |
            ForEach-Object { "$($_.Groups['file'].Value):$($_.Groups['line'].Value)" } |
            Select-Object -Unique
    )
    $exceptionCode = Get-First $text 'ExceptionCode:\s+(?<value>[0-9A-Fa-f]+)'
    if (-not $exceptionCode) { $exceptionCode = Get-First $text 'Access violation\s+- code\s+(?<value>[0-9A-Fa-f]+)' }
    $exceptionAddress = Get-First $text 'ExceptionAddress:\s+(?<value>[0-9A-Fa-f`]+)'
    $wrongSymbols = $text -match 'OS symbols are WRONG|WRONG_SYMBOLS'
    $boundary = if ($frameLines.Count -ge 3) {
        'At least three expected business frames were found in the CDB transcript.'
    } elseif ($businessFrames.Count -lt 3) {
        "Only $($businessFrames.Count) stable business frame(s) are declared by this fixture; remaining frames are runtime/recursive/inline boundary."
    } else {
        "Fewer than three declared business frames were visible; preserve the available frame evidence and do not infer missing frames."
    }
    if ($exitCode -ne 0) { $failures.Add("$fixtureId CDB exit code $exitCode") }
    if ($frameLines.Count -eq 0) { $failures.Add("$fixtureId no expected business frame resolved") }
    $summary = @(
        "schema_version: golden-cdb-summary-v0.1",
        "fixture_id: $fixtureId",
        "cdb_version: $version",
        "command: cdb.exe -z <generated dump> -y <generated artifact directory> -lines -cf scripts/fixtures/cdb-golden.commands",
        "exit_code: $exitCode",
        "exception_code: $(if ($exceptionCode) { '0x' + $exceptionCode.ToUpperInvariant() } else { '<not exposed>' })",
        "exception_address: $(if ($exceptionAddress) { '<redacted: absolute address present>' } else { '<not exposed>' })",
        "business_frame_count: $($frameLines.Count)",
        "business_frames:"
    )
    $summary += @($frameLines | ForEach-Object { "  - $_" })
    $summary += @(
        "source_locations: $(if ($sourceMatches.Count) { $sourceMatches -join ', ' } else { '<not exposed>' })",
        "os_symbols_wrong: $wrongSymbols",
        "boundary: $boundary",
        "redaction: absolute addresses, source paths and machine-specific stack text omitted; binary dump/PE/PDB are ignored"
    )
    Write-Utf8 (Join-Path $fixtureDirectory 'reference\cdb-summary.txt') (($summary -join [Environment]::NewLine) + [Environment]::NewLine)
}
Write-Output ("Generated CDB summaries: {0}" -f $selected.Count)
if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 2
}
