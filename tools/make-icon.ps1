# Draws the app icon (grape rounded square, golden blade and P) and writes src/paf/assets/prep-a-fight.ico.
# Rerun only to change the icon; the .ico is committed.
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$out = Join-Path $root "src\paf\assets\prep-a-fight.ico"
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null

function Rounded([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $p.AddArc($x, $y, 2 * $r, 2 * $r, 180, 90); $p.AddArc($x + $w - 2 * $r, $y, 2 * $r, 2 * $r, 270, 90)
    $p.AddArc($x + $w - 2 * $r, $y + $h - 2 * $r, 2 * $r, 2 * $r, 0, 90); $p.AddArc($x, $y + $h - 2 * $r, 2 * $r, 2 * $r, 90, 90)
    $p.CloseFigure(); return $p
}

function Draw([int]$n) {
    $bmp = New-Object System.Drawing.Bitmap $n, $n
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = "AntiAlias"; $g.TextRenderingHint = "AntiAliasGridFit"
    $s = $n / 256.0
    $bg = Rounded (4 * $s) (4 * $s) (248 * $s) (248 * $s) (52 * $s)
    $grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush (New-Object System.Drawing.PointF 0, 0), (New-Object System.Drawing.PointF $n, $n), ([System.Drawing.ColorTranslator]::FromHtml("#74526c")), ([System.Drawing.ColorTranslator]::FromHtml("#3f2b40"))
    $g.FillPath($grad, $bg)
    $gold = New-Object System.Drawing.Drawing2D.LinearGradientBrush (New-Object System.Drawing.PointF 0, 0), (New-Object System.Drawing.PointF $n, $n), ([System.Drawing.ColorTranslator]::FromHtml("#dbd053")), ([System.Drawing.ColorTranslator]::FromHtml("#c89933"))
    # the blade: a diagonal from bottom-left to top-right, behind the letter
    $blade = New-Object System.Drawing.Drawing2D.GraphicsPath
    $pts = @((New-Object System.Drawing.PointF (206 * $s), (34 * $s)), (New-Object System.Drawing.PointF (222 * $s), (50 * $s)),
             (New-Object System.Drawing.PointF (78 * $s), (194 * $s)), (New-Object System.Drawing.PointF (62 * $s), (178 * $s)))
    $blade.AddPolygon([System.Drawing.PointF[]]$pts)
    $g.FillPath($gold, $blade)
    $guard = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml("#c89933")), ([float](18 * $s))
    $guard.StartCap = "Round"; $guard.EndCap = "Round"
    $g.DrawLine($guard, [float](44 * $s), [float](160 * $s), [float](96 * $s), [float](212 * $s))
    $g.DrawLine($guard, [float](56 * $s), [float](200 * $s), [float](34 * $s), [float](222 * $s))
    # the P
    $font = New-Object System.Drawing.Font "Bahnschrift", ([float](150 * $s)), ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat; $fmt.Alignment = "Center"; $fmt.LineAlignment = "Center"
    $shadow = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(110, 0, 0, 0))
    $rect = New-Object System.Drawing.RectangleF ([float](0 * $s)), ([float](6 * $s)), ([float]$n), ([float]$n)
    $g.DrawString("P", $font, $shadow, (New-Object System.Drawing.RectangleF ([float](6 * $s)), ([float](12 * $s)), ([float]$n), ([float]$n)), $fmt)
    $g.DrawString("P", $font, [System.Drawing.Brushes]::White, $rect, $fmt)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    return , $ms.ToArray()
}

# ICO container with PNG-compressed entries (Windows Vista and later)
$sizes = 16, 24, 32, 48, 64, 128, 256
$images = @($sizes | ForEach-Object { , (Draw $_) })
$fs = [System.IO.File]::Create($out)
$w = New-Object System.IO.BinaryWriter $fs
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $d = $sizes[$i] % 256
    $w.Write([byte]$d); $w.Write([byte]$d); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([uint16]1); $w.Write([uint16]32); $w.Write([uint32]$images[$i].Length); $w.Write([uint32]$offset)
    $offset += $images[$i].Length
}
foreach ($img in $images) { $w.Write([byte[]]$img) }
$w.Close()
Write-Host "Icon: $out"
