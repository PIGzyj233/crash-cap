[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$CrossModule,
    [switch]$SystemWaitThread
)

$ErrorActionPreference = 'Stop'

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
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
        (Join-Path $programFilesX86 'Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'No VS vcvarsall.bat found. Install an x64 MSVC workload before generating Windows fixtures.'
}

function Import-VcEnvironment([string]$VcVarsPath) {
    $command = 'call "{0}" x64 >nul && set' -f $VcVarsPath
    $lines = & cmd.exe /d /s /c $command
    if ($LASTEXITCODE -ne 0) {
        throw "vcvarsall failed with exit code $LASTEXITCODE"
    }
    foreach ($line in $lines) {
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2 -and $parts[0] -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            Set-Item -Path ("Env:" + $parts[0]) -Value $parts[1]
        }
    }
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw 'vcvarsall returned no cl.exe in PATH'
    }
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}

$repo = Get-RepositoryRoot
if ($CrossModule -and $SystemWaitThread) {
    throw 'CrossModule and SystemWaitThread are separate fixture variants'
}
$fixtureId = if ($SystemWaitThread) { 'qai-q16-system-wait' } elseif ($CrossModule) { 'qai-c08-cross-module' } else { 'p0-b01-null-read' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repo "fixtures\$fixtureId\generated"
}
$OutputDirectory = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$sourceDirectory = Join-Path $repo 'scripts\fixtures'
$targetSource = Join-Path $sourceDirectory 'null_read_target.cpp'
$collectorSource = Join-Path $sourceDirectory 'mini_dump_collector.cpp'
$verifierSource = Join-Path $sourceDirectory 'verify_minidump.cpp'
$includeDirectory = $sourceDirectory

$vcvarsPath = Find-VcVars
Import-VcEnvironment $vcvarsPath
$vcVersionFile = Join-Path (Split-Path (Split-Path (Split-Path (Split-Path $vcvarsPath -Parent) -Parent) -Parent) -Parent) 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt'
$vcVersion = if (Test-Path -LiteralPath $vcVersionFile) { (Get-Content -LiteralPath $vcVersionFile -Raw).Trim() } else { 'unknown' }

$targetExe = Join-Path $OutputDirectory 'null_read_target.exe'
$targetPdb = Join-Path $OutputDirectory 'null_read_target.pdb'
$collectorExe = Join-Path $OutputDirectory 'mini_dump_collector.exe'
$collectorPdb = Join-Path $OutputDirectory 'mini_dump_collector.pdb'
$verifierExe = Join-Path $OutputDirectory 'verify_minidump.exe'
$verifierPdb = Join-Path $OutputDirectory 'verify_minidump.pdb'

$common = @('/nologo', '/std:c++20', '/EHsc', '/MT', '/W4', '/DUNICODE', '/D_UNICODE', "/I$includeDirectory")
Push-Location $repo
try {
    $targetOptions = @()
    $targetLibraries = @()
    if ($SystemWaitThread) {
        $targetOptions = @('/DCRASHCAP_SYSTEM_WAIT_THREAD')
    }
    if ($CrossModule) {
        $faultDll = Join-Path $OutputDirectory 'unknown_fault.dll'
        $faultPdb = Join-Path $OutputDirectory 'unknown_fault.pdb'
        $faultLib = Join-Path $OutputDirectory 'unknown_fault.lib'
        Invoke-Native 'cl.exe' ($common + @('/LD', '/Od', '/Zi', (Join-Path $sourceDirectory 'unknown_fault.cpp'), "/Fe:$faultDll", "/Fd:$faultPdb", '/link', '/DEBUG', "/PDB:$faultPdb", "/IMPLIB:$faultLib", '/INCREMENTAL:NO'))
        $targetOptions = @('/DCRASHCAP_CROSS_MODULE_FIXTURE')
        $targetLibraries = @($faultLib)
    }
    Invoke-Native 'cl.exe' ($common + $targetOptions + @('/Od', '/Zi', $targetSource, "/Fe:$targetExe", "/Fd:$targetPdb", '/link', '/DEBUG', "/PDB:$targetPdb", '/INCREMENTAL:NO') + $targetLibraries)
    Invoke-Native 'cl.exe' ($common + @('/O2', '/Zi', $collectorSource, "/Fe:$collectorExe", "/Fd:$collectorPdb", '/link', '/DEBUG', "/PDB:$collectorPdb", '/INCREMENTAL:NO'))
    Invoke-Native 'cl.exe' ($common + @('/O2', '/Zi', $verifierSource, "/Fe:$verifierExe", "/Fd:$verifierPdb", '/link', '/DEBUG', "/PDB:$verifierPdb", '/INCREMENTAL:NO'))
}
finally {
    Pop-Location
}

$dumpPath = Join-Path $OutputDirectory 'null-read.dmp'
$contextPath = Join-Path $OutputDirectory 'exception-context.bin'
$collectorResultPath = Join-Path $OutputDirectory 'collector-result.json'
$verifierResultPath = Join-Path $OutputDirectory 'verifier-result.json'
$nonce = [Guid]::NewGuid().ToString('N')
$readyEvent = "Local\CrashCapReady_$nonce"
$releaseEvent = "Local\CrashCapRelease_$nonce"

Invoke-Native $collectorExe @(
    '--target', $targetExe,
    '--dump', $dumpPath,
    '--context', $contextPath,
    '--result', $collectorResultPath,
    '--ready-event', $readyEvent,
    '--release-event', $releaseEvent
)

$verifierJson = & $verifierExe '--dump' $dumpPath
if ($LASTEXITCODE -ne 0) {
    [IO.File]::WriteAllText($verifierResultPath, ($verifierJson -join [Environment]::NewLine) + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    throw "MiniDump verifier failed with exit code $LASTEXITCODE"
}
[IO.File]::WriteAllText($verifierResultPath, ($verifierJson -join [Environment]::NewLine) + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
$verification = $verifierJson -join [Environment]::NewLine | ConvertFrom-Json
if (-not $verification.ok) {
    throw 'MiniDump verifier returned ok=false'
}

$metadataPath = Join-Path $OutputDirectory 'pe-metadata.json'
$extractor = Join-Path $sourceDirectory 'extract_pe_metadata.py'
Invoke-Native 'python' @($extractor, '--pe', $targetExe, '--output', $metadataPath)
$metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json

$manifest = [ordered]@{
    schema_version = 'fixture-artifact-manifest-v0.1'
    fixture_id = $fixtureId
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    generator = [ordered]@{
        build_script = 'scripts/fixtures/build_p0_b01.ps1'
        source_root = $repo
        compiler = 'MSVC'
        vcvarsall = $vcvarsPath
        cl_version = "MSVC toolset $vcVersion (cl.exe probe is recorded in docs/evidence/toolchain.json)"
        compiler_flags = @('/std:c++20', '/EHsc', '/MT', '/Od', '/Zi', '/W4', '/DUNICODE', '/D_UNICODE')
        linker_flags = @('/DEBUG', '/INCREMENTAL:NO')
        capture_api = 'MiniDumpWriteDump'
        collector_process = 'mini_dump_collector.exe'
        capture_flags = @('MiniDumpWithDataSegs', 'MiniDumpWithHandleData', 'MiniDumpWithUnloadedModules', 'MiniDumpWithProcessThreadData', 'MiniDumpWithThreadInfo', 'MiniDumpWithIndirectlyReferencedMemory')
        capture_timeout_seconds = 30
    }
    target = [ordered]@{
        path = 'generated/null_read_target.exe'
        pdb = 'generated/null_read_target.pdb'
        architecture = $metadata.architecture
        image_base = $metadata.image_base
        code_id = $metadata.code_id
        debug_id = $metadata.debug_id
        sha256 = $metadata.sha256
        size = $metadata.size
    }
    dump = [ordered]@{
        path = 'generated/null-read.dmp'
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $dumpPath).Hash.ToLowerInvariant()
        size = (Get-Item -LiteralPath $dumpPath).Length
        verifier = 'generated/verifier-result.json'
        exception_code = $verification.exception.code
        exception_address = $verification.exception_address
        fault_module = $verification.fault_module
        crashing_thread_id = $verification.crashing_thread.thread_id
    }
    binaries = [ordered]@{
        collector = 'generated/mini_dump_collector.exe'
        verifier = 'generated/verify_minidump.exe'
    }
}
if ($CrossModule) {
    $faultMetadataPath = Join-Path $OutputDirectory 'fault-pe-metadata.json'
    Invoke-Native 'python' @($extractor, '--pe', $faultDll, '--output', $faultMetadataPath)
    $faultMetadata = Get-Content -LiteralPath $faultMetadataPath -Raw | ConvertFrom-Json
    $manifest['fault_binary'] = [ordered]@{
        path = 'generated/unknown_fault.dll'
        pdb = 'generated/unknown_fault.pdb'
        code_id = $faultMetadata.code_id
        debug_id = $faultMetadata.debug_id
        sha256 = $faultMetadata.sha256
        pdb_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $faultPdb).Hash.ToLowerInvariant()
    }
    $manifest.generator.compiler_flags += '/DCRASHCAP_CROSS_MODULE_FIXTURE'
}
Write-Utf8Json (Join-Path $OutputDirectory 'manifest.json') $manifest

Write-Output ("Generated and verified {0} in {1}" -f $manifest.fixture_id, $OutputDirectory)
Write-Output ("code_id={0} debug_id={1} exception={2} thread={3}" -f $metadata.code_id, $metadata.debug_id, $verification.exception.code, $verification.crashing_thread.thread_id)
