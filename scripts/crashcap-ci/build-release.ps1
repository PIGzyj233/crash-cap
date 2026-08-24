[CmdletBinding()]
param(
    [switch]$SkipWindows,
    [switch]$SkipLinux
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$tools = Join-Path $root "tools/crashcap-ci"
$windowsOutput = Join-Path $tools "windows-x86_64/crashcap-ci.exe"
$linuxOutput = Join-Path $tools "linux-x86_64/crashcap-ci"
$linuxBuilder = "rust:1.96.1-alpine@sha256:a41f7740f8b45d45795624eec13a8b42263cc700f19f7e4e86e04d3dda08a479"
New-Item -ItemType Directory -Force (Split-Path $windowsOutput) | Out-Null
New-Item -ItemType Directory -Force (Split-Path $linuxOutput) | Out-Null

Push-Location $root
try {
    if (-not $SkipWindows) {
        $oldRustFlags = $env:RUSTFLAGS
        try {
            $env:RUSTFLAGS = "-C target-feature=+crt-static -C strip=symbols -C link-arg=/Brepro"
            cargo build --locked --release -p crashcap-ci --target x86_64-pc-windows-msvc
            if ($LASTEXITCODE -ne 0) { throw "Windows crashcap-ci build failed" }
        }
        finally {
            $env:RUSTFLAGS = $oldRustFlags
        }
        Copy-Item -Force "target/x86_64-pc-windows-msvc/release/crashcap-ci.exe" $windowsOutput
    }

    if (-not $SkipLinux) {
        docker run --rm --mount "type=bind,source=$root,target=/work" --workdir /work $linuxBuilder sh -c "rustup target add x86_64-unknown-linux-musl >/dev/null && CARGO_TARGET_DIR=/work/target/linux-musl RUSTFLAGS='-C strip=symbols -C link-arg=-Wl,--build-id=none' cargo build --locked --release -p crashcap-ci --target x86_64-unknown-linux-musl && cp /work/target/linux-musl/x86_64-unknown-linux-musl/release/crashcap-ci /work/tools/crashcap-ci/linux-x86_64/crashcap-ci && chmod 755 /work/tools/crashcap-ci/linux-x86_64/crashcap-ci"
        if ($LASTEXITCODE -ne 0) { throw "Linux crashcap-ci build failed" }
    }

    if (-not (Test-Path $windowsOutput) -or -not (Test-Path $linuxOutput)) {
        throw "both native delivery artifacts must exist before metadata is generated"
    }
    $windowsHash = (Get-FileHash -Algorithm SHA256 $windowsOutput).Hash.ToLowerInvariant()
    $linuxHash = (Get-FileHash -Algorithm SHA256 $linuxOutput).Hash.ToLowerInvariant()
    $checksumLines = @(
        "$linuxHash  linux-x86_64/crashcap-ci"
        "$windowsHash  windows-x86_64/crashcap-ci.exe"
    )
    [IO.File]::WriteAllText(
        (Join-Path $tools "SHA256SUMS"),
        ($checksumLines -join "`n") + "`n",
        [Text.UTF8Encoding]::new($false)
    )

    $release = [ordered]@{
        schema_version = "1.0"
        tool = "crashcap-ci"
        version = "1.0.0"
        rustc = "1.96.1"
        linux_builder_image = $linuxBuilder
        artifacts = @(
            [ordered]@{
                target = "x86_64-unknown-linux-musl"
                path = "linux-x86_64/crashcap-ci"
                sha256 = $linuxHash
                linkage = "static-musl"
                cargo_args = "build --locked --release -p crashcap-ci --target x86_64-unknown-linux-musl"
                rustflags = "-C strip=symbols -C link-arg=-Wl,--build-id=none"
            }
            [ordered]@{
                target = "x86_64-pc-windows-msvc"
                path = "windows-x86_64/crashcap-ci.exe"
                sha256 = $windowsHash
                linkage = "static-crt"
                cargo_args = "build --locked --release -p crashcap-ci --target x86_64-pc-windows-msvc"
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
