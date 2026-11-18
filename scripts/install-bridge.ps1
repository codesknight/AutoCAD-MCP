param(
    [Parameter(Mandatory=$true)][string]$AutoCADDir,
    [string]$DotnetPath = (Join-Path $env:USERPROFILE '.dotnet/dotnet.exe')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $DotnetPath)) { $DotnetPath = (Get-Command dotnet).Source }
$projectRoot = Split-Path $PSScriptRoot -Parent
$projectFile = Join-Path $projectRoot 'plugin/AutoCADBridge/AutoCADBridge.csproj'
& $DotnetPath build $projectFile -c Release "-p:AutoCADDir=$AutoCADDir" --nologo -v quiet
if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed' }
$bundlePath = Join-Path $env:APPDATA 'Autodesk/ApplicationPlugins/AutoCADMCPBridge.bundle'
$existingManifest = Join-Path $bundlePath 'PackageContents.xml'
if (Test-Path -LiteralPath $existingManifest) {
    $existingPackage = [xml](Get-Content -LiteralPath $existingManifest -Raw)
    if ($existingPackage.ApplicationPackage.ProductCode -ne '{F19F5DBA-39A5-4887-B3ED-458EF4C2D401}') {
        throw 'Existing bundle does not belong to AutoCAD-MCP; refusing to overwrite it'
    }
}
$contentsPath = Join-Path $bundlePath 'Contents/Windows'
New-Item -ItemType Directory -Force -Path $contentsPath | Out-Null
foreach ($artifact in @('AutoCADBridge.dll','AutoCADBridge.deps.json','AutoCADBridge.runtimeconfig.json')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "plugin/AutoCADBridge/bin/Release/net8.0-windows/$artifact") -Destination $contentsPath
}
$manifest = @'
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AppVersion="0.1.0" Name="AutoCAD MCP Bridge" Description="Experimental local CAD Bridge" ProductCode="{F19F5DBA-39A5-4887-B3ED-458EF4C2D401}" UpgradeCode="{9D393C89-D4E1-4F57-A813-F9914F82117C}">
  <CompanyDetails Name="AutoCAD-MCP" />
  <Components>
    <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R25.1" SeriesMax="R25.1" />
    <ComponentEntry AppName="AutoCADMCPBridge" ModuleName="./Contents/Windows/AutoCADBridge.dll" AppDescription="Local authenticated CAD Bridge" LoadOnAutoCADStartup="False" />
  </Components>
</ApplicationPackage>
'@
Set-Content -LiteralPath (Join-Path $bundlePath 'PackageContents.xml') -Value $manifest -Encoding utf8
Write-Output "Installed Bridge at $bundlePath (listener starts only with MCPBRIDGE_START)"
