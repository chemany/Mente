# ============================================================================
# Mente Agent Installer for Windows
# ============================================================================
# Installation script for Windows (PowerShell).
# Uses uv for fast Python provisioning and package management.
#
# Usage:
#   irm https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.ps1 | iex
#
# Or download and run with options:
#   .\install.ps1 -Release latest -NoVenv -SkipSetup -China
#   .\install.ps1 -Branch main -SourceTarball .\mente-runtime-source.tar.gz
#   .\install.ps1 -OfficialNetwork
#
# ============================================================================

param(
    [switch]$NoVenv,
    [switch]$SkipSetup,
    [switch]$WithNodeDeps,
    [switch]$SshFirst,
    [switch]$China,
    [switch]$OfficialNetwork,
    [string]$Release = "latest",
    [string]$Branch = "main",
    [string]$MenteHome = $(if ($env:MENTE_HOME) { $env:MENTE_HOME } elseif ($env:HERMES_HOME) { $env:HERMES_HOME } else { "$env:LOCALAPPDATA\mente" }),
    [string]$InstallDir = $(if ($env:MENTE_INSTALL_DIR) { $env:MENTE_INSTALL_DIR } else { Join-Path $MenteHome "mente-agent" }),
    [string]$InstallMode = "release",
    [string]$RuntimeArtifactManifest = "",
    [string]$RuntimeWheel = "",
    [string]$SourceTarball = $(if ($env:MENTE_SOURCE_TARBALL) { $env:MENTE_SOURCE_TARBALL } else { "" }),
    [string]$HermesHome = $(if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:MENTE_HOME) { $env:MENTE_HOME } else { "$env:LOCALAPPDATA\mente" })
)

$ErrorActionPreference = "Stop"

# ============================================================================
# Configuration
# ============================================================================

$RepoUrlSsh = "git@github.com:chemany/Mente.git"
$RepoUrlHttps = "https://github.com/chemany/Mente.git"
$UvInstallUrl = if ($env:MENTE_UV_INSTALL_URL) { $env:MENTE_UV_INSTALL_URL } else { "https://astral.sh/uv/install.ps1" }
$NodeDistBaseUrl = if ($env:MENTE_NODE_DIST_BASE_URL) { $env:MENTE_NODE_DIST_BASE_URL } else { "https://nodejs.org/dist" }
$SourceArchiveBaseUrl = if ($env:MENTE_SOURCE_ARCHIVE_BASE_URL) { $env:MENTE_SOURCE_ARCHIVE_BASE_URL } else { "https://codeload.github.com/chemany/Mente/tar.gz" }
$PythonVersion = "3.11"
$NodeVersion = "22"

# ============================================================================
# Helper functions
# ============================================================================

function Write-Banner {
    Write-Host ""
    Write-Host "┌─────────────────────────────────────────────────────────┐" -ForegroundColor Magenta
    Write-Host "│              ⚕ Mente Agent Installer                    │" -ForegroundColor Magenta
    Write-Host "├─────────────────────────────────────────────────────────┤" -ForegroundColor Magenta
    Write-Host "│  An open source AI agent by Nous Research.              │" -ForegroundColor Magenta
    Write-Host "└─────────────────────────────────────────────────────────┘" -ForegroundColor Magenta
    Write-Host ""
}

function Write-Info {
    param([string]$Message)
    Write-Host "→ $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Test-OfficialEndpoint {
    param([string]$Url)

    try {
        Invoke-WebRequest -Uri $Url -Method Head -TimeoutSec 5 -UseBasicParsing | Out-Null
        return $true
    } catch {
        try {
            Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing | Out-Null
            return $true
        } catch {
            return $false
        }
    }
}

function Should-EnableChinaMirrors {
    $probeUrls = @(
        "https://astral.sh/uv/install.ps1",
        "https://registry.npmjs.org/-/ping",
        "https://nodejs.org/dist/latest-v${NodeVersion}.x/"
    )

    foreach ($url in $probeUrls) {
        if (-not (Test-OfficialEndpoint -Url $url)) {
            Write-Warn "Official endpoint probe failed: $url"
            return $true
        }
    }

    return $false
}

function Apply-ChinaNetworkDefaults {
    Write-Info "China mode enabled"

    if (-not $env:PIP_INDEX_URL) {
        $env:PIP_INDEX_URL = if ($env:MENTE_PYPI_INDEX_URL) { $env:MENTE_PYPI_INDEX_URL } else { "https://pypi.tuna.tsinghua.edu.cn/simple" }
    }
    if (-not $env:UV_INDEX_URL) {
        $env:UV_INDEX_URL = if ($env:MENTE_UV_INDEX_URL) { $env:MENTE_UV_INDEX_URL } else { $env:PIP_INDEX_URL }
    }
    if (-not $env:NPM_CONFIG_REGISTRY) {
        $env:NPM_CONFIG_REGISTRY = if ($env:MENTE_NPM_REGISTRY) { $env:MENTE_NPM_REGISTRY } else { "https://registry.npmmirror.com" }
    }
    if (-not $env:PLAYWRIGHT_DOWNLOAD_HOST) {
        $env:PLAYWRIGHT_DOWNLOAD_HOST = if ($env:MENTE_PLAYWRIGHT_DOWNLOAD_HOST) { $env:MENTE_PLAYWRIGHT_DOWNLOAD_HOST } else { "https://npmmirror.com/mirrors/playwright" }
    }
    if (-not $env:MENTE_NODE_DIST_BASE_URL) {
        $script:NodeDistBaseUrl = "https://npmmirror.com/mirrors/node"
    }

    Write-Info "  Python index: $env:PIP_INDEX_URL"
    Write-Info "  npm registry: $env:NPM_CONFIG_REGISTRY"
    Write-Info "  Playwright mirror: $env:PLAYWRIGHT_DOWNLOAD_HOST"
}

function Configure-NetworkDefaults {
    if ($China) {
        Apply-ChinaNetworkDefaults
        return
    }

    if ($OfficialNetwork) {
        Write-Info "Official network mode forced; skipping China mirror auto-detection"
        return
    }

    Write-Info "Auto-detecting whether China mirrors are needed..."
    if (Should-EnableChinaMirrors) {
        Write-Warn "Official network path looks degraded; switching to China mirrors"
        Apply-ChinaNetworkDefaults
    } else {
        Write-Success "Official network path looks healthy"
    }
}

function Can-UseArchiveInstall {
    return $InstallMode -eq "source" -or $Release -ne "latest"
}

function Should-RequireGit {
    if (Test-Path (Join-Path $InstallDir ".git")) {
        return $true
    }
    if ($SourceTarball -and (Test-Path $SourceTarball)) {
        return $false
    }
    return -not (Can-UseArchiveInstall)
}

function Get-InstallerPython {
    try {
        $pythonPath = & $UvCmd python find $PythonVersion 2>$null
        if ($pythonPath) {
            return $pythonPath.Trim()
        }
    } catch { }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return (Get-Command python).Source
    }

    throw "Python interpreter not available for source extraction"
}

function Install-FromSourceTarball {
    param([string]$TarballPath)

    if (-not $TarballPath -or -not (Test-Path $TarballPath)) {
        return $false
    }

    Write-Info "Trying local bundled source..."

    $tmpDir = Join-Path $env:TEMP ("mente-source-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

    try {
        $pythonExe = Get-InstallerPython
        & $pythonExe -c "import pathlib, sys, tarfile; tarfile.open(sys.argv[1], 'r:gz').extractall(pathlib.Path(sys.argv[2]))" $TarballPath $tmpDir
        if ($LASTEXITCODE -ne 0) {
            throw "python extraction failed"
        }

        $extractedDir = Get-ChildItem $tmpDir -Directory | Select-Object -First 1
        if (-not $extractedDir) {
            throw "source tarball did not contain an installable project root"
        }

        if (Test-Path $InstallDir) {
            Remove-Item -Recurse -Force $InstallDir
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null
        Move-Item $extractedDir.FullName $InstallDir -Force
        Write-Success "Loaded local bundled source"
        return $true
    } catch {
        Write-Warn "Failed to extract local bundled source: $_"
        return $false
    } finally {
        Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    }
}

function Download-SourceArchive {
    $archiveUrl = $null

    if ($InstallMode -eq "source") {
        $archiveUrl = "$SourceArchiveBaseUrl/refs/heads/$Branch"
    } elseif ($Release -ne "latest") {
        $archiveUrl = "$SourceArchiveBaseUrl/refs/tags/$Release"
        $script:CurrentReleaseRef = $Release
    } else {
        return $false
    }

    Write-Info "Trying source archive download..."

    $tmpDir = Join-Path $env:TEMP ("mente-source-download-" + [guid]::NewGuid().ToString("N"))
    $archivePath = Join-Path $tmpDir "mente-source.tar.gz"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

    try {
        Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
        $script:SourceTarball = $archivePath
        return Install-FromSourceTarball -TarballPath $script:SourceTarball
    } catch {
        Write-Warn "Source archive download failed: $_"
        return $false
    } finally {
        Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    }
}

# ============================================================================
# Dependency checks
# ============================================================================

function Install-Uv {
    Write-Info "Checking for uv package manager..."
    
    # Check if uv is already available
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $version = uv --version
        $script:UvCmd = "uv"
        Write-Success "uv found ($version)"
        return $true
    }
    
    # Check common install locations
    $uvPaths = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:USERPROFILE\.cargo\bin\uv.exe"
    )
    foreach ($uvPath in $uvPaths) {
        if (Test-Path $uvPath) {
            $script:UvCmd = $uvPath
            $version = & $uvPath --version
            Write-Success "uv found at $uvPath ($version)"
            return $true
        }
    }
    
    # Install uv
    Write-Info "Installing uv (fast Python package manager)..."
    try {
        powershell -ExecutionPolicy ByPass -c "irm $UvInstallUrl | iex" 2>&1 | Out-Null
        
        # Find the installed binary
        $uvExe = "$env:USERPROFILE\.local\bin\uv.exe"
        if (-not (Test-Path $uvExe)) {
            $uvExe = "$env:USERPROFILE\.cargo\bin\uv.exe"
        }
        if (-not (Test-Path $uvExe)) {
            # Refresh PATH and try again
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                $uvExe = (Get-Command uv).Source
            }
        }
        
        if (Test-Path $uvExe) {
            $script:UvCmd = $uvExe
            $version = & $uvExe --version
            Write-Success "uv installed ($version)"
            return $true
        }
        
        Write-Err "uv installed but not found on PATH"
        Write-Info "Try restarting your terminal and re-running"
        return $false
    } catch {
        Write-Err "Failed to install uv"
        Write-Info "Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        return $false
    }
}

function Test-Python {
    Write-Info "Checking Python $PythonVersion..."
    
    # Let uv find or install Python
    try {
        $pythonPath = & $UvCmd python find $PythonVersion 2>$null
        if ($pythonPath) {
            $ver = & $pythonPath --version 2>$null
            Write-Success "Python found: $ver"
            return $true
        }
    } catch { }
    
    # Python not found — use uv to install it (no admin needed!)
    Write-Info "Python $PythonVersion not found, installing via uv..."
    try {
        $uvOutput = & $UvCmd python install $PythonVersion 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonPath = & $UvCmd python find $PythonVersion 2>$null
            if ($pythonPath) {
                $ver = & $pythonPath --version 2>$null
                Write-Success "Python installed: $ver"
                return $true
            }
        } else {
            Write-Warn "uv python install output:"
            Write-Host $uvOutput -ForegroundColor DarkGray
        }
    } catch {
        Write-Warn "uv python install error: $_"
    }

    # Fallback: check if ANY Python 3.10+ is already available on the system
    Write-Info "Trying to find any existing Python 3.10+..."
    foreach ($fallbackVer in @("3.12", "3.13", "3.10")) {
        try {
            $pythonPath = & $UvCmd python find $fallbackVer 2>$null
            if ($pythonPath) {
                $ver = & $pythonPath --version 2>$null
                Write-Success "Found fallback: $ver"
                $script:PythonVersion = $fallbackVer
                return $true
            }
        } catch { }
    }

    # Fallback: try system python
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $sysVer = python --version 2>$null
        if ($sysVer -match "3\.(1[0-9]|[1-9][0-9])") {
            Write-Success "Using system Python: $sysVer"
            return $true
        }
    }
    
    Write-Err "Failed to install Python $PythonVersion"
    Write-Info "Install Python 3.11 manually, then re-run this script:"
    Write-Info "  https://www.python.org/downloads/"
    Write-Info "  Or: winget install Python.Python.3.11"
    return $false
}

function Test-Git {
    Write-Info "Checking Git..."
    
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $version = git --version
        Write-Success "Git found ($version)"
        return $true
    }
    
    Write-Err "Git not found"
    Write-Info "Please install Git from:"
    Write-Info "  https://git-scm.com/download/win"
    return $false
}

function Test-Node {
    Write-Info "Checking Node.js (for browser tools)..."

    if (Get-Command node -ErrorAction SilentlyContinue) {
        $version = node --version
        Write-Success "Node.js $version found"
        $script:HasNode = $true
        return $true
    }

    # Check our own managed install from a previous run
    $managedNode = "$MenteHome\node\node.exe"
    if (Test-Path $managedNode) {
        $version = & $managedNode --version
        $env:Path = "$MenteHome\node;$env:Path"
        Write-Success "Node.js $version found (Mente-managed)"
        $script:HasNode = $true
        return $true
    }

    Write-Info "Node.js not found — installing Node.js $NodeVersion LTS..."

    # Try winget first (cleanest on modern Windows)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Info "Installing via winget..."
        try {
            winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            # Refresh PATH
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command node -ErrorAction SilentlyContinue) {
                $version = node --version
                Write-Success "Node.js $version installed via winget"
                $script:HasNode = $true
                return $true
            }
        } catch { }
    }

    # Fallback: download binary zip to ~/.mente/node/
    Write-Info "Downloading Node.js $NodeVersion binary..."
    try {
        $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
        $indexUrl = "$NodeDistBaseUrl/latest-v${NodeVersion}.x/"
        $indexPage = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing
        $zipName = ($indexPage.Content | Select-String -Pattern "node-v${NodeVersion}\.\d+\.\d+-win-${arch}\.zip" -AllMatches).Matches[0].Value

        if ($zipName) {
            $downloadUrl = "${indexUrl}${zipName}"
            $tmpZip = "$env:TEMP\$zipName"
            $tmpDir = "$env:TEMP\hermes-node-extract"

            Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpZip -UseBasicParsing
            if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
            Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

            $extractedDir = Get-ChildItem $tmpDir -Directory | Select-Object -First 1
            if ($extractedDir) {
                if (Test-Path "$HermesHome\node") { Remove-Item -Recurse -Force "$HermesHome\node" }
                Move-Item $extractedDir.FullName "$HermesHome\node"
                $env:Path = "$HermesHome\node;$env:Path"

                $version = & "$HermesHome\node\node.exe" --version
                Write-Success "Node.js $version installed to ~/.mente/node/"
                $script:HasNode = $true

                Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
                return $true
            }
        }
    } catch {
        Write-Warn "Download failed: $_"
    }

    Write-Warn "Could not auto-install Node.js"
    Write-Info "Install manually: https://nodejs.org/en/download/"
    $script:HasNode = $false
    return $true
}

function Install-SystemPackages {
    $script:HasRipgrep = $false
    $script:HasFfmpeg = $false
    $needRipgrep = $false
    $needFfmpeg = $false

    Write-Info "Checking ripgrep (fast file search)..."
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        $version = rg --version | Select-Object -First 1
        Write-Success "$version found"
        $script:HasRipgrep = $true
    } else {
        $needRipgrep = $true
    }

    Write-Info "Checking ffmpeg (TTS voice messages)..."
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        Write-Success "ffmpeg found"
        $script:HasFfmpeg = $true
    } else {
        $needFfmpeg = $true
    }

    if (-not $needRipgrep -and -not $needFfmpeg) { return }

    # Build description and package lists for each package manager
    $descParts = @()
    $wingetPkgs = @()
    $chocoPkgs = @()
    $scoopPkgs = @()

    if ($needRipgrep) {
        $descParts += "ripgrep for faster file search"
        $wingetPkgs += "BurntSushi.ripgrep.MSVC"
        $chocoPkgs += "ripgrep"
        $scoopPkgs += "ripgrep"
    }
    if ($needFfmpeg) {
        $descParts += "ffmpeg for TTS voice messages"
        $wingetPkgs += "Gyan.FFmpeg"
        $chocoPkgs += "ffmpeg"
        $scoopPkgs += "ffmpeg"
    }

    $description = $descParts -join " and "
    $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
    $hasChoco = Get-Command choco -ErrorAction SilentlyContinue
    $hasScoop = Get-Command scoop -ErrorAction SilentlyContinue

    # Try winget first (most common on modern Windows)
    if ($hasWinget) {
        Write-Info "Installing $description via winget..."
        foreach ($pkg in $wingetPkgs) {
            try {
                winget install $pkg --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            } catch { }
        }
        # Refresh PATH and recheck
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
        if (-not $needRipgrep -and -not $needFfmpeg) { return }
    }

    # Fallback: choco
    if ($hasChoco -and ($needRipgrep -or $needFfmpeg)) {
        Write-Info "Trying Chocolatey..."
        foreach ($pkg in $chocoPkgs) {
            try { choco install $pkg -y 2>&1 | Out-Null } catch { }
        }
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed via chocolatey"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed via chocolatey"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
    }

    # Fallback: scoop
    if ($hasScoop -and ($needRipgrep -or $needFfmpeg)) {
        Write-Info "Trying Scoop..."
        foreach ($pkg in $scoopPkgs) {
            try { scoop install $pkg 2>&1 | Out-Null } catch { }
        }
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed via scoop"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed via scoop"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
    }

    # Show manual instructions for anything still missing
    if ($needRipgrep) {
        Write-Warn "ripgrep not installed (file search will use findstr fallback)"
        Write-Info "  winget install BurntSushi.ripgrep.MSVC"
    }
    if ($needFfmpeg) {
        Write-Warn "ffmpeg not installed (TTS voice messages will be limited)"
        Write-Info "  winget install Gyan.FFmpeg"
    }
}

# ============================================================================
# Installation
# ============================================================================

function Resolve-TargetReleaseRef {
    param([string]$Requested = "latest")
    if ($Requested -ne "latest") { return $Requested }
    $tag = git -c windows.appendAtomically=false tag --sort=-creatordate | Select-Object -First 1
    if (-not $tag) { throw "Could not resolve latest release tag" }
    return $tag.Trim()
}

function Write-InstallManifest {
    $releaseRef = if ($script:CurrentReleaseRef) { $script:CurrentReleaseRef } else { "" }
    $policy = if ($InstallMode -eq "release") { "release_pinned" } else { "source_checkout" }
    $updatePolicy = if ($InstallMode -eq "release") { "git_tag_release" } else { "git_branch_source" }
    $payload = @{
        install_mode = $InstallMode
        release_ref = $releaseRef
        source_branch = $Branch
        runtime_artifact_manifest = $RuntimeArtifactManifest
        runtime_wheel = $RuntimeWheel
        update_policy = $updatePolicy
        runtime_bootstrap_policy = "artifact_manifest_and_runtime_wheel"
        developer_setup_path = "./setup-hermes.sh"
        one_click_install_policy = $policy
    } | ConvertTo-Json -Depth 4
    Set-Content -Path (Join-Path $InstallDir ".mente-install.json") -Value $payload
}

function Install-VendoredRuntime {
    if (-not $RuntimeWheel) {
        if ($RuntimeArtifactManifest) {
            Write-Info "Runtime artifact manifest recorded: $RuntimeArtifactManifest"
        }
        return
    }

    Write-Info "Bootstrapping vendored Codex runtime wheel..."
    Push-Location $InstallDir
    try {
        & $UvCmd pip install $RuntimeWheel 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install runtime wheel"
        }
        Write-Success "Vendored Codex runtime wheel installed"
    } finally {
        Pop-Location
    }
}

function Install-Repository {
    Write-Info "Installing to $InstallDir..."
    
    if (Test-Path $InstallDir) {
        if (Test-Path "$InstallDir\.git") {
            Write-Info "Existing installation found, updating..."
            Push-Location $InstallDir
            if ($InstallMode -eq "release") {
                git -c windows.appendAtomically=false fetch origin --tags
                $script:CurrentReleaseRef = Resolve-TargetReleaseRef $Release
                git -c windows.appendAtomically=false checkout $script:CurrentReleaseRef
            } else {
                git -c windows.appendAtomically=false fetch origin
                git -c windows.appendAtomically=false checkout $Branch
                git -c windows.appendAtomically=false pull origin $Branch
            }
            Pop-Location
        } elseif (Install-FromSourceTarball -TarballPath $SourceTarball) {
            # Local bundle refresh path.
        } elseif (Download-SourceArchive) {
            # Archive refresh path.
        } else {
            Write-Err "Directory exists but is not a git repository: $InstallDir"
            Write-Info "Remove it, use -SourceTarball, or choose a different directory with -InstallDir"
            throw "Directory exists but is not a git repository: $InstallDir"
        }
    } else {
        $cloneSuccess = $false

        if ((Install-FromSourceTarball -TarballPath $SourceTarball) -or (Download-SourceArchive)) {
            $cloneSuccess = $true
        }

        # Fix Windows git "copy-fd: write returned: Invalid argument" error.
        # Git for Windows can fail on atomic file operations (hook templates,
        # config lock files) due to antivirus, OneDrive, or NTFS filter drivers.
        # The -c flag injects config before any file I/O occurs.
        if (-not $cloneSuccess) {
            Write-Info "Configuring git for Windows compatibility..."
            $env:GIT_CONFIG_COUNT = "1"
            $env:GIT_CONFIG_KEY_0 = "windows.appendAtomically"
            $env:GIT_CONFIG_VALUE_0 = "false"
            git config --global windows.appendAtomically false 2>$null
        }

        if (-not $cloneSuccess -and $SshFirst) {
            Write-Info "Trying SSH clone..."
            $env:GIT_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=5"
            try {
                if ($InstallMode -eq "release") {
                    git -c windows.appendAtomically=false clone --recurse-submodules $RepoUrlSsh $InstallDir
                } else {
                    git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlSsh $InstallDir
                }
                if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
            } catch { }
            $env:GIT_SSH_COMMAND = $null
            
            if (-not $cloneSuccess) {
                if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
                Write-Info "SSH failed, trying HTTPS..."
                try {
                    if ($InstallMode -eq "release") {
                        git -c windows.appendAtomically=false clone --recurse-submodules $RepoUrlHttps $InstallDir
                    } else {
                        git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlHttps $InstallDir
                    }
                    if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
                } catch { }
            }
        } elseif (-not $cloneSuccess) {
            Write-Info "Trying HTTPS clone..."
            try {
                if ($InstallMode -eq "release") {
                    git -c windows.appendAtomically=false clone --recurse-submodules $RepoUrlHttps $InstallDir
                } else {
                    git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlHttps $InstallDir
                }
                if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
            } catch { }

            if (-not $cloneSuccess) {
                if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
                Write-Info "HTTPS failed, trying SSH..."
                $env:GIT_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=5"
                try {
                    if ($InstallMode -eq "release") {
                        git -c windows.appendAtomically=false clone --recurse-submodules $RepoUrlSsh $InstallDir
                    } else {
                        git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlSsh $InstallDir
                    }
                    if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
                } catch { }
                $env:GIT_SSH_COMMAND = $null
            }
        }

        # Fallback: download ZIP archive (bypasses git file I/O issues entirely)
        if (-not $cloneSuccess) {
            if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
            Write-Warn "Git clone failed — downloading ZIP archive instead..."
            try {
                $zipUrl = "https://github.com/chemany/Mente/archive/refs/heads/$Branch.zip"
                $zipPath = "$env:TEMP\mente-agent-$Branch.zip"
                $extractPath = "$env:TEMP\mente-agent-extract"
                
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
                if (Test-Path $extractPath) { Remove-Item -Recurse -Force $extractPath }
                Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
                
                # GitHub ZIPs extract to repo-branch/ subdirectory
                $extractedDir = Get-ChildItem $extractPath -Directory | Select-Object -First 1
                if ($extractedDir) {
                    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) -ErrorAction SilentlyContinue | Out-Null
                    Move-Item $extractedDir.FullName $InstallDir -Force
                    Write-Success "Downloaded and extracted"
                    
                    # Initialize git repo so updates work later
                    Push-Location $InstallDir
                    git -c windows.appendAtomically=false init 2>$null
                    git -c windows.appendAtomically=false config windows.appendAtomically false 2>$null
                    git remote add origin $RepoUrlHttps 2>$null
                    Pop-Location
                    Write-Success "Git repo initialized for future updates"
                    
                    $cloneSuccess = $true
                }
                
                # Cleanup temp files
                Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $extractPath -ErrorAction SilentlyContinue
            } catch {
                Write-Err "ZIP download also failed: $_"
            }
        }

        if (-not $cloneSuccess) {
            throw "Failed to download repository (tried git clone SSH, HTTPS, and ZIP)"
        }
    }
    
    # Set per-repo config (harmless if it fails)
    Push-Location $InstallDir
    if (Test-Path ".git") {
        git -c windows.appendAtomically=false config windows.appendAtomically false 2>$null

        # Ensure submodules are initialized and updated
        Write-Info "Initializing submodules..."
        git -c windows.appendAtomically=false submodule update --init --recursive 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Submodule init failed (terminal/RL tools may need manual setup)"
        } else {
            Write-Success "Submodules ready"
        }
        if ($InstallMode -eq "release") {
            $script:CurrentReleaseRef = Resolve-TargetReleaseRef $Release
            git -c windows.appendAtomically=false checkout $script:CurrentReleaseRef 2>$null
        }
    }
    Write-InstallManifest
    Pop-Location
    
    Write-Success "Repository ready"
}

function Install-Venv {
    if ($NoVenv) {
        Write-Info "Skipping virtual environment (-NoVenv)"
        return
    }
    
    Write-Info "Creating virtual environment with Python $PythonVersion..."
    
    Push-Location $InstallDir
    
    if (Test-Path "venv") {
        Write-Info "Virtual environment already exists, recreating..."
        Remove-Item -Recurse -Force "venv"
    }
    
    # uv creates the venv and pins the Python version in one step
    & $UvCmd venv venv --python $PythonVersion
    
    Pop-Location
    
    Write-Success "Virtual environment ready (Python $PythonVersion)"
}

function Install-Dependencies {
    Write-Info "Installing dependencies..."
    
    Push-Location $InstallDir
    
    if (-not $NoVenv) {
        # Tell uv to install into our venv (no activation needed)
        $env:VIRTUAL_ENV = "$InstallDir\venv"
    }
    
    # Install main package with all extras
    try {
        & $UvCmd pip install -e ".[all]" 2>&1 | Out-Null
    } catch {
        & $UvCmd pip install -e "." | Out-Null
    }
    
    Write-Success "Main package installed"
    
    # Install optional submodules
    Write-Info "Installing tinker-atropos (RL training backend)..."
    if (Test-Path "tinker-atropos\pyproject.toml") {
        try {
            & $UvCmd pip install -e ".\tinker-atropos" 2>&1 | Out-Null
            Write-Success "tinker-atropos installed"
        } catch {
            Write-Warn "tinker-atropos install failed (RL tools may not work)"
        }
    } else {
        Write-Warn "tinker-atropos not found (run: git submodule update --init)"
    }
    
    Pop-Location
    
    Write-Success "All dependencies installed"
}

function Set-PathVariable {
    Write-Info "Setting up mente command..."
    
    if ($NoVenv) {
        $menteBin = "$InstallDir"
    } else {
        $menteBin = "$InstallDir\venv\Scripts"
    }
    
    # Add the venv Scripts dir to user PATH so mente is globally available
    # On Windows, the mente.exe in venv\Scripts\ has the venv Python baked in
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    
    if ($currentPath -notlike "*$menteBin*") {
        [Environment]::SetEnvironmentVariable(
            "Path",
            "$menteBin;$currentPath",
            "User"
        )
        Write-Success "Added to user PATH: $menteBin"
    } else {
        Write-Info "PATH already configured"
    }
    
    # Set both MENTE_HOME and HERMES_HOME for rollout compatibility.
    $currentMenteHome = [Environment]::GetEnvironmentVariable("MENTE_HOME", "User")
    if (-not $currentMenteHome -or $currentMenteHome -ne $MenteHome) {
        [Environment]::SetEnvironmentVariable("MENTE_HOME", $MenteHome, "User")
        Write-Success "Set MENTE_HOME=$MenteHome"
    }
    $currentHermesHome = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
    if (-not $currentHermesHome -or $currentHermesHome -ne $MenteHome) {
        [Environment]::SetEnvironmentVariable("HERMES_HOME", $MenteHome, "User")
        Write-Success "Set HERMES_HOME=$MenteHome"
    }
    $env:MENTE_HOME = $MenteHome
    $env:HERMES_HOME = $MenteHome
    
    # Update current session
    $env:Path = "$menteBin;$env:Path"
    
    Write-Success "mente command ready"
}

function Copy-ConfigTemplates {
    Write-Info "Setting up configuration files..."
    
    # Create ~/.mente directory structure
    New-Item -ItemType Directory -Force -Path "$MenteHome\cron" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\sessions" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\logs" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\pairing" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\hooks" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\image_cache" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\audio_cache" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\memories" | Out-Null
    New-Item -ItemType Directory -Force -Path "$MenteHome\skills" | Out-Null

    
    # Create .env
    $envPath = "$MenteHome\.env"
    if (-not (Test-Path $envPath)) {
        $examplePath = "$InstallDir\.env.example"
        if (Test-Path $examplePath) {
            Copy-Item $examplePath $envPath
            Write-Success "Created ~/.mente/.env from template"
        } else {
            New-Item -ItemType File -Force -Path $envPath | Out-Null
            Write-Success "Created ~/.mente/.env"
        }
    } else {
        Write-Info "~/.mente/.env already exists, keeping it"
    }
    
    # Create config.yaml
    $configPath = "$MenteHome\config.yaml"
    if (-not (Test-Path $configPath)) {
        $examplePath = "$InstallDir\cli-config.yaml.example"
        if (Test-Path $examplePath) {
            Copy-Item $examplePath $configPath
            Write-Success "Created ~/.mente/config.yaml from template"
        }
    } else {
        Write-Info "~/.mente/config.yaml already exists, keeping it"
    }
    
    # Create SOUL.md if it doesn't exist (global persona file)
    $soulPath = "$MenteHome\SOUL.md"
    if (-not (Test-Path $soulPath)) {
        @"
# Mente Agent Persona

<!-- 
This file defines the agent's personality and tone.
The agent will embody whatever you write here.
Edit this to customize how Mente communicates with you.

Examples:
  - "You are a warm, playful assistant who uses kaomoji occasionally."
  - "You are a concise technical expert. No fluff, just facts."
  - "You speak like a friendly coworker who happens to know everything."

This file is loaded fresh each message -- no restart needed.
Delete the contents (or this file) to use the default personality.
-->
"@ | Set-Content -Path $soulPath -Encoding UTF8
        Write-Success "Created ~/.mente/SOUL.md (edit to customize personality)"
    }
    
    Write-Success "Configuration directory ready: ~/.mente/"
    
    # Seed bundled skills into ~/.mente/skills/ (manifest-based, one-time per skill)
    Write-Info "Syncing bundled skills to ~/.mente/skills/ ..."
    $pythonExe = "$InstallDir\venv\Scripts\python.exe"
    if (Test-Path $pythonExe) {
        try {
            & $pythonExe "$InstallDir\tools\skills_sync.py" 2>$null
            Write-Success "Skills synced to ~/.mente/skills/"
        } catch {
            # Fallback: simple directory copy
            $bundledSkills = "$InstallDir\skills"
            $userSkills = "$MenteHome\skills"
            if ((Test-Path $bundledSkills) -and -not (Get-ChildItem $userSkills -Exclude '.bundled_manifest' -ErrorAction SilentlyContinue)) {
                Copy-Item -Path "$bundledSkills\*" -Destination $userSkills -Recurse -Force -ErrorAction SilentlyContinue
                Write-Success "Skills copied to ~/.mente/skills/"
            }
        }
    }
}

function Install-NodeDeps {
    if (-not $HasNode) {
        Write-Info "Skipping Node.js dependencies (Node not installed)"
        return
    }

    if (-not $WithNodeDeps) {
        Write-Info "Skipping Node.js/browser dependency install during bootstrap"
        Write-Info "TUI dependencies install automatically on first 'mente --tui' run."
        Write-Info "Browser tools install on demand; use -WithNodeDeps if you want them preinstalled."
        return
    }
    
    Push-Location $InstallDir
    
    if (Test-Path "package.json") {
        Write-Info "Installing Node.js dependencies (browser tools)..."
        try {
            npm install --silent 2>&1 | Out-Null
            Write-Success "Node.js dependencies installed"
        } catch {
            Write-Warn "npm install failed (browser tools may not work)"
        }
    }
    
    # Install TUI dependencies
    $tuiDir = "$InstallDir\ui-tui"
    if (Test-Path "$tuiDir\package.json") {
        Write-Info "Installing TUI dependencies..."
        Push-Location $tuiDir
        try {
            npm install --silent 2>&1 | Out-Null
            Write-Success "TUI dependencies installed"
        } catch {
            Write-Warn "TUI npm install failed (mente --tui may not work)"
        }
        Pop-Location
    }


    
    Pop-Location
}

function Invoke-SetupWizard {
    if ($SkipSetup) {
        Write-Info "Skipping setup wizard (-SkipSetup)"
        return
    }
    
    Write-Host ""
    Write-Info "Starting setup wizard..."
    Write-Host ""
    
    Push-Location $InstallDir
    
    # Run mente setup using the venv Python directly (no activation needed)
    $env:MENTE_SETUP_SKIP_AUTO_CHAT = "1"
    $env:HERMES_SETUP_SKIP_AUTO_CHAT = "1"
    try {
        if (-not $NoVenv) {
            & ".\venv\Scripts\python.exe" -m hermes_cli.main setup
        } else {
            python -m hermes_cli.main setup
        }
    } finally {
        Remove-Item Env:MENTE_SETUP_SKIP_AUTO_CHAT -ErrorAction SilentlyContinue
        Remove-Item Env:HERMES_SETUP_SKIP_AUTO_CHAT -ErrorAction SilentlyContinue
    }
    
    Pop-Location
}

function Start-GatewayIfConfigured {
    $envPath = "$MenteHome\.env"
    if (-not (Test-Path $envPath)) { return }

    $hasMessaging = $false
    $content = Get-Content $envPath -ErrorAction SilentlyContinue
    foreach ($var in @("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "WHATSAPP_ENABLED")) {
        $match = $content | Where-Object { $_ -match "^${var}=.+" -and $_ -notmatch "your-token-here" }
        if ($match) { $hasMessaging = $true; break }
    }

    if (-not $hasMessaging) { return }

    $menteCmd = "$InstallDir\venv\Scripts\mente.exe"
    if (-not (Test-Path $menteCmd)) {
        $menteCmd = "mente"
    }

    # If WhatsApp is enabled but not yet paired, run foreground for QR scan
    $whatsappEnabled = $content | Where-Object { $_ -match "^WHATSAPP_ENABLED=true" }
    $whatsappSession = "$MenteHome\whatsapp\session\creds.json"
    if ($whatsappEnabled -and -not (Test-Path $whatsappSession)) {
        Write-Host ""
        Write-Info "WhatsApp is enabled but not yet paired."
        Write-Info "Running 'mente whatsapp' to pair via QR code..."
        Write-Host ""
        $response = Read-Host "Pair WhatsApp now? [Y/n]"
        if ($response -eq "" -or $response -match "^[Yy]") {
            try {
                & $menteCmd whatsapp
            } catch {
                # Expected after pairing completes
            }
        }
    }

    Write-Host ""
    Write-Info "Messaging platform token detected!"
    Write-Info "The gateway handles messaging platforms and cron job execution."
    Write-Host ""
    $response = Read-Host "Would you like to start the gateway now? [Y/n]"

    if ($response -eq "" -or $response -match "^[Yy]") {
        Write-Info "Starting gateway in background..."
        try {
            $logFile = "$MenteHome\logs\gateway.log"
            Start-Process -FilePath $menteCmd -ArgumentList "gateway" `
                -RedirectStandardOutput $logFile `
                -RedirectStandardError "$MenteHome\logs\gateway-error.log" `
                -WindowStyle Hidden
            Write-Success "Gateway started! Your bot is now online."
            Write-Info "Logs: $logFile"
            Write-Info "To stop: close the gateway process from Task Manager"
        } catch {
            Write-Warn "Failed to start gateway. Run manually: mente gateway"
        }
    } else {
        Write-Info "Skipped. Start the gateway later with: mente gateway"
    }
}

function Write-Completion {
    Write-Host ""
    Write-Host "┌─────────────────────────────────────────────────────────┐" -ForegroundColor Green
    Write-Host "│              ✓ Installation Complete!                   │" -ForegroundColor Green
    Write-Host "└─────────────────────────────────────────────────────────┘" -ForegroundColor Green
    Write-Host ""
    
    # Show file locations
    Write-Host "📁 Your files:" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   Config:    " -NoNewline -ForegroundColor Yellow
    Write-Host "$MenteHome\config.yaml"
    Write-Host "   API Keys:  " -NoNewline -ForegroundColor Yellow
    Write-Host "$MenteHome\.env"
    Write-Host "   Data:      " -NoNewline -ForegroundColor Yellow
    Write-Host "$MenteHome\cron\, sessions\, logs\"
    Write-Host "   Code:      " -NoNewline -ForegroundColor Yellow
    Write-Host "$InstallDir\"
    Write-Host ""
    
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "🚀 Commands:" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   mente               " -NoNewline -ForegroundColor Green
    Write-Host "Start chatting"
    Write-Host "   mente setup         " -NoNewline -ForegroundColor Green
    Write-Host "Configure API keys & settings"
    Write-Host "   mente config        " -NoNewline -ForegroundColor Green
    Write-Host "View/edit configuration"
    Write-Host "   mente config edit   " -NoNewline -ForegroundColor Green
    Write-Host "Open config in editor"
    Write-Host "   mente gateway       " -NoNewline -ForegroundColor Green
    Write-Host "Start messaging gateway (Telegram, Discord, etc.)"
    Write-Host "   mente update        " -NoNewline -ForegroundColor Green
    Write-Host "Update to latest version"
    Write-Host ""
    
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "⚡ Restart your terminal for PATH changes to take effect" -ForegroundColor Yellow
    Write-Host ""
    
    if (-not $HasNode) {
        Write-Host "Note: Node.js could not be installed automatically." -ForegroundColor Yellow
        Write-Host "Browser tools need Node.js. Install manually:" -ForegroundColor Yellow
        Write-Host "  https://nodejs.org/en/download/" -ForegroundColor Yellow
        Write-Host ""
    }
    
    if (-not $HasRipgrep) {
        Write-Host "Note: ripgrep (rg) was not installed. For faster file search:" -ForegroundColor Yellow
        Write-Host "  winget install BurntSushi.ripgrep.MSVC" -ForegroundColor Yellow
        Write-Host ""
    }
}

# ============================================================================
# Main
# ============================================================================

function Main {
    Write-Banner
    
    Configure-NetworkDefaults
    if (-not (Install-Uv)) { throw "uv installation failed — cannot continue" }
    if (-not (Test-Python)) { throw "Python $PythonVersion not available — cannot continue" }
    if (Should-RequireGit) {
        if (-not (Test-Git)) { throw "Git not found — install from https://git-scm.com/download/win" }
    } else {
        Write-Info "Skipping Git check (local source bundle/archive path available)"
    }
    Test-Node              # Auto-installs if missing
    Install-SystemPackages  # ripgrep + ffmpeg in one step
    
    Install-Repository
    Install-Venv
    Install-Dependencies
    Install-VendoredRuntime
    Install-NodeDeps
    Set-PathVariable
    Copy-ConfigTemplates
    Invoke-SetupWizard
    Start-GatewayIfConfigured
    
    Write-Completion
}

# Wrap in try/catch so errors don't kill the terminal when run via:
#   irm https://...install.ps1 | iex
# (exit/throw inside iex kills the entire PowerShell session)
try {
    Main
} catch {
    Write-Host ""
    Write-Err "Installation failed: $_"
    Write-Host ""
    Write-Info "If the error is unclear, try downloading and running the script directly:"
    Write-Host "  Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/chemany/Mente/main/scripts/install.ps1' -OutFile install.ps1" -ForegroundColor Yellow
    Write-Host "  .\install.ps1" -ForegroundColor Yellow
    Write-Host ""
}
