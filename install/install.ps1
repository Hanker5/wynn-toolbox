# Wynn Toolbox installer for Windows. In PowerShell:
#
#   irm https://raw.githubusercontent.com/Hanker5/wynn-toolbox/main/install/install.ps1 | iex
#
# Installs into %LOCALAPPDATA%\WynnToolbox, adds "Wynn Toolbox" to the Start
# menu and the Desktop, and a `wynn-toolbox` command. Run it again to update:
# your builds, settings and downloaded game data are kept.
#
# Overrides: WYNN_TOOLBOX_REPO (owner/name), WYNN_TOOLBOX_BRANCH,
# WYNN_TOOLBOX_DIR (install folder), WYNN_TOOLBOX_ZIP (URL or local file).
#
# Runs through `iex`, so it never calls `exit` (that would close the window);
# errors are thrown instead.

& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'      # Invoke-WebRequest is very slow with it

    $Repo = if ($env:WYNN_TOOLBOX_REPO) { $env:WYNN_TOOLBOX_REPO } else { 'Hanker5/wynn-toolbox' }
    $Branch = if ($env:WYNN_TOOLBOX_BRANCH) { $env:WYNN_TOOLBOX_BRANCH } else { 'main' }
    $Dir = if ($env:WYNN_TOOLBOX_DIR) { $env:WYNN_TOOLBOX_DIR } else { Join-Path $env:LOCALAPPDATA 'WynnToolbox' }
    $Zip = if ($env:WYNN_TOOLBOX_ZIP) { $env:WYNN_TOOLBOX_ZIP } else { "https://github.com/$Repo/archive/refs/heads/$Branch.zip" }
    $Bin = Join-Path $env:USERPROFILE '.local\bin'
    $Marker = '.wynn-toolbox-install'

    function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
    function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" } }

    # ------------------------------------------------------------ uv (Python manager)
    $env:Path = "$Bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Say 'Installing uv (it manages Python for Wynn Toolbox)...'
        powershell -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        Check 'Installing uv'
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv did not install; see https://docs.astral.sh/uv/' }

    # ------------------------------------------------------------ the app
    if ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Select-Object -First 1) -and
        -not (Test-Path (Join-Path $Dir $Marker))) {
        throw "$Dir already exists and wasn't made by this installer. Move it, or set WYNN_TOOLBOX_DIR to another folder."
    }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('wynn-toolbox-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        Say 'Downloading Wynn Toolbox...'
        if ($Zip -match '^https?://') { Invoke-WebRequest $Zip -OutFile "$tmp\src.zip" -UseBasicParsing }
        else { Copy-Item $Zip "$tmp\src.zip" }
        Expand-Archive "$tmp\src.zip" -DestinationPath "$tmp\src"
        $src = Get-ChildItem "$tmp\src" -Directory | Select-Object -First 1

        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        # Replace the app's files; keep the player's builds, settings, data and venv.
        Get-ChildItem $Dir -Force |
            Where-Object { $_.Name -notin @('builds', 'data', '.venv', $Marker) } |
            Remove-Item -Recurse -Force
        Copy-Item (Join-Path $src.FullName '*') $Dir -Recurse -Force
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType File -Force -Path (Join-Path $Dir $Marker) | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Dir 'builds') | Out-Null

    Push-Location $Dir
    try {
        Say 'Setting up Python and dependencies (the first time takes a minute)...'
        uv sync --no-dev --frozen --quiet
        Check 'Setting up dependencies'
        Say "Downloading WynnBuilder's item data..."
        & "$Dir\.venv\Scripts\wt.exe" fetch | Out-Null
        Check 'Downloading data'
    } finally {
        Pop-Location
    }

    # ------------------------------------------------------------ launchers
    $wt = Join-Path $Dir '.venv\Scripts\wt.exe'
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    Set-Content -Path (Join-Path $Bin 'wynn-toolbox.cmd') -Encoding ASCII -Value @(
        '@echo off',
        'rem Starts Wynn Toolbox (made by its installer; re-run the installer to update).',
        "cd /d `"$Dir`"",
        "`"$wt`" serve %*"
    )

    $shell = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
        if (-not $folder) { continue }
        $lnk = $shell.CreateShortcut((Join-Path $folder 'Wynn Toolbox.lnk'))
        $lnk.TargetPath = $wt
        $lnk.Arguments = 'serve'
        $lnk.WorkingDirectory = $Dir
        $lnk.Description = 'AI-assisted Wynncraft builds'
        $lnk.Save()
    }

    Write-Host ''
    Say "Done! Wynn Toolbox is installed in $Dir"
    Write-Host '    To start it, open "Wynn Toolbox" from the Start menu or your Desktop.'
    Write-Host '    The first time, it will help you set up an AI assistant.'
    Write-Host '    To update later, run this installer again.'
}
