# Scarica i font della presentazione (Google Fonts) in locale e genera fonts.css.
# Uso: powershell -File presentazione/fonts/_fetch_fonts.ps1
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$ua  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
$urls = @(
  'https://fonts.googleapis.com/css2?family=Instrument+Sans:wdth,wght@75..100,400..700&display=swap',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400..700&display=swap'
)
$out = New-Object System.Text.StringBuilder
foreach ($u in $urls) {
  $css = (Invoke-WebRequest -Uri $u -UserAgent $ua -UseBasicParsing).Content
  # Tiene solo i sottoinsiemi "latin" e "latin-ext" (accenti italiani inclusi)
  $blocks = [regex]::Matches($css, '/\*\s*(latin|latin-ext)\s*\*/\s*@font-face\s*\{[^}]*\}')
  foreach ($b in $blocks) {
    $subset = $b.Groups[1].Value
    $text = $b.Value
    $m = [regex]::Match($text, 'url\((https://[^)]+\.woff2)\)')
    $family = ([regex]::Match($text, "font-family:\s*'([^']+)'")).Groups[1].Value -replace '\s',''
    $file = "$family-$subset.woff2"
    Invoke-WebRequest -Uri $m.Groups[1].Value -OutFile (Join-Path $dir $file) -UseBasicParsing
    $text = $text.Replace($m.Groups[1].Value, $file)
    [void]$out.AppendLine($text)
  }
}
Set-Content -Path (Join-Path $dir 'fonts.css') -Value $out.ToString() -Encoding UTF8
Get-ChildItem $dir | Select-Object Name, Length
