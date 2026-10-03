param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'build'),
    [string]$WatcomDirectory = $env:WATCOM
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($WatcomDirectory)) { throw 'Specify -WatcomDirectory or the existing WATCOM environment variable.' }
$watcomRoot = [IO.Path]::GetFullPath($WatcomDirectory)
if (-not ('PatchBridgeBuildPaths' -as [type])) {
    Add-Type -TypeDefinition 'using System; using System.Text; using System.Runtime.InteropServices; public static class PatchBridgeBuildPaths { [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern uint GetShortPathName(string path, StringBuilder result, uint count); }'
}
$shortWatcom = New-Object Text.StringBuilder 32768
if ([PatchBridgeBuildPaths]::GetShortPathName($watcomRoot, $shortWatcom, 32768) -eq 0) { throw 'Cannot resolve the compiler path.' }
$watcomRoot = $shortWatcom.ToString()
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
$oldWatcom = $env:WATCOM
$oldInclude = $env:INCLUDE
$oldPath = $env:PATH
$oldWlink = $env:WLINK_LNK
try {
    $env:WATCOM = $watcomRoot
    $env:INCLUDE = (Join-Path $watcomRoot 'h') + ';' + (Join-Path $watcomRoot 'h/nt')
    $env:PATH = (Join-Path $watcomRoot 'binnt') + ';' + $oldPath
    Push-Location -LiteralPath $resolvedOutput
    try {
        [IO.File]::Copy((Join-Path $PSScriptRoot 'PatchBridge.c'), (Join-Path $resolvedOutput 'PatchBridge.c'), $true)
        & (Join-Path $watcomRoot 'binnt/wcc386.exe') '-q' '-bt=nt' '-bd' '-bm' '-ox' '-fo=PatchBridge.obj' 'PatchBridge.c'
        if ($LASTEXITCODE -ne 0) { throw 'Native bridge compilation failed.' }
        # Use an owned initialization file with the compiler's short path.
        [IO.File]::WriteAllText((Join-Path $resolvedOutput 'bridge-empty.lnk'), "# private linker initialization`r`n", [Text.Encoding]::ASCII)
        $env:WLINK_LNK = 'bridge-empty.lnk'
        $directives = @('format windows nt dll','runtime windows=4.0','option quiet','name Cabela4x4PatchBridge.dll','file PatchBridge.obj',("libpath '" + (Join-Path $watcomRoot 'lib386') + "'"),("libpath '" + (Join-Path $watcomRoot 'lib386/nt') + "'"),'library kernel32,user32',"export PatchGame='_PatchGame@12'") -join "`r`n"
        [IO.File]::WriteAllText((Join-Path $resolvedOutput 'bridge-link.lnk'), $directives + "`r`n", [Text.Encoding]::ASCII)
        & (Join-Path $watcomRoot 'binnt/wlink.exe') '@bridge-link.lnk'
        if ($LASTEXITCODE -ne 0) { throw 'Native bridge linking failed.' }
    } finally { Pop-Location }
} finally {
    $env:WATCOM = $oldWatcom
    $env:INCLUDE = $oldInclude
    $env:PATH = $oldPath
    $env:WLINK_LNK = $oldWlink
}
Get-FileHash -LiteralPath (Join-Path $resolvedOutput 'Cabela4x4PatchBridge.dll') -Algorithm SHA256
