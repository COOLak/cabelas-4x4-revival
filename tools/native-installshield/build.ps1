param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'build'))
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'The installed .NET Framework C# compiler is required.' }
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
$arguments = @('/nologo','/target:winexe','/platform:x86','/optimize+','/reference:System.dll','/reference:System.Core.dll','/reference:System.Web.Extensions.dll',('/out:' + (Join-Path $resolvedOutput 'Cabela4x4PatchBackend.exe')),(Join-Path $PSScriptRoot 'PatchBackend.cs'))
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Backend compilation failed.' }
Get-FileHash -LiteralPath (Join-Path $resolvedOutput 'Cabela4x4PatchBackend.exe') -Algorithm SHA256
