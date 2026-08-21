[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Continue'

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding($false)))
}

function Invoke-Captured([string]$FilePath, [string[]]$Arguments) {
    $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    [pscustomobject]@{
        exit_code = $LASTEXITCODE
        output = ($output -join [Environment]::NewLine)
    }
}

function Find-Path([string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Find-VcVars {
    $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    return Find-Path @(
        (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat'),
        (Join-Path $programFilesX86 'Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat')
    )
}

function Import-VcEnvironment([string]$VcVarsPath) {
    if (-not $VcVarsPath) {
        return $false
    }
    $command = 'call "{0}" x64 >nul && set' -f $VcVarsPath
    $lines = & cmd.exe /d /s /c $command
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    foreach ($line in $lines) {
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2 -and $parts[0] -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            Set-Item -Path ("Env:" + $parts[0]) -Value $parts[1]
        }
    }
    return [bool](Get-Command cl.exe -ErrorAction SilentlyContinue)
}

function Add-CommandEvidence([System.Collections.Generic.List[object]]$List,
                             [string]$Name, [string]$Command,
                             [string[]]$Arguments, [bool]$Required,
                             [string]$Notes = '') {
    $commandInfo = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $commandInfo) {
        $List.Add([pscustomobject]@{
                name = $Name
                status = 'missing'
                required_for_phase0 = $Required
                command = $Command
                arguments = $Arguments
                path = $null
                version = $null
                exit_code = $null
                raw_output = ''
                notes = $Notes
            })
        return
    }
    $captured = Invoke-Captured $commandInfo.Source $Arguments
    # Some probes intentionally return non-zero (for example `cl /Bv` also
    # complains that no source file was supplied). Presence and launchability
    # are availability; preserve the probe exit code below.
    $status = 'available'
    $List.Add([pscustomobject]@{
            name = $Name
            status = $status
            required_for_phase0 = $Required
            command = $Command
            arguments = $Arguments
            path = $commandInfo.Source
            version = ($captured.output -split [Environment]::NewLine | Select-Object -First 3) -join [Environment]::NewLine
            exit_code = $captured.exit_code
            probe_status = if ($captured.exit_code -eq 0) { 'ok' } else { 'nonzero' }
            raw_output = $captured.output
            notes = $Notes
        })
}

function Add-PathEvidence([System.Collections.Generic.List[object]]$List,
                          [string]$Name, [string]$Path, [bool]$Required,
                          [string]$Version = '', [string]$Notes = '') {
    $resolved = if ($Path -and (Test-Path -LiteralPath $Path)) { (Resolve-Path -LiteralPath $Path).Path } else { $null }
    $List.Add([pscustomobject]@{
            name = $Name
            status = if ($resolved) { 'available' } else { 'missing' }
            required_for_phase0 = $Required
            command = $null
            arguments = @()
            path = $resolved
            version = $Version
            exit_code = $null
            probe_status = 'not_run'
            raw_output = ''
            notes = $Notes
        })
}

$repo = Get-RepositoryRoot
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repo 'docs\evidence'
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$portableCdb = Join-Path $repo 'scripts\symbolicator\.tools\windbg\x64-package\unpacked\amd64\cdb.exe'
$portableWinDbg = Join-Path $repo 'scripts\symbolicator\.tools\windbg\x64-package\unpacked\DbgX.Shell.exe'
$portableSymsorter = Join-Path $repo 'scripts\symbolicator\.tools\symsorter\26.7.2\symsorter-Windows-x86_64.exe'

$evidence = New-Object 'System.Collections.Generic.List[object]'
$vcvars = Find-VcVars
$vcImported = Import-VcEnvironment $vcvars
$vcVersion = ''
$vcToolsRoot = $null
if ($vcvars) {
    $vcToolsRoot = Split-Path (Split-Path (Split-Path (Split-Path $vcvars -Parent) -Parent) -Parent) -Parent
    $versionFile = Join-Path $vcToolsRoot 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt'
    if (Test-Path -LiteralPath $versionFile) {
        $vcVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    }
}

Add-CommandEvidence $evidence 'Rust compiler' 'rustc' @('--version', '--verbose') $true 'Core build and test toolchain.'
Add-CommandEvidence $evidence 'Cargo' 'cargo' @('--version') $true 'Core build and test toolchain.'
Add-CommandEvidence $evidence 'Docker CLI' 'docker' @('--version') $true 'Compose experiments and OCI verification.'
Add-CommandEvidence $evidence 'Docker Compose plugin' 'docker' @('compose', 'version') $true 'Preferred Compose command.'
Add-CommandEvidence $evidence 'docker-compose compatibility CLI' 'docker-compose' @('version') $false 'Compatibility command; Compose v2 plugin is preferred.'
Add-CommandEvidence $evidence 'CMake' 'cmake' @('--version') $false 'Not a Phase 0 product dependency, recorded because MSVC projects may use it.'
Add-CommandEvidence $evidence 'MSVC compiler' 'cl.exe' @('/Bv') $true 'x64 generator uses the environment imported from vcvarsall.'
Add-CommandEvidence $evidence 'MSVC linker' 'link.exe' @('/VERSION') $true 'Needed to produce x64 PE/PDB artifacts.'
Add-CommandEvidence $evidence 'MSVC dumpbin' 'dumpbin.exe' @('/?') $false 'Useful for manual PE/PDB inspection.'
Add-CommandEvidence $evidence 'CDB' $portableCdb @('-version') $false 'Portable CDB extracted from the hash-verified official Microsoft.WinDbg package.'
Add-PathEvidence $evidence 'WinDbg' $portableWinDbg $false '1.2606.22001.0' 'Portable official WinDbg package; path-only probe avoids launching the graphical shell.'
Add-CommandEvidence $evidence 'Symbolicator CLI' 'symbolicator' @('--version') $false 'Phase 0 runtime is normally containerized; local CLI is optional.'
Add-CommandEvidence $evidence 'symsorter' $portableSymsorter @('--version') $false 'Pinned Symbolicator 26.7.2 symsorter used for the Unified fixture.'
Add-CommandEvidence $evidence 'RustFS CLI' 'rustfs' @('--version') $false 'RustFS is normally run as a container; local CLI is optional.'

$sdkRoot = Join-Path ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)')) 'Windows Kits\10'
$sdkVersions = @()
$sdkInclude = Join-Path $sdkRoot 'Include'
if (Test-Path -LiteralPath $sdkInclude) {
    $sdkVersions = @(Get-ChildItem -LiteralPath $sdkInclude -Directory | Select-Object -ExpandProperty Name | Sort-Object)
}
$dbghelp = Find-Path @(
    (Join-Path $sdkRoot 'Debuggers\x64\dbghelp.dll'),
    (Join-Path $sdkRoot 'App Certification Kit\DbgHelp.dll')
)
Add-PathEvidence $evidence 'Windows SDK' $sdkRoot $true (($sdkVersions -join ', ')) 'Headers/libraries provide MiniDumpWriteDump and MiniDumpReadDumpStream.'
Add-PathEvidence $evidence 'Windows SDK DbgHelp.dll' $dbghelp $true '' 'The fixture collector links DbgHelp.lib and executes against the SDK/runtime DbgHelp implementation.'
Add-PathEvidence $evidence 'VS vcvarsall x64' $vcvars $true $vcVersion 'Loads MSVC, linker, SDK include/lib and PATH for the generator.'

$dockerVersion = $null
$dockerInfo = $null
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $versionCapture = Invoke-Captured $dockerCommand.Source @('version', '--format', '{{json .}}')
    $dockerVersion = [pscustomobject]@{ exit_code = $versionCapture.exit_code; raw_output = $versionCapture.output }
    $infoCapture = Invoke-Captured $dockerCommand.Source @('info', '--format', '{{json .}}')
    if ($infoCapture.exit_code -eq 0) {
        try {
            $info = $infoCapture.output | ConvertFrom-Json
            $dockerInfo = [pscustomobject]@{
                exit_code = $infoCapture.exit_code
                server_version = $info.ServerVersion
                operating_system = $info.OperatingSystem
                os_type = $info.OSType
                architecture = $info.Architecture
                containers = $info.Containers
                containers_running = $info.ContainersRunning
                images = $info.Images
                name = $info.Name
                kernel_version = $info.KernelVersion
                cgroup_version = $info.CgroupVersion
            }
        }
        catch {
            $dockerInfo = [pscustomobject]@{ exit_code = $infoCapture.exit_code; parse_error = $_.Exception.Message }
        }
    }
    else {
        $dockerInfo = [pscustomobject]@{ exit_code = $infoCapture.exit_code; error = $infoCapture.output }
    }
}

function Get-ImageEvidence([string]$Reference, [string]$Name) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        return [pscustomobject]@{ name = $Name; reference = $Reference; status = 'docker_missing'; image_id = $null; repo_digests = @(); labels = @{} }
    }
    $capture = Invoke-Captured $docker.Source @('image', 'inspect', $Reference, '--format', '{{json .}}')
    if ($capture.exit_code -ne 0) {
        return [pscustomobject]@{ name = $Name; reference = $Reference; status = 'missing'; image_id = $null; repo_digests = @(); labels = @{}; raw_output = $capture.output }
    }
    try {
        $image = $capture.output | ConvertFrom-Json
        $labels = @{}
        if ($image.Config.Labels) { $labels = $image.Config.Labels }
        return [pscustomobject]@{
            name = $Name
            reference = $Reference
            status = 'available'
            image_id = $image.Id
            repo_digests = @($image.RepoDigests)
            labels = $labels
            created = $image.Created
            architecture = $image.Architecture
            os = $image.Os
        }
    }
    catch {
        return [pscustomobject]@{ name = $Name; reference = $Reference; status = 'error'; image_id = $null; repo_digests = @(); labels = @{}; raw_output = $capture.output; error = $_.Exception.Message }
    }
}

$images = @(
    (Get-ImageEvidence 'ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831' 'RustFS qualified image'),
    (Get-ImageEvidence 'ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959' 'Symbolicator pinned image'),
    (Get-ImageEvidence 'crash-cap/dmp-core:p0-a04' 'Core local OCI image')
)

$record = [ordered]@{
    schema_version = 'toolchain-evidence-v0.1'
    checked_at_utc = [DateTime]::UtcNow.ToString('o')
    repository = $repo
    host = [ordered]@{
        os = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption
        os_version = [Environment]::OSVersion.Version.ToString()
        architecture = $env:PROCESSOR_ARCHITECTURE
        powershell = $PSVersionTable.PSVersion.ToString()
    }
    tools = $evidence.ToArray()
    docker = [ordered]@{
        version = $dockerVersion
        info = $dockerInfo
        images = $images
    }
    conclusions = [ordered]@{
        base06 = 'recorded'
        msvc_x64_generator = if ($vcImported) { 'available' } else { 'blocked_vcvars_or_cl' }
        cdb_windbg_reference = if (@($evidence | Where-Object { $_.name -in @('CDB', 'WinDbg') -and $_.status -eq 'available' }).Count -gt 0) { 'available' } else { 'not_available' }
        symbolicator = if (@($images | Where-Object { $_.name -eq 'Symbolicator pinned image' -and $_.status -eq 'available' }).Count -gt 0) { 'pinned_image_available' } else { 'pinned_image_not_available' }
        rustfs = if (@($images | Where-Object { $_.name -eq 'RustFS qualified image' -and $_.status -eq 'available' }).Count -gt 0) { 'qualified_image_available' } else { 'qualified_image_not_available' }
    }
}

$jsonPath = Join-Path $OutputDirectory 'toolchain.json'
$markdownPath = Join-Path $OutputDirectory 'toolchain.md'
$json = $record | ConvertTo-Json -Depth 12
Write-Utf8NoBom $jsonPath ($json + [Environment]::NewLine)

$lines = New-Object 'System.Collections.Generic.List[string]'
$lines.Add('# Phase 0 toolchain evidence')
$lines.Add('')
$lines.Add(('Checked (UTC): `{0}`' -f $record.checked_at_utc))
$lines.Add('')
$lines.Add('This is a point-in-time, read-only inventory. `available` means the command or local image was observed; it does not prove a complete Phase 0 analysis path.')
$lines.Add('')
$lines.Add('| Component | Status | Version / identity | Path or reference |')
$lines.Add('| --- | --- | --- | --- |')
foreach ($tool in $evidence) {
    $version = ($tool.version -replace '\r?\n', '<br>')
    $path = if ($tool.path) { $tool.path } else { $tool.command }
    $lines.Add(('| {0} | `{1}` | {2} | `{3}` |' -f $tool.name, $tool.status, $version, $path))
}
foreach ($image in $images) {
    $versionLabel = if ($image.labels -and $image.labels.version) { "version=$($image.labels.version)" } else { '' }
    $digestLabel = if ($image.repo_digests.Count -gt 0) { $image.repo_digests -join '<br>' } elseif ($image.image_id) { $image.image_id } else { '' }
    $identity = (@($versionLabel, $digestLabel) | Where-Object { $_ }) -join '<br>'
    $lines.Add(('| {0} | `{1}` | {2} | `{3}` |' -f $image.name, $image.status, $identity, $image.reference))
}
$lines.Add('')
$lines.Add('## Re-run')
$lines.Add('')
$lines.Add('```text')
$lines.Add('powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/env/check-toolchain.ps1')
$lines.Add('```')
$lines.Add('')
$lines.Add('## Evidence boundary')
$lines.Add('')
$lines.Add('- Rust, Cargo, Docker/Compose, MSVC/SDK, CMake, CDB/WinDbg, Symbolicator and RustFS status is recorded in `toolchain.json`.')
$lines.Add('- The RustFS digest is only a local-image identity until the S3 qualification tests pin and approve it.')
$lines.Add('- Missing CDB/WinDbg means the fixture reference transcript remains an expectation, not a debugger-backed result.')
$lines.Add('- Missing Symbolicator is an environment blocker for the SYM lane; this inventory does not install or pull it. CMake is available through the VS installation but is not required by the current fixture generator.')
Write-Utf8NoBom $markdownPath (($lines -join [Environment]::NewLine) + [Environment]::NewLine)

Write-Output $jsonPath
Write-Output $markdownPath
