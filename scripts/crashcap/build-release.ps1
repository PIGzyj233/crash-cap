[CmdletBinding()]
param(
    [switch]$SkipWindows,
    [switch]$SkipLinux,
    [string]$AuthenticodeCertificateThumbprint,
    [string]$TimestampServer
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$tools = Join-Path $root "tools/crashcap"
$windowsOutput = Join-Path $tools "windows-x86_64/crashcap.exe"
$linuxOutput = Join-Path $tools "linux-x86_64/crashcap"
$linuxBuilder = "rust:1.96.1-alpine@sha256:a41f7740f8b45d45795624eec13a8b42263cc700f19f7e4e86e04d3dda08a479"
New-Item -ItemType Directory -Force (Split-Path $windowsOutput) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $linuxOutput) | Out-Null

function Find-CodeSigningCertificate([string]$thumbprint) {
    $normalized = $thumbprint.Replace(" ", "").ToUpperInvariant()
    foreach ($store in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
        $candidate = Get-ChildItem $store | Where-Object { $_.Thumbprint -eq $normalized } | Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    throw "Authenticode certificate not found: $normalized"
}

Push-Location $root
try {
    if (-not $SkipWindows) {
        $oldRustFlags = $env:RUSTFLAGS
        try {
            $env:RUSTFLAGS = "-C target-feature=+crt-static -C strip=symbols -C link-arg=/Brepro"
            cargo build --locked --release -p crashcap --target x86_64-pc-windows-msvc
            if ($LASTEXITCODE -ne 0) { throw "Windows crashcap build failed" }
        }
        finally {
            $env:RUSTFLAGS = $oldRustFlags
        }
        Copy-Item -Force "target/x86_64-pc-windows-msvc/release/crashcap.exe" $windowsOutput
    }

    $signatureStatus = "unsigned-pilot"
    $certificateThumbprint = $null
    if (-not [string]::IsNullOrWhiteSpace($AuthenticodeCertificateThumbprint)) {
        if ($SkipWindows) { throw "Authenticode signing cannot be requested with -SkipWindows" }
        $certificate = Find-CodeSigningCertificate $AuthenticodeCertificateThumbprint
        $signatureParameters = @{
            FilePath = $windowsOutput
            Certificate = $certificate
            HashAlgorithm = "SHA256"
        }
        if (-not [string]::IsNullOrWhiteSpace($TimestampServer)) {
            $signatureParameters.TimestampServer = $TimestampServer
        }
        $signature = Set-AuthenticodeSignature @signatureParameters
        if ($signature.Status -ne "Valid") { throw "Authenticode signing failed: $($signature.StatusMessage)" }
        $signatureStatus = "authenticode-signed"
        $certificateThumbprint = $signature.SignerCertificate.Thumbprint.ToLowerInvariant()
    } else {
        $signature = Get-AuthenticodeSignature $windowsOutput
        if ($signature.Status -eq "Valid" -and $signature.SignerCertificate) {
            $signatureStatus = "authenticode-signed"
            $certificateThumbprint = $signature.SignerCertificate.Thumbprint.ToLowerInvariant()
        }
    }

    if (-not $SkipLinux) {
        docker run --rm --mount "type=bind,source=$root,target=/work" --workdir /work $linuxBuilder sh -c "rustup target add x86_64-unknown-linux-musl >/dev/null && CARGO_TARGET_DIR=/work/target/linux-musl RUSTFLAGS='-C strip=symbols -C link-arg=-Wl,--build-id=none' cargo build --locked --release -p crashcap --target x86_64-unknown-linux-musl && cp /work/target/linux-musl/x86_64-unknown-linux-musl/release/crashcap /work/tools/crashcap/linux-x86_64/crashcap && chmod 755 /work/tools/crashcap/linux-x86_64/crashcap"
        if ($LASTEXITCODE -ne 0) { throw "Linux crashcap build failed" }
    }

    if (-not (Test-Path $windowsOutput) -or -not (Test-Path $linuxOutput)) {
        throw "both native delivery artifacts must exist before metadata is generated"
    }
    $windowsHash = (Get-FileHash -Algorithm SHA256 $windowsOutput).Hash.ToLowerInvariant()
    $linuxHash = (Get-FileHash -Algorithm SHA256 $linuxOutput).Hash.ToLowerInvariant()
    $checksumLines = @(
        "$linuxHash  linux-x86_64/crashcap"
        "$windowsHash  windows-x86_64/crashcap.exe"
    )
    [IO.File]::WriteAllText(
        (Join-Path $tools "SHA256SUMS"),
        ($checksumLines -join "`n") + "`n",
        [Text.UTF8Encoding]::new($false)
    )

    $signedWindowsHash = if ($signatureStatus -eq "authenticode-signed") { $windowsHash } else { $null }
    $release = [ordered]@{
        schema_version = "1.0"
        tool = "crashcap"
        version = "1.0.0"
        rustc = "1.96.1"
        linux_builder_image = $linuxBuilder
        signing = [ordered]@{
            status = $signatureStatus
            required_before_general_availability = $true
            windows_signed_sha256 = $signedWindowsHash
            certificate_thumbprint = $certificateThumbprint
        }
        artifacts = @(
            [ordered]@{
                target = "x86_64-unknown-linux-musl"
                path = "linux-x86_64/crashcap"
                sha256 = $linuxHash
                linkage = "static-musl"
                cargo_args = "build --locked --release -p crashcap --target x86_64-unknown-linux-musl"
                rustflags = "-C strip=symbols -C link-arg=-Wl,--build-id=none"
            }
            [ordered]@{
                target = "x86_64-pc-windows-msvc"
                path = "windows-x86_64/crashcap.exe"
                sha256 = $windowsHash
                linkage = "static-crt"
                cargo_args = "build --locked --release -p crashcap --target x86_64-pc-windows-msvc"
                rustflags = "-C target-feature=+crt-static -C strip=symbols -C link-arg=/Brepro"
            }
        )
    }
    [IO.File]::WriteAllText(
        (Join-Path $tools "release.json"),
        ($release | ConvertTo-Json -Depth 5) + "`n",
        [Text.UTF8Encoding]::new($false)
    )
}
finally {
    Pop-Location
}
