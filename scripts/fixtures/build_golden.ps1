[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$PreserveExistingP0,
    [string[]]$Only
)

$ErrorActionPreference = 'Stop'

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $json = $Value | ConvertTo-Json -Depth 16
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine,
                            (New-Object Text.UTF8Encoding($false)))
}

function Find-VcVars {
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    $vswhere = Join-Path $programFilesX86 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
        $installations = @(& $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null)
        if ($LASTEXITCODE -eq 0) {
            foreach ($installation in $installations) {
                $candidate = Join-Path $installation 'VC\Auxiliary\Build\vcvarsall.bat'
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return (Resolve-Path -LiteralPath $candidate).Path
                }
            }
        }
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat'),
        (Join-Path $programFilesX86 'Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat'),
        (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat'),
        (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat'),
        (Join-Path $programFilesX86 'Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'No VS vcvarsall.bat found.'
}

function Import-VcEnvironment([string]$VcVarsPath, [string]$Architecture) {
    $command = 'call "{0}" {1} >nul && set' -f $VcVarsPath, $Architecture
    $lines = & cmd.exe /d /s /c $command
    if ($LASTEXITCODE -ne 0) {
        throw "vcvarsall failed for $Architecture with exit code $LASTEXITCODE"
    }
    foreach ($line in $lines) {
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2 -and $parts[0] -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            Set-Item -Path ("Env:" + $parts[0]) -Value $parts[1]
        }
    }
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "vcvarsall returned no cl.exe for $Architecture"
    }
}

function Invoke-NativeChecked([string]$FilePath, [string[]]$Arguments) {
    $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Build-Binary([string]$Source, [string]$Exe, [string]$Pdb,
                      [string]$Obj, [string]$Flavor, [string]$IncludeDirectory) {
    $common = @('/nologo', '/std:c++20', '/EHsc', '/MT', '/W4', '/FC',
                '/DUNICODE', '/D_UNICODE', "/I$IncludeDirectory")
    $optimization = if ($Flavor -eq 'release') {
        @('/O2', '/Ob3', '/Zi')
    } else {
        @('/Od', '/Zi')
    }
    $arguments = $common + $optimization + @(
        $Source,
        "/Fo:$Obj",
        "/Fe:$Exe",
        "/Fd:$Pdb",
        '/link',
        '/DEBUG',
        "/PDB:$Pdb",
        '/INCREMENTAL:NO'
    )
    Invoke-NativeChecked 'cl.exe' $arguments | Out-Null
}

function Copy-IfPresent([string]$Source, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    if ($Source) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Invoke-Collector([string]$Collector, [string]$Scenario,
                          [string]$Target, [string]$Dump, [string]$Context,
                          [string]$Result, [bool]$NoException,
                          [bool]$TerminateAfterDump) {
    $nonce = [Guid]::NewGuid().ToString('N')
    $ready = "Local\CrashCapGoldenReady_$nonce"
    $release = "Local\CrashCapGoldenRelease_$nonce"
    $arguments = @(
        '--scenario', $Scenario,
        '--target', $Target,
        '--dump', $Dump,
        '--context', $Context,
        '--result', $Result,
        '--ready-event', $ready,
        '--release-event', $release
    )
    if ($NoException) { $arguments += '--no-exception' }
    if ($TerminateAfterDump) { $arguments += '--terminate-after-dump' }
    $output = @(& $Collector @arguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "MiniDumpWriteDump collector failed ($exitCode) for $Scenario`n$($output -join [Environment]::NewLine)"
    }
    if (-not (Test-Path -LiteralPath $Result -PathType Leaf)) {
        throw "Collector did not write result: $Result"
    }
    $collectorResult = Get-Content -LiteralPath $Result -Raw | ConvertFrom-Json
    if (-not $collectorResult.dump_ok) {
        throw "MiniDumpWriteDump reported dump_ok=false for $Scenario"
    }
    return [pscustomobject]@{
        exit_code = $exitCode
        output = ($output -join [Environment]::NewLine)
        result = $collectorResult
    }
}

function Invoke-Verifier([string]$Verifier, [string]$Dump) {
    $output = @(& $Verifier '--dump' $Dump 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    $json = $null
    try { $json = ($output -join [Environment]::NewLine) | ConvertFrom-Json } catch {}
    return [pscustomobject]@{
        exit_code = $exitCode
        output = ($output -join [Environment]::NewLine)
        result = $json
    }
}

function Mutate-Dump([string]$Path, [string]$Treatment) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($Treatment -eq 'corrupt_dump') {
        if ($bytes.Length -lt 4) { throw "Cannot corrupt a dump shorter than four bytes: $Path" }
        $bytes[0] = 0x58; $bytes[1] = 0x58; $bytes[2] = 0x58; $bytes[3] = 0x58
        [IO.File]::WriteAllBytes($Path, $bytes)
    } elseif ($Treatment -eq 'truncated_dump') {
        $length = [Math]::Min(64, $bytes.Length)
        $short = New-Object byte[] $length
        [Array]::Copy($bytes, $short, $length)
        [IO.File]::WriteAllBytes($Path, $short)
    }
}

$repo = Get-RepositoryRoot
$sourceDirectory = Join-Path $repo 'scripts\fixtures'
$fixturesRoot = Join-Path $repo 'fixtures'
$buildRoot = Join-Path $fixturesRoot '.build\golden'
$vcvars = Find-VcVars
$scenarioTable = @(
    [pscustomobject]@{ id='p0-b01-null-read'; title='x64 MSVC null-pointer read'; category='P0-D03'; target='null_read'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d03-null-write'; title='x64 MSVC null-pointer write'; category='P0-D03'; target='null_write'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='write'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d03-illegal-execute'; title='x64 illegal execute address'; category='P0-D03'; target='illegal_execute'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='execute'; fault='0x0000000000000001'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d03-cpp-uncaught'; title='x64 uncaught C++ exception'; category='P0-D03'; target='cpp_uncaught'; flavor='debug'; architecture='x86_64'; exception='0xE06D7363'; access='none'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d03-std-terminate'; title='x64 std::terminate'; category='P0-D03'; target='std_terminate'; flavor='debug'; architecture='x86_64'; exception='0xE0000001'; access='none'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d03-abort'; title='x64 abort'; category='P0-D03'; target='abort'; flavor='debug'; architecture='x86_64'; exception='0x40000015'; access='none'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d04-stack-overflow'; title='x64 stack overflow'; category='P0-D04'; target='stack_overflow'; flavor='debug'; architecture='x86_64'; exception='0xC00000FD'; access='none'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d04-multithread'; title='x64 worker-thread crash'; category='P0-D04'; target='multithread'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='write'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d04-release-inline'; title='x64 Release optimized inline crash'; category='P0-D04'; target='release_inline'; flavor='release'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d04-async-thread-pool'; title='x64 Windows thread-pool crash'; category='P0-D04'; target='async_thread_pool'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d04-deep-business-stack'; title='x64 deep business stack'; category='P0-D04'; target='deep_business_stack'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='complete'; no_exception=$false; terminate=$false; cdb=$true },
    [pscustomobject]@{ id='p0-d05-missing-pdb'; title='valid dump with missing PDB'; category='P0-D05'; target='null_read'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='missing_pdb'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d05-wrong-pdb'; title='valid dump with wrong PDB'; category='P0-D05'; target='null_read'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='wrong_pdb'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d05-missing-pe'; title='valid dump with missing PE'; category='P0-D05'; target='null_read'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='missing_pe'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d05-pe-mismatch'; title='dump with PE/PDB mismatch'; category='P0-D05'; target='null_read'; flavor='debug'; architecture='x86_64'; exception='0xC0000005'; access='read'; fault='0x0000000000000000'; treatment='pe_mismatch'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d06-corrupt-dmp'; title='corrupt minidump'; category='P0-D06'; target='null_read'; flavor='debug'; architecture='x86_64'; exception=$null; access='none'; fault='0x0000000000000000'; treatment='corrupt_dump'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d06-truncated-dmp'; title='truncated minidump'; category='P0-D06'; target='null_read'; flavor='debug'; architecture='x86_64'; exception=$null; access='none'; fault='0x0000000000000000'; treatment='truncated_dump'; no_exception=$false; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d06-non-x64'; title='real x86 no-exception dump'; category='P0-D06'; target='unknown_no_exception'; flavor='debug'; architecture='x86'; exception=$null; access='none'; fault='0x0000000000000000'; treatment='non_x64'; no_exception=$true; terminate=$false; cdb=$false },
    [pscustomobject]@{ id='p0-d06-explicit-hang'; title='declared explicit hang sample'; category='P0-D06'; target='explicit_hang'; flavor='debug'; architecture='x86_64'; exception=$null; access='none'; fault='0x0000000000000000'; treatment='explicit_hang'; no_exception=$true; terminate=$true; cdb=$false },
    [pscustomobject]@{ id='p0-d06-unknown-no-exception'; title='unknown no-exception dump'; category='P0-D06'; target='unknown_no_exception'; flavor='debug'; architecture='x86_64'; exception=$null; access='none'; fault='0x0000000000000000'; treatment='unknown_no_exception'; no_exception=$true; terminate=$false; cdb=$false }
)

if ($scenarioTable.Count -ne 20) {
    throw "Internal Golden table must contain exactly 20 fixtures, got $($scenarioTable.Count)"
}
$selected = if ($Only -and $Only.Count -gt 0) {
    @($scenarioTable | Where-Object { $_.id -in $Only })
} else { @($scenarioTable) }
if ($selected.Count -eq 0) { throw 'No matching fixtures selected.' }

New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
Import-VcEnvironment $vcvars 'x64'
$collectorExe = Join-Path $buildRoot 'golden_collector.exe'
$collectorPdb = Join-Path $buildRoot 'golden_collector.pdb'
$collectorObj = Join-Path $buildRoot 'golden_collector.obj'
$verifierExe = Join-Path $buildRoot 'verify_golden_minidump.exe'
$verifierPdb = Join-Path $buildRoot 'verify_golden_minidump.pdb'
$verifierObj = Join-Path $buildRoot 'verify_golden_minidump.obj'
$targetSource = Join-Path $sourceDirectory 'golden_target.cpp'
$collectorSource = Join-Path $sourceDirectory 'golden_collector.cpp'
$verifierSource = Join-Path $sourceDirectory 'verify_golden_minidump.cpp'
Build-Binary $collectorSource $collectorExe $collectorPdb $collectorObj 'release' $sourceDirectory
Build-Binary $verifierSource $verifierExe $verifierPdb $verifierObj 'release' $sourceDirectory

$debugTarget = Join-Path $buildRoot 'golden_target_debug.exe'
$debugPdb = Join-Path $buildRoot 'golden_target_debug.pdb'
$debugObj = Join-Path $buildRoot 'golden_target_debug.obj'
$releaseTarget = Join-Path $buildRoot 'golden_target_release.exe'
$releasePdb = Join-Path $buildRoot 'golden_target_release.pdb'
$releaseObj = Join-Path $buildRoot 'golden_target_release.obj'
Build-Binary $targetSource $debugTarget $debugPdb $debugObj 'debug' $sourceDirectory
Build-Binary $targetSource $releaseTarget $releasePdb $releaseObj 'release' $sourceDirectory

Import-VcEnvironment $vcvars 'x86'
$x86Target = Join-Path $buildRoot 'golden_target_x86.exe'
$x86Pdb = Join-Path $buildRoot 'golden_target_x86.pdb'
$x86Obj = Join-Path $buildRoot 'golden_target_x86.obj'
Build-Binary $targetSource $x86Target $x86Pdb $x86Obj 'debug' $sourceDirectory

Import-VcEnvironment $vcvars 'x64'
$extractor = Join-Path $sourceDirectory 'extract_pe_metadata.py'
$runtimeResults = New-Object 'System.Collections.Generic.List[object]'
foreach ($scenario in $selected) {
    $fixtureDirectory = Join-Path $fixturesRoot $scenario.id
    $generated = Join-Path $fixtureDirectory 'generated'
    if ($PreserveExistingP0 -and $scenario.id -eq 'p0-b01-null-read' -and
        (Test-Path -LiteralPath (Join-Path $generated 'manifest.json') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $generated 'verifier-result.json') -PathType Leaf)) {
        $legacyVerifier = Get-Content -LiteralPath (Join-Path $generated 'verifier-result.json') -Raw | ConvertFrom-Json
        if (-not (Test-Path -LiteralPath (Join-Path $generated 'validation.json') -PathType Leaf)) {
            Write-Utf8Json (Join-Path $generated 'validation.json') ([ordered]@{
                schema_version = 'golden-runtime-validation-v0.1'
                fixture_id = $scenario.id
                status = 'preserved_existing_verified'
                collector = 'MiniDumpWriteDump'
                verifier = $legacyVerifier
                target_architecture = 'x86_64'
                architecture_boundary = 'Existing P0-B01 independent DbgHelp-verified baseline was preserved so the Symbolicator evidence remains aligned.'
            })
        }
        $runtimeResults.Add([pscustomobject]@{
            fixture_id = $scenario.id
            status = 'preserved_existing_verified'
            treatment = 'complete'
            architecture = 'x86_64'
            has_exception = $true
            dump_size = (Get-Item -LiteralPath (Join-Path $generated 'null-read.dmp')).Length
        })
        continue
    }
    if ($Clean -and (Test-Path -LiteralPath $generated)) {
        Remove-Item -LiteralPath $generated -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $generated | Out-Null

    $baseTarget = if ($scenario.architecture -eq 'x86') { $x86Target } elseif ($scenario.flavor -eq 'release') { $releaseTarget } else { $debugTarget }
    $basePdb = if ($scenario.architecture -eq 'x86') { $x86Pdb } elseif ($scenario.flavor -eq 'release') { $releasePdb } else { $debugPdb }
    $baseMetadataPath = Join-Path $generated 'base-pe-metadata.json'
    Invoke-NativeChecked 'python' @('-B', $extractor, '--pe', $baseTarget, '--output', $baseMetadataPath) | Out-Null
    $baseMetadata = Get-Content -LiteralPath $baseMetadataPath -Raw | ConvertFrom-Json

    $targetArtifact = Join-Path $generated 'target.exe'
    $pdbArtifact = Join-Path $generated 'target.pdb'
    $dumpPath = Join-Path $generated 'dump.dmp'
    $contextPath = Join-Path $generated 'exception-context.bin'
    $collectorResultPath = Join-Path $generated 'collector-result.json'
    $verifierResultPath = Join-Path $generated 'verifier-result.json'
    $scenarioTarget = if ($scenario.treatment -in @('missing_pdb', 'wrong_pdb', 'missing_pe', 'pe_mismatch', 'corrupt_dump', 'truncated_dump')) { $debugTarget } else { $baseTarget }
    $collector = Invoke-Collector $collectorExe $scenario.target $scenarioTarget $dumpPath $contextPath $collectorResultPath ([bool]$scenario.no_exception) ([bool]$scenario.terminate)

    if ($scenario.treatment -eq 'missing_pdb') {
        Copy-IfPresent $debugTarget $targetArtifact
    } elseif ($scenario.treatment -eq 'wrong_pdb') {
        Copy-IfPresent $debugTarget $targetArtifact
        Copy-IfPresent $releasePdb $pdbArtifact
    } elseif ($scenario.treatment -eq 'missing_pe') {
        Copy-IfPresent $debugPdb $pdbArtifact
    } elseif ($scenario.treatment -eq 'pe_mismatch') {
        Copy-IfPresent $releaseTarget $targetArtifact
        Copy-IfPresent $debugPdb $pdbArtifact
    } elseif ($scenario.treatment -in @('corrupt_dump', 'truncated_dump')) {
        Copy-IfPresent $debugTarget $targetArtifact
        Copy-IfPresent $debugPdb $pdbArtifact
        Mutate-Dump $dumpPath $scenario.treatment
    } else {
        Copy-IfPresent $baseTarget $targetArtifact
        Copy-IfPresent $basePdb $pdbArtifact
    }

    $metadataPath = Join-Path $generated 'pe-metadata.json'
    if (Test-Path -LiteralPath $targetArtifact -PathType Leaf) {
        $metadataProbe = @(& python -B $extractor '--pe' $targetArtifact '--output' $metadataPath 2>&1 | ForEach-Object { $_.ToString() })
        if ($LASTEXITCODE -ne 0) { throw "PE metadata extraction failed for $($scenario.id): $($metadataProbe -join ' ')" }
    }

    $verification = Invoke-Verifier $verifierExe $dumpPath
    Write-Utf8Json $verifierResultPath ([ordered]@{
        schema_version = 'golden-verifier-result-v0.1'
        fixture_id = $scenario.id
        exit_code = $verification.exit_code
        output = $verification.output
        result = $verification.result
    })
    $expectedValid = $scenario.treatment -notin @('corrupt_dump', 'truncated_dump')
    if ($expectedValid -and (-not $verification.result -or $verification.result.valid_dump -ne $true)) {
        throw "Verifier did not accept generated dump for $($scenario.id): $($verification.output)"
    }
    if (-not $expectedValid -and $verification.result -and $verification.result.valid_dump -eq $true) {
        throw "Verifier unexpectedly accepted rejected dump for $($scenario.id)"
    }
    if ($scenario.no_exception -and $verification.result -and $verification.result.has_exception -eq $true) {
        throw "No-exception fixture has an exception stream: $($scenario.id)"
    }
    if (-not $scenario.no_exception -and $expectedValid -and (-not $verification.result -or $verification.result.has_exception -ne $true)) {
        throw "Crash fixture has no exception stream: $($scenario.id)"
    }
    if ($scenario.architecture -eq 'x86' -and $baseMetadata.architecture -ne 'x86') {
        throw "Non-x64 fixture target PE was not x86: $($scenario.id)"
    }

    $validation = [ordered]@{
        schema_version = 'golden-runtime-validation-v0.1'
        fixture_id = $scenario.id
        collector = $collector.result
        verifier = [ordered]@{ exit_code = $verification.exit_code; output = $verification.output; result = $verification.result }
        target_architecture = $baseMetadata.architecture
        architecture_boundary = if ($scenario.architecture -eq 'x86') { 'The x64 collector writes a real x86 target dump; MiniDump SystemInfoStream reflects the collector host architecture, so the target PE architecture is authoritative for this fixture.' } else { $null }
        dump = [ordered]@{ path = 'generated/dump.dmp'; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant(); size = (Get-Item -LiteralPath $dumpPath).Length }
        artifacts = [ordered]@{
            pe_present = Test-Path -LiteralPath $targetArtifact -PathType Leaf
            pdb_present = Test-Path -LiteralPath $pdbArtifact -PathType Leaf
            pe_sha256 = if (Test-Path -LiteralPath $targetArtifact -PathType Leaf) { (Get-FileHash -Algorithm SHA256 -LiteralPath $targetArtifact).Hash.ToLowerInvariant() } else { $null }
            pdb_sha256 = if (Test-Path -LiteralPath $pdbArtifact -PathType Leaf) { (Get-FileHash -Algorithm SHA256 -LiteralPath $pdbArtifact).Hash.ToLowerInvariant() } else { $null }
            treatment = $scenario.treatment
        }
        status = 'verified_local'
    }
    Write-Utf8Json (Join-Path $generated 'validation.json') $validation

    $manifest = [ordered]@{
        schema_version = 'fixture-artifact-manifest-v0.2'
        fixture_id = $scenario.id
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        generator = [ordered]@{
            script = 'scripts/fixtures/build_golden.ps1'
            target_source = 'scripts/fixtures/golden_target.cpp'
            collector_source = 'scripts/fixtures/golden_collector.cpp'
            collector_api = 'MiniDumpWriteDump'
            process_model = 'independent collector process'
            compiler = 'MSVC'
            architecture = $scenario.architecture
            flavor = $scenario.flavor
            vcvarsall = $vcvars
        }
        target = [ordered]@{
            path = if (Test-Path -LiteralPath $targetArtifact -PathType Leaf) { 'generated/target.exe' } else { $null }
            pdb = if (Test-Path -LiteralPath $pdbArtifact -PathType Leaf) { 'generated/target.pdb' } else { $null }
            source_metadata = 'generated/base-pe-metadata.json'
            code_id = $baseMetadata.code_id
            debug_id = $baseMetadata.debug_id
            architecture = $baseMetadata.architecture
        }
        dump = [ordered]@{
            path = 'generated/dump.dmp'
            collector_result = 'generated/collector-result.json'
            validation = 'generated/validation.json'
            no_exception = [bool]$scenario.no_exception
            treatment = $scenario.treatment
        }
    }
    Write-Utf8Json (Join-Path $generated 'manifest.json') $manifest
    $runtimeResults.Add([pscustomobject]@{
        fixture_id = $scenario.id
        status = 'verified_local'
        treatment = $scenario.treatment
        architecture = $baseMetadata.architecture
        has_exception = if ($verification.result) { $verification.result.has_exception } else { $false }
        dump_size = (Get-Item -LiteralPath $dumpPath).Length
    })
}

$summary = [ordered]@{
    schema_version = 'golden-build-summary-v0.1'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    count = $runtimeResults.Count
    fixtures = $runtimeResults.ToArray()
}
Write-Utf8Json (Join-Path $fixturesRoot 'golden-build-summary.json') $summary
$summary | ConvertTo-Json -Depth 12
