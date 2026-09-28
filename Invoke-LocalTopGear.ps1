#Requires -Version 5.1
<#
.SYNOPSIS
    Top Gear local, multi-profils de combat, en 2 passes.

.DESCRIPTION
    Lit un export /simc (avec la case "Bags" cochee : sac + coffre hebdo), puis :

      Passe 1  : chaque item du sac/coffre est simme seul contre ton stuff equipe, sur chaque profil
                 de combat (1 cible, 2 cibles, AoE, M+, boss custom...). On garde les meilleurs par slot.
      Passe 2  : toutes les combinaisons des items gardes (4pc tier respecte, 1 seul item de coffre,
                 bijoux/anneaux distincts, dague+bouclier ou baton) sont simmees sur chaque profil.

    Resultat : meilleur set par profil, classement global pondere (poids par profil dans fights.csv),
    et "regret" = ce que tu perds sur chaque profil si tu ne changes pas de set entre les boss.

.EXAMPLE
    .\Invoke-LocalTopGear.ps1 -BaseProfile .\eduxi.simc -ResolveNames

.EXAMPLE
    .\Invoke-LocalTopGear.ps1 -BaseProfile .\eduxi.simc -Fights .\fights.csv -Pass2Error 0.1 -WorkThreads 4

.NOTES
    - Les profils de combat sont dans fights.csv (colonnes : name, weight, fight_style, targets, max_time,
      raid_events, talents, extra). weight=0 desactive une ligne.
    - Le script ne connait pas le type des armes du sac : passe -TwoHandIds pour les batons/2H,
      ou -ResolveNames (detection via le tooltip Wowhead).
    - Limite de 2 embellissements non geree : verifie a la main si tu as plus de 2 pieces embellies en sac.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseProfile,

    [string]$Fights,                    # CSV des profils de combat (defaut : fights.csv a cote du script, sinon presets integres)
    [string]$SimcPath,
    [int]$Threads = 0,
    [int]$WorkThreads = 0,              # >0 : profilesets en parallele (profileset_work_threads). A essayer : 4
    [double]$Pass1Error = 0.3,
    [double]$Pass2Error = 0.15,
    [int]$Iterations = 1000000,

    [int]$KeepArmor = 2,                # options gardees par slot d'armure apres la passe 1 (equipe compris)
    [int]$KeepJewelry = 3,              # items gardes pour anneaux / bijoux (equipes compris)
    [int]$KeepWeapons = 3,              # combos d'armes gardes (equipe compris)
    [double]$PruneBelow = -2.0,         # un item a moins de X% sur tous les profils est ecarte
    [int]$MaxCombos = 1500,             # au-dela, on retire les moins bonnes options jusqu'a passer sous la barre

    [int[]]$TierIds = @(271481, 271482, 271483, 271484, 271486),   # tier Ophidian Oracle (Elem S2)
    [int]$MinTier = 4,                  # nombre mini de pieces de tier dans un set (0 = pas de contrainte)
    [int[]]$TwoHandIds = @(),           # item IDs des armes a 2 mains presentes dans le sac / equipees

    [string]$NameMap,                   # CSV id,name pour nommer les items (la table de loot marche)
    [switch]$ResolveNames,              # noms + type d'arme via le tooltip Wowhead (cache local)
    [int]$WowheadLocale = 0,
    [switch]$NoVault,                   # ignorer la section "Weekly Reward Choices"
    [switch]$SkipPass1,                 # tout le sac directement en combinaisons (petits sacs seulement)
    [string]$OutDir,
    [int]$Top = 10,
    [switch]$DryRun,

    # --- Droptimizer re-optimise : items que tu n'as pas encore (table de loot) inseres dans les meilleurs sets ---
    [string]$Loot,                      # CSV de loot (meme format que le droptimizer : name,slot,id,bonus_id,ilvl,source)
    [int]$LootBase = 10,                # nb de meilleurs sets (par profil + global) dans lesquels on insere chaque item de loot (0 = tous)
    [int]$MaxLootItems = 1,             # 1 = un item de loot par set ; 2 = aussi les paires d'items de loot (beaucoup plus long)
    [int]$LootIlvl = 0,                 # force ilevel= sur les lignes de loot sans bonus_id
    [double]$Pass3Error = 0             # precision de la passe loot (0 = comme Pass2Error)
)

$ErrorActionPreference = 'Stop'
$Inv = [System.Globalization.CultureInfo]::InvariantCulture

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
function Get-FullPath([string]$p) { return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p) }

function Write-Utf8NoBom([string]$Path, [string]$Content) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Get-FullPath $Path), $Content, $enc)
}

function Find-Simc([string]$Hint) {
    if ($Hint) {
        if (Test-Path -LiteralPath $Hint) { return (Get-Item -LiteralPath $Hint).FullName }
        throw "simc introuvable : $Hint"
    }
    $cmd = Get-Command simc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @()
    if ($PSScriptRoot) { $candidates += (Join-Path $PSScriptRoot 'simc.exe'); $candidates += (Join-Path $PSScriptRoot 'simc\simc.exe') }
    foreach ($root in @('C:\simc', 'C:\SimulationCraft', "$env:USERPROFILE\Downloads", "$env:ProgramFiles")) {
        if ($root -and (Test-Path -LiteralPath $root)) {
            $found = Get-ChildItem -LiteralPath $root -Filter 'simc.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $candidates += $found.FullName }
        }
    }
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return (Get-Item -LiteralPath $c).FullName } }
    throw "simc.exe introuvable. Passe -SimcPath 'C:\chemin\vers\simc.exe' ou ajoute-le au PATH."
}

function Get-Col($row, [string[]]$names) {
    foreach ($n in $names) {
        foreach ($p in $row.PSObject.Properties) {
            if ($p.Name -ieq $n) { if ($null -eq $p.Value) { return '' } ; return ("$($p.Value)").Trim() }
        }
    }
    return ''
}

function Import-CsvAuto([string]$Path) {
    $first = Get-Content -LiteralPath $Path -TotalCount 1 -Encoding UTF8
    $delim = ','
    if ($first -and ($first -match ';') -and -not ($first -match ',')) { $delim = ';' }
    return @(Import-Csv -LiteralPath $Path -Delimiter $delim -Encoding UTF8)
}

function Get-EnchantToken([string]$GearValue) {
    if ($GearValue -match '(?:^|,)(enchant_id=\d+)')  { return $Matches[1] }
    if ($GearValue -match '(?:^|,)(enchant=[^,\s]+)') { return $Matches[1] }
    return $null
}

function Add-EnchantIfMissing([string]$Value, [string]$EquippedValue) {
    if (-not $EquippedValue) { return $Value }
    if ($Value -match '(?:^|,)enchant(_id)?=') { return $Value }
    $tok = Get-EnchantToken $EquippedValue
    if ($tok) { return "$Value,$tok" }
    return $Value
}

function Get-Family([string]$slot) {
    if ($slot -like 'finger*')  { return 'finger' }
    if ($slot -like 'trinket*') { return 'trinket' }
    if ($slot -eq 'shoulders')  { return 'shoulder' }
    if ($slot -eq 'wrists')     { return 'wrist' }
    return $slot
}

function Format-Pct([double]$v, [bool]$signed) {
    if ($signed) { return $v.ToString('+0.00;-0.00;0.00', $Inv) }
    return $v.ToString('0.00', $Inv)
}

function Resolve-Wowhead([string[]]$Ids, [string]$CachePath, [int]$Locale) {
    # retourne hashtable id -> @{ name=...; twohand=$true/$false }
    $cache = @{}
    if (Test-Path -LiteralPath $CachePath) {
        try {
            $obj = Get-Content -LiteralPath $CachePath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $obj.PSObject.Properties) {
                $v = $p.Value
                if ($v -is [string]) { $cache[$p.Name] = @{ name = $v; twohand = $false } }
                else { $cache[$p.Name] = @{ name = "$($v.name)"; twohand = [bool]$v.twohand } }
            }
        } catch { Write-Warning "Cache Wowhead illisible, on repart de zero." }
    }
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    $todo = @($Ids | Where-Object { $_ -and -not $cache.ContainsKey("$_") } | Sort-Object -Unique)
    if ($todo.Count -gt 0) { Write-Host ("Wowhead : resolution de {0} items..." -f $todo.Count) -ForegroundColor DarkGray }
    foreach ($id in $todo) {
        try {
            $uri  = "https://nether.wowhead.com/tooltip/item/$id" + "?dataEnv=1&locale=$Locale"
            $resp = Invoke-RestMethod -Uri $uri -TimeoutSec 15 -UserAgent 'Mozilla/5.0 (local-topgear)'
            $tt = "$($resp.tooltip)"
            $twoHand = ($tt -match 'Two-Hand|Deux mains|Zweihand|Dos manos|Due mani')
            if ($resp.name) { $cache["$id"] = @{ name = "$($resp.name)"; twohand = $twoHand } }
        } catch { Write-Warning "Wowhead : item $id non resolu ($($_.Exception.Message))" }
        Start-Sleep -Milliseconds 150
    }
    try {
        $out = @{}
        foreach ($k in $cache.Keys) { $out[$k] = @{ name = $cache[$k].name; twohand = $cache[$k].twohand } }
        ($out | ConvertTo-Json -Depth 3) | Set-Content -LiteralPath $CachePath -Encoding UTF8
    } catch { }
    return $cache
}

function Invoke-SimcRun([string]$SimcExe, [string]$RunFile, [string]$JsonPath, [string]$HtmlPath, [string]$LogPath, [double]$TargetErr, [string]$Label) {
    $simcArgs = @($RunFile)
    if ($script:Threads -gt 0)     { $simcArgs += "threads=$($script:Threads)" }
    if ($script:WorkThreads -gt 0) { $simcArgs += "profileset_work_threads=$($script:WorkThreads)" }
    $simcArgs += ("target_error=" + $TargetErr.ToString($Inv))
    $simcArgs += "iterations=$($script:Iterations)"
    $simcArgs += "json2=$JsonPath"
    $simcArgs += "html=$HtmlPath"

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    if (Test-Path variable:global:PSNativeCommandUseErrorActionPreference) { $global:PSNativeCommandUseErrorActionPreference = $false }
    $n = 0
    & $SimcExe @simcArgs 2>&1 | ForEach-Object {
        $s = "$_"
        if ($s.Contains("`r")) { $s = ($s -split "`r")[-1] }
        if ($s.Trim() -ne '') {
            Add-Content -LiteralPath $LogPath -Value $s
            $isProgress = ($s -match '^\s*(Profilesets|Generating)')
            if (-not $isProgress) { Write-Host "  $s" -ForegroundColor DarkGray }
            elseif ($s -match '^\s*Profilesets') { $n++; if ($n % 25 -eq 0) { Write-Host "  $Label : $s" -ForegroundColor DarkGray } }
        }
    }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    $sw.Stop()
    if ($code -ne 0 -or -not (Test-Path -LiteralPath $JsonPath)) {
        Write-Host "simc a echoue (code $code). Fin du log :" -ForegroundColor Red
        if (Test-Path -LiteralPath $LogPath) { Get-Content -LiteralPath $LogPath -Tail 25 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow } }
        throw "Echec simc sur $RunFile"
    }
    return $sw.Elapsed.TotalSeconds
}

function Read-SimcResults([string]$JsonPath) {
    $json = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $sim = $json.sim
    if (-not $sim) { throw "JSON inattendu : $JsonPath" }
    $baseMean = $null; $baseErr = 0.0
    try {
        $p0 = $sim.players[0]
        $baseMean = [double]$p0.collected_data.dps.mean
        if ($p0.collected_data.dps.PSObject.Properties['mean_std_dev']) { $baseErr = [double]$p0.collected_data.dps.mean_std_dev }
    } catch { }
    if (-not $baseMean) { try { $baseMean = [double]$sim.statistics.raid_dps.mean } catch { } }
    if (-not $baseMean) { throw "DPS de baseline illisible dans $JsonPath" }
    $res = @{}
    if ($sim.profilesets -and $sim.profilesets.results) {
        foreach ($r in $sim.profilesets.results) {
            $m = [double]$r.mean
            $e = 0.0
            if ($r.PSObject.Properties['mean_error'])      { $e = [double]$r.mean_error }
            elseif ($r.PSObject.Properties['mean_stddev']) { $e = [double]$r.mean_stddev }
            $res["$($r.name)"] = @{ Mean = $m; Err = $e; Delta = (100.0 * ($m - $baseMean) / $baseMean) }
        }
    }
    return @{ Base = $baseMean; BaseErr = $baseErr; Results = $res }
}

function New-RunFile([string]$Path, [string[]]$Base, [string[]]$Options, [string[]]$Profilesets, [string]$Title) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($l in $Base) { [void]$sb.AppendLine($l) }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine("# ---- $Title : options du profil de combat ----")
    foreach ($l in $Options) { [void]$sb.AppendLine($l) }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine("# ---- $Title : $($Profilesets.Count) lignes de profilesets ----")
    foreach ($l in $Profilesets) { [void]$sb.AppendLine($l) }
    Write-Utf8NoBom $Path $sb.ToString()
}

# ----------------------------------------------------------------------------
# 1. Lecture de l'export /simc : equipe + sac + coffre
# ----------------------------------------------------------------------------
$BaseProfile = Get-FullPath $BaseProfile
if (-not (Test-Path -LiteralPath $BaseProfile)) { throw "Profil introuvable : $BaseProfile" }
$baseLines = @(Get-Content -LiteralPath $BaseProfile -Encoding UTF8)
if ($baseLines | Where-Object { $_ -match '^\s*profileset\.' }) { throw "Le profil contient deja des profilesets : donne un export /simc brut." }

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if (-not $OutDir) { $OutDir = Join-Path (Get-Location) ("runs\topgear_" + $stamp) }
$OutDir = Get-FullPath $OutDir
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$cacheDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$wowheadCache = Join-Path $cacheDir 'wowhead_names_cache.json'

$slotRx = 'head|neck|shoulders?|back|chest|wrists?|hands|waist|legs|feet|finger1|finger2|trinket1|trinket2|main_hand|off_hand'
$rxGearEq = "^\s*($slotRx)\s*=\s*(.*)$"
$rxGearCm = "^\s*#\s*($slotRx)\s*=\s*(.*)$"
$rxName   = '^\s*#\s*(.+?)\s*\((\d+)\)\s*$'

$equipped = @{}          # slot -> value
$cands = [System.Collections.Generic.List[object]]::new()
$section = 'main'
$pendingName = ''; $pendingIlvl = ''
$candNo = 0
$warnings = [System.Collections.Generic.List[string]]::new()

function New-Cand([string]$Key, [string]$Slot, [string]$Value, [string]$Source) {
    $iid = ''
    if ($Value -match '(?:^|,)id=(\d+)') { $iid = $Matches[1] }
    $bid = ''
    if ($Value -match 'bonus_id=([\d/]+)') { $bid = $Matches[1] }
    return [pscustomobject]@{
        Key        = $Key
        Slot       = $Slot                # slot d'origine (finger1, trinket2, ...)
        Family     = (Get-Family $Slot)   # head, finger, trinket, main_hand, off_hand...
        Id         = $iid
        Bonus      = $bid
        Value      = $Value
        Name       = ''
        Ilvl       = ''
        Source     = $Source              # equipe / sac / coffre
        IsEquipped = ($Source -eq 'equipe')
        IsVault    = ($Source -eq 'coffre')
        IsTier     = ($iid -and ($script:TierIds -contains [int]$iid))
        TwoHand    = $false
        IsLoot     = ($Source -eq 'loot')
        LootSource = ''
    }
}

foreach ($l in $baseLines) {
    if ($l -match '^\s*###\s*(.+)$') {
        $h = $Matches[1]
        if ($h -match '^End of') { $section = 'other' }
        elseif ($h -match 'Bags') { $section = 'bags' }
        elseif ($h -match 'Weekly Reward') { $section = 'vault' }
        elseif ($h -match 'Linked gear') { $section = 'linked' }
        else { $section = 'other' }
        $pendingName = ''; $pendingIlvl = ''
        continue
    }
    if ($section -eq 'main' -and $l -match $rxGearEq) {
        $s = $Matches[1]; $v = $Matches[2].Trim()
        if ($s -eq 'shoulders') { $s = 'shoulder' }
        if ($s -eq 'wrists')    { $s = 'wrist' }
        $equipped[$s] = $v
        continue
    }
    if ($section -eq 'bags' -or $section -eq 'vault' -or $section -eq 'linked') {
        if ($section -eq 'vault' -and $NoVault) { continue }
        if ($l -match $rxGearCm) {
            $s = $Matches[1]; $v = $Matches[2].Trim()
            if ($s -eq 'shoulders') { $s = 'shoulder' }
            if ($s -eq 'wrists')    { $s = 'wrist' }
            $candNo++
            $src = if ($section -eq 'vault') { 'coffre' } elseif ($section -eq 'linked') { 'lien' } else { 'sac' }
            $c = New-Cand -Key ("B{0:D3}" -f $candNo) -Slot $s -Value $v -Source $src
            $c.Name = $pendingName; $c.Ilvl = $pendingIlvl
            $cands.Add($c)
            $pendingName = ''; $pendingIlvl = ''
            continue
        }
        if ($l -match $rxName) { $pendingName = $Matches[1]; $pendingIlvl = $Matches[2]; continue }
        if ($section -eq 'linked' -and $l -match '^\s*#\s*(\S.+?)\s*$' -and $l -notmatch '=') { $pendingName = $Matches[1]; continue }
    }
}

if ($equipped.Count -eq 0) { throw "Aucune piece equipee trouvee : est-ce bien un export /simc ?" }
if ($cands.Count -eq 0) { throw "Aucun item de sac/coffre trouve. Coche 'Bags' dans la fenetre /simc de l'addon avant d'exporter." }

# table de loot -> candidats "hypothetiques"
$LootSlotAlias = @{
    'head' = 'head'; 'helm' = 'head'; 'tete' = 'head'; 'neck' = 'neck'; 'cou' = 'neck';
    'shoulder' = 'shoulder'; 'shoulders' = 'shoulder'; 'epaules' = 'shoulder'; 'back' = 'back'; 'cloak' = 'back'; 'cape' = 'back';
    'chest' = 'chest'; 'torse' = 'chest'; 'wrist' = 'wrist'; 'wrists' = 'wrist'; 'bracers' = 'wrist';
    'hands' = 'hands'; 'gloves' = 'hands'; 'gants' = 'hands'; 'waist' = 'waist'; 'belt' = 'waist'; 'ceinture' = 'waist';
    'legs' = 'legs'; 'jambes' = 'legs'; 'feet' = 'feet'; 'boots' = 'feet'; 'bottes' = 'feet';
    'finger' = 'finger'; 'ring' = 'finger'; 'anneau' = 'finger'; 'finger1' = 'finger'; 'finger2' = 'finger';
    'trinket' = 'trinket'; 'bijou' = 'trinket'; 'trinket1' = 'trinket'; 'trinket2' = 'trinket';
    'main_hand' = 'main_hand'; 'mainhand' = 'main_hand'; 'mh' = 'main_hand'; '1h' = 'main_hand'; 'weapon' = 'main_hand'; 'arme' = 'main_hand';
    'off_hand' = 'off_hand'; 'offhand' = 'off_hand'; 'oh' = 'off_hand'; 'shield' = 'off_hand'; 'bouclier' = 'off_hand';
    'two_hand' = 'two_hand'; 'twohand' = 'two_hand'; '2h' = 'two_hand'; 'staff' = 'two_hand'; 'baton' = 'two_hand'
}
if ($Loot) {
    $lootPath = Get-FullPath $Loot
    if (-not (Test-Path -LiteralPath $lootPath)) { throw "Table de loot introuvable : $lootPath" }
    $ln = 0
    foreach ($row in (Import-CsvAuto $lootPath)) {
        $ln++
        $lName = Get-Col $row @('name', 'item', 'nom'); $lSlot = Get-Col $row @('slot', 'emplacement'); $lId = Get-Col $row @('id', 'item_id', 'itemid')
        $lBonus = Get-Col $row @('bonus_id', 'bonus', 'bonus_ids'); $lIlvl = Get-Col $row @('ilvl', 'ilevel', 'item_level')
        $lSrc = Get-Col $row @('source', 'boss', 'donjon', 'dungeon'); $lSkip = Get-Col $row @('skip', 'ignore')
        if ($lSkip -match '^(1|true|oui|yes|x)$') { continue }
        if (-not $lId -or $lId -notmatch '^\d+$' -or -not $lSlot) { Write-Warning "Loot ligne $ln ignoree (id/slot manquant) : '$lName'"; continue }
        $sk = $lSlot.ToLower() -replace '\s', ''
        if (-not $LootSlotAlias.ContainsKey($sk)) { Write-Warning "Loot ligne $ln ignoree (slot inconnu '$lSlot')"; continue }
        $lFam = $LootSlotAlias[$sk]
        if ($LootIlvl -gt 0 -and -not $lBonus) { $lIlvl = "$LootIlvl" }
        if ($lBonus) { $lBonus = ($lBonus -replace '[^\d/]', '') }
        $lVal = ",id=$lId"
        if ($lBonus) { $lVal += ",bonus_id=$lBonus" } elseif ($lIlvl) { $lVal += ",ilevel=$lIlvl" }
        $lSlotName = switch ($lFam) { 'finger' { 'finger1' } 'trinket' { 'trinket1' } 'two_hand' { 'main_hand' } default { $lFam } }
        $c = New-Cand -Key ("L{0:D3}" -f $ln) -Slot $lSlotName -Value $lVal -Source 'loot'
        $c.Name = $(if ($lName) { $lName } else { "item $lId" }); $c.Ilvl = $lIlvl; $c.LootSource = $lSrc
        if ($lFam -eq 'two_hand') { $c.TwoHand = $true }
        $cands.Add($c)
    }
}

# items equipes -> candidats
foreach ($s in @($equipped.Keys)) {
    $c = New-Cand -Key ("E_" + $s) -Slot $s -Value $equipped[$s] -Source 'equipe'
    $c.Name = ''
    $cands.Add($c)
}

# doublons (meme id + bonus) : on garde le premier (equipe d'abord)
$seen = @{}
$dedup = [System.Collections.Generic.List[object]]::new()
foreach ($c in ($cands | Sort-Object -Property @{Expression = { if ($_.IsEquipped) { 0 } else { 1 } }})) {
    $k = "$($c.Id)|$($c.Bonus)"
    if ($c.Id -and $seen.ContainsKey($k)) { continue }
    $seen[$k] = $true
    $dedup.Add($c)
}
$cands = $dedup

# noms
$nameTable = @{}
if ($NameMap) {
    $nmPath = Get-FullPath $NameMap
    if (Test-Path -LiteralPath $nmPath) {
        foreach ($r in (Import-CsvAuto $nmPath)) {
            $i = Get-Col $r @('id', 'item_id', 'itemid'); $n = Get-Col $r @('name', 'item', 'nom')
            if ($i -and $n -and -not $nameTable.ContainsKey($i)) { $nameTable[$i] = $n }
        }
    } else { Write-Warning "NameMap introuvable : $nmPath" }
}
$wh = @{}
if ($ResolveNames) {
    $wh = Resolve-Wowhead -Ids @($cands | ForEach-Object { $_.Id }) -CachePath $wowheadCache -Locale $WowheadLocale
}
foreach ($c in $cands) {
    if (-not $c.Name -and $c.Id -and $nameTable.ContainsKey($c.Id)) { $c.Name = $nameTable[$c.Id] }
    if (-not $c.Name -and $c.Id -and $wh.ContainsKey($c.Id))        { $c.Name = $wh[$c.Id].name }
    if (-not $c.Name) { $c.Name = "item $($c.Id)" }
    if ($c.Family -eq 'main_hand') {
        if ($TwoHandIds -contains [int]$c.Id) { $c.TwoHand = $true }
        elseif ($wh.ContainsKey($c.Id) -and $wh[$c.Id].twohand) { $c.TwoHand = $true }
    }
}
# arme equipee : avec off-hand => 1H ; sans => 2H (ou piege off-hand, on previent)
$eqMH = $cands | Where-Object { $_.IsEquipped -and $_.Family -eq 'main_hand' } | Select-Object -First 1
$eqOH = $cands | Where-Object { $_.IsEquipped -and $_.Family -eq 'off_hand' }  | Select-Object -First 1
if ($eqMH) {
    if ($eqOH) { $eqMH.TwoHand = $false }
    elseif (-not $eqMH.TwoHand) {
        $eqMH.TwoHand = $true
        $warnings.Add("Pas d'off_hand equipee : l'arme equipee est traitee comme une 2 mains. Si tu joues une 1H, refais l'export avec l'off-hand equipee.")
    }
}
$bagWeps = @($cands | Where-Object { -not $_.IsEquipped -and $_.Family -eq 'main_hand' -and -not $_.TwoHand })
if ($bagWeps.Count -gt 0 -and -not $ResolveNames -and $TwoHandIds.Count -eq 0) {
    $warnings.Add("Armes du sac traitees comme 1 main par defaut : " + (($bagWeps | ForEach-Object { "$($_.Name) [$($_.Id)]" }) -join ', ') + ". Si l'une est un baton : -TwoHandIds <id> ou -ResolveNames.")
}

# ----------------------------------------------------------------------------
# 2. Profils de combat
# ----------------------------------------------------------------------------
$profiles = [System.Collections.Generic.List[object]]::new()
function Add-Profile([string]$Name, [double]$Weight, [string]$Style, [string]$Targets, [string]$MaxTime, [string]$RaidEvents, [string]$Talents, [string]$Extra, [string[]]$RawLines) {
    if ($Weight -le 0) { return }
    $opts = @()
    if ($RawLines) { foreach ($rl in $RawLines) { $t = $rl.Trim(); if ($t -and -not $t.StartsWith('#')) { $opts += $t } } }
    if ($Style)   { $opts += "fight_style=$Style" }
    if ($Targets) { $opts += "desired_targets=$Targets" }
    if ($MaxTime) { $opts += "max_time=$MaxTime" }
    if ($RaidEvents) {
        foreach ($ev in ($RaidEvents -split '\|')) {
            $e = $ev.Trim(); if (-not $e) { continue }
            if ($e -notmatch '^/') { $e = "/$e" }
            $opts += "raid_events+=$e"
        }
    }
    if ($Talents) { $opts += "talents=$Talents" }
    if ($Extra) { foreach ($x in ($Extra -split '\|')) { $x2 = $x.Trim(); if ($x2) { $opts += $x2 } } }
    $safe = (($Name -replace '\+', 'plus') -replace '[^\w\-]', '_')
    $profiles.Add([pscustomobject]@{ Name = $Name; Safe = $safe; Weight = $Weight; Options = $opts })
}

$fightsPath = $null
if ($Fights) { $fightsPath = Get-FullPath $Fights; if (-not (Test-Path -LiteralPath $fightsPath)) { throw "Fichier de profils introuvable : $fightsPath" } }
elseif ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'fights.csv'))) { $fightsPath = Join-Path $PSScriptRoot 'fights.csv' }

if ($fightsPath) {
    foreach ($r in (Import-CsvAuto $fightsPath)) {
        $nm = Get-Col $r @('name', 'nom', 'profil')
        if (-not $nm) { continue }
        $wRaw = Get-Col $r @('weight', 'poids')
        $w = 1.0
        if ($wRaw) { $w = [double]::Parse(($wRaw -replace ',', '.'), $Inv) }
        $rawLines = @()
        $fileCol = Get-Col $r @('file', 'fichier')
        if ($fileCol) {
            $fp = $fileCol
            if (-not [System.IO.Path]::IsPathRooted($fp)) { $fp = Join-Path (Split-Path $fightsPath -Parent) $fileCol }
            if (-not (Test-Path -LiteralPath $fp)) { throw "Profil '$nm' : fichier introuvable : $fp" }
            $rawLines = @(Get-Content -LiteralPath $fp -Encoding UTF8)
        }
        Add-Profile -Name $nm -Weight $w -Style (Get-Col $r @('fight_style', 'style')) -Targets (Get-Col $r @('targets', 'cibles', 'desired_targets')) `
            -MaxTime (Get-Col $r @('max_time', 'duree')) -RaidEvents (Get-Col $r @('raid_events', 'events')) -Talents (Get-Col $r @('talents')) -Extra (Get-Col $r @('extra', 'options')) -RawLines $rawLines
    }
    Write-Host ("Profils de combat : {0} ({1})" -f $profiles.Count, (Split-Path $fightsPath -Leaf)) -ForegroundColor DarkGray
} else {
    Add-Profile '1 cible'   4 'Patchwerk' '1' '300' '' '' ''
    Add-Profile '2 cibles'  2 'Patchwerk' '2' '300' '' '' ''
    Add-Profile '3 cibles'  1 'Patchwerk' '3' '300' '' '' ''
    Add-Profile 'AoE 5'     1 'Patchwerk' '5' '240' '' '' ''
    Add-Profile 'M+'        2 'DungeonSlice' '' '' '' '' ''
    Write-Host "Profils de combat : presets integres (1/2/3 cibles, AoE 5, M+)" -ForegroundColor DarkGray
}
if ($profiles.Count -eq 0) { throw "Aucun profil de combat actif (weight > 0)." }

# ----------------------------------------------------------------------------
# 3. Candidats par slot + combos d'armes
# ----------------------------------------------------------------------------
$armorFamilies = @('head', 'neck', 'shoulder', 'back', 'chest', 'wrist', 'hands', 'waist', 'legs', 'feet')

$mh1H = @($cands | Where-Object { $_.Family -eq 'main_hand' -and -not $_.TwoHand })
$mh2H = @($cands | Where-Object { $_.Family -eq 'main_hand' -and $_.TwoHand })
$ohs  = @($cands | Where-Object { $_.Family -eq 'off_hand' })
$wepCombos = [System.Collections.Generic.List[object]]::new()
$wNo = 0
foreach ($mh in $mh1H) {
    foreach ($oh in $ohs) {
        $wNo++
        $wepCombos.Add([pscustomobject]@{
            Key = ("W{0:D3}" -f $wNo); Family = 'weapon'; MH = $mh; OH = $oh
            Name = "$($mh.Name) + $($oh.Name)"
            IsEquipped = ($mh.IsEquipped -and $oh.IsEquipped)
            VaultCount = (@($mh, $oh | Where-Object { $_.IsVault }).Count)
            LootCount  = (@($mh, $oh | Where-Object { $_.IsLoot }).Count)
        })
    }
}
foreach ($th in $mh2H) {
    $wNo++
    $wepCombos.Add([pscustomobject]@{
        Key = ("W{0:D3}" -f $wNo); Family = 'weapon'; MH = $th; OH = $null
        Name = "$($th.Name) (2 mains)"
        IsEquipped = $th.IsEquipped
        VaultCount = $(if ($th.IsVault) { 1 } else { 0 })
        LootCount  = $(if ($th.IsLoot) { 1 } else { 0 })
    })
}
if ($mh1H.Count -gt 0 -and $ohs.Count -eq 0) { $warnings.Add("Des armes 1 main sont candidates mais aucune off-hand n'est disponible : elles ne seront pas testees.") }

function Get-Lines-ForArmor($c) {
    # ligne de gear pour un candidat d'armure place dans son slot
    $v = Add-EnchantIfMissing $c.Value $equipped[$c.Family]
    return @("$($c.Family)=$v")
}
function Get-Lines-ForPair($a, $b, [string]$fam) {
    $s1 = "${fam}1"; $s2 = "${fam}2"
    $first = $a; $second = $b
    if ($b.IsEquipped -and $b.Slot -eq $s1) { $first = $b; $second = $a }
    elseif ($a.IsEquipped -and $a.Slot -eq $s2) { $first = $b; $second = $a }
    $v1 = Add-EnchantIfMissing $first.Value $equipped[$s1]
    $v2 = Add-EnchantIfMissing $second.Value $equipped[$s2]
    return @("$s1=$v1", "$s2=$v2")
}
function Get-Lines-ForWeapon($w) {
    $out = @()
    $out += ("main_hand=" + (Add-EnchantIfMissing $w.MH.Value $equipped['main_hand']))
    if ($w.OH) { $out += ("off_hand=" + (Add-EnchantIfMissing $w.OH.Value $equipped['off_hand'])) } else { $out += 'off_hand=' }
    return $out
}

foreach ($w in $warnings) { Write-Warning $w }
$nBag = @($cands | Where-Object { $_.Source -eq 'sac' }).Count
$nVault = @($cands | Where-Object { $_.Source -eq 'coffre' }).Count
$nLinked = @($cands | Where-Object { $_.Source -eq 'lien' }).Count
$nLoot = @($cands | Where-Object { $_.IsLoot }).Count
Write-Host ("Items : {0} equipes, {1} en sac, {2} au coffre, {3} lies (/simc [lien]), {4} de la table de loot, {5} combos d'armes" -f @($cands | Where-Object { $_.IsEquipped }).Count, $nBag, $nVault, $nLinked, $nLoot, $wepCombos.Count) -ForegroundColor Cyan

$simcExe = $null
if (-not $DryRun) { $simcExe = Find-Simc $SimcPath; Write-Host "simc : $simcExe" -ForegroundColor DarkGray }

# ----------------------------------------------------------------------------
# 4. Passe 1 : chaque item seul, sur chaque profil
# ----------------------------------------------------------------------------
$p1 = @{}    # key candidat/combo -> hashtable profil -> delta (meilleure variante)
$p1Time = 0.0; $p1Count = 0

# profilesets de la passe 1 (identiques pour tous les profils)
$p1Sets = [System.Collections.Generic.List[object]]::new()   # {Name, Key, Lines}
foreach ($c in $cands) {
    if ($c.IsEquipped) { continue }
    if ($c.Family -eq 'main_hand' -or $c.Family -eq 'off_hand') { continue }   # via combos d'armes
    if ($c.Family -eq 'finger' -or $c.Family -eq 'trinket') {
        foreach ($pos in @(1, 2)) {
            $slot = "$($c.Family)$pos"
            $v = Add-EnchantIfMissing $c.Value $equipped[$slot]
            $p1Sets.Add([pscustomobject]@{ Name = "$($c.Key)_$slot"; Key = $c.Key; Lines = @("$slot=$v") })
        }
    } else {
        $p1Sets.Add([pscustomobject]@{ Name = "$($c.Key)_$($c.Family)"; Key = $c.Key; Lines = (Get-Lines-ForArmor $c) })
    }
}
foreach ($w in $wepCombos) {
    if ($w.IsEquipped) { continue }
    $p1Sets.Add([pscustomobject]@{ Name = $w.Key; Key = $w.Key; Lines = (Get-Lines-ForWeapon $w) })
}

if (-not $SkipPass1) {
    Write-Host ""
    Write-Host ("=== Passe 1 : {0} profilesets x {1} profils (target_error {2}) ===" -f $p1Sets.Count, $profiles.Count, $Pass1Error.ToString($Inv)) -ForegroundColor Cyan
    foreach ($pf in $profiles) {
        $dir = Join-Path $OutDir ("pass1_" + $pf.Safe); New-Item -ItemType Directory -Path $dir -Force | Out-Null
        $runFile = Join-Path $dir 'run.simc'
        $lines = @()
        foreach ($s in $p1Sets) { foreach ($gl in $s.Lines) { $lines += "profileset.`"$($s.Name)`"+=$gl" } }
        New-RunFile -Path $runFile -Base $baseLines -Options $pf.Options -Profilesets $lines -Title ("Passe 1 / " + $pf.Name)
        if ($DryRun) { Write-Host "  [DryRun] $runFile" -ForegroundColor Yellow; continue }
        Write-Host ("- {0} ..." -f $pf.Name) -ForegroundColor White
        $secs = Invoke-SimcRun -SimcExe $simcExe -RunFile $runFile -JsonPath (Join-Path $dir 'report.json') -HtmlPath (Join-Path $dir 'report.html') -LogPath (Join-Path $dir 'simc.log') -TargetErr $Pass1Error -Label $pf.Name
        $p1Time += $secs; $p1Count += $p1Sets.Count
        $res = Read-SimcResults (Join-Path $dir 'report.json')
        $rows = @()
        foreach ($s in $p1Sets) {
            if (-not $res.Results.ContainsKey($s.Name)) { continue }
            $d = $res.Results[$s.Name].Delta
            if (-not $p1.ContainsKey($s.Key)) { $p1[$s.Key] = @{} }
            if (-not $p1[$s.Key].ContainsKey($pf.Name) -or $d -gt $p1[$s.Key][$pf.Name]) { $p1[$s.Key][$pf.Name] = $d }
            $rows += [pscustomobject]@{ profileset = $s.Name; delta_pct = [math]::Round($d, 3); err_pct = [math]::Round(100.0 * $res.Results[$s.Name].Err / $res.Results[$s.Name].Mean, 3) }
        }
        $rows | Sort-Object -Property delta_pct -Descending | Export-Csv -LiteralPath (Join-Path $dir 'pass1.csv') -NoTypeInformation -Encoding UTF8
        Write-Host ("  {0} : baseline {1} DPS, {2} profilesets en {3:mm\:ss}" -f $pf.Name, $res.Base.ToString('N0', $Inv), $p1Sets.Count, [TimeSpan]::FromSeconds($secs)) -ForegroundColor DarkGray
    }
}

# ----------------------------------------------------------------------------
# 5. Selection des options par slot
# ----------------------------------------------------------------------------
function Get-MaxDelta([string]$key) {
    if (-not $p1.ContainsKey($key)) { return 0.0 }
    $m = -999.0
    foreach ($v in $p1[$key].Values) { if ($v -gt $m) { $m = $v } }
    return $m
}
function Select-Top([object[]]$items, [int]$keepTotal) {
    # $items : candidats non equipes d'une famille ; retourne l'union des top (keepTotal-1) par profil
    $kept = @{}
    if ($SkipPass1 -or $p1.Count -eq 0) { foreach ($i in $items) { $kept[$i.Key] = $i }; return @($kept.Values) }
    $n = [math]::Max(0, $keepTotal - 1)
    foreach ($pf in $profiles) {
        $ranked = @($items | Where-Object { $p1.ContainsKey($_.Key) -and $p1[$_.Key].ContainsKey($pf.Name) -and $p1[$_.Key][$pf.Name] -ge $PruneBelow } |
                    Sort-Object -Property @{Expression = { $p1[$_.Key][$pf.Name] }; Descending = $true} | Select-Object -First $n)
        foreach ($i in $ranked) { $kept[$i.Key] = $i }
    }
    return @($kept.Values)
}

$slotOptions = [ordered]@{}   # famille -> liste d'options (candidats / paires / combos d'armes)
foreach ($fam in $armorFamilies) {
    $opts = @()
    $eq = $cands | Where-Object { $_.IsEquipped -and $_.Family -eq $fam } | Select-Object -First 1
    if ($eq) { $opts += $eq }
    $opts += Select-Top @($cands | Where-Object { -not $_.IsEquipped -and -not $_.IsLoot -and $_.Family -eq $fam }) $KeepArmor
    if ($opts.Count -gt 0) { $slotOptions[$fam] = $opts }
}
$jewelryItems = @{}
foreach ($fam in @('finger', 'trinket')) {
    $items = @($cands | Where-Object { $_.IsEquipped -and $_.Family -eq $fam })
    $items += Select-Top @($cands | Where-Object { -not $_.IsEquipped -and -not $_.IsLoot -and $_.Family -eq $fam }) $KeepJewelry
    $jewelryItems[$fam] = $items
}
$wepKept = @($wepCombos | Where-Object { $_.IsEquipped })
$wepKept += Select-Top @($wepCombos | Where-Object { -not $_.IsEquipped -and $_.LootCount -eq 0 }) $KeepWeapons
if ($wepKept.Count -gt 0) { $slotOptions['weapon'] = $wepKept }

function New-Pair($a, $b) {
    return [pscustomobject]@{
        Key = "$($a.Key)+$($b.Key)"; A = $a; B = $b; Family = $a.Family
        Name = "$($a.Name) + $($b.Name)"
        IsEquipped = ($a.IsEquipped -and $b.IsEquipped)
        VaultCount = (@($a, $b | Where-Object { $_.IsVault }).Count)
        LootCount  = (@($a, $b | Where-Object { $_.IsLoot }).Count)
    }
}
function New-Pairs([object[]]$items) {
    $pairs = [System.Collections.Generic.List[object]]::new()
    for ($i = 0; $i -lt $items.Count; $i++) {
        for ($j = $i + 1; $j -lt $items.Count; $j++) {
            $a = $items[$i]; $b = $items[$j]
            if ($a.Id -and $a.Id -eq $b.Id) { continue }   # unique-equipped
            $pairs.Add((New-Pair $a $b))
        }
    }
    return $pairs.ToArray()
}
foreach ($fam in @('finger', 'trinket')) {
    $pairs = New-Pairs $jewelryItems[$fam]
    if ($pairs.Count -gt 0) { $slotOptions[$fam] = $pairs }
}

function Get-ComboCount {
    $n = 1
    foreach ($k in $slotOptions.Keys) { $n *= [math]::Max(1, $slotOptions[$k].Count) }
    return $n
}
function Get-OptionScore($opt) {
    if ($opt.PSObject.Properties['A']) {
        $m = -999.0
        foreach ($x in @($opt.A, $opt.B)) { if (-not $x.IsEquipped) { $d = Get-MaxDelta $x.Key; if ($d -gt $m) { $m = $d } } }
        if ($m -eq -999.0) { $m = 0.0 }
        return $m
    }
    if ($opt.IsEquipped) { return 0.0 }
    return (Get-MaxDelta $opt.Key)
}

# reduction gloutonne si trop de combinaisons
$removed = @()
while ((Get-ComboCount) -gt $MaxCombos) {
    $bestFam = $null; $bestCount = 1
    foreach ($k in $slotOptions.Keys) { if ($slotOptions[$k].Count -gt $bestCount) { $bestCount = $slotOptions[$k].Count; $bestFam = $k } }
    if (-not $bestFam) { break }
    $fam = $bestFam
    if ($fam -eq 'finger' -or $fam -eq 'trinket') {
        # on retire le moins bon item non equipe, puis on regenere les paires
        $items = @($jewelryItems[$fam])
        $worst = $items | Where-Object { -not $_.IsEquipped } | Sort-Object -Property @{Expression = { Get-MaxDelta $_.Key }} | Select-Object -First 1
        if (-not $worst) { break }
        $jewelryItems[$fam] = @($items | Where-Object { $_.Key -ne $worst.Key })
        $slotOptions[$fam] = New-Pairs $jewelryItems[$fam]
        $removed += "$($worst.Name) ($fam)"
    } else {
        $opts = @($slotOptions[$fam])
        $worst = $opts | Where-Object { -not $_.IsEquipped } | Sort-Object -Property @{Expression = { Get-OptionScore $_ }} | Select-Object -First 1
        if (-not $worst) { break }
        $slotOptions[$fam] = @($opts | Where-Object { $_.Key -ne $worst.Key })
        $removed += "$($worst.Name) ($fam)"
    }
}
if ($removed.Count -gt 0) { Write-Warning ("Trop de combinaisons (> $MaxCombos) : options retirees -> " + ($removed -join '; ')) }

# ----------------------------------------------------------------------------
# 6. Generation des combinaisons
# ----------------------------------------------------------------------------
$famOrder = @($slotOptions.Keys)

function Build-Combo($picks, [string]$name) {
    # $picks : famille -> option (candidat / paire / combo d'armes). Retourne $null si le set est invalide ou identique a l'equipe.
    $tier = 0; $vault = 0; $loot = 0; $allEq = $true
    $lines = @(); $diff = @(); $keys = @(); $lootKeys = @(); $lootNames = @()
    foreach ($fam in $famOrder) {
        $o = $picks[$fam]
        if (-not $o) { continue }
        $keys += $o.Key
        if ($fam -eq 'finger' -or $fam -eq 'trinket') {
            $vault += $o.VaultCount; $loot += $o.LootCount
            if (-not $o.IsEquipped) {
                $allEq = $false; $lines += Get-Lines-ForPair $o.A $o.B $fam
                foreach ($x in @($o.A, $o.B)) {
                    if (-not $x.IsEquipped) { $diff += "$($x.Name) [$fam]" }
                    if ($x.IsLoot) { $lootKeys += $x.Key; $lootNames += $x.Name }
                }
            }
        } elseif ($fam -eq 'weapon') {
            $vault += $o.VaultCount; $loot += $o.LootCount
            if (-not $o.IsEquipped) {
                $allEq = $false; $lines += Get-Lines-ForWeapon $o; $diff += "$($o.Name) [arme]"
                foreach ($x in @($o.MH, $o.OH)) { if ($x -and $x.IsLoot) { $lootKeys += $x.Key; $lootNames += $x.Name } }
            }
        } else {
            if ($o.IsTier) { $tier++ }
            if ($o.IsVault) { $vault++ }
            if ($o.IsLoot) { $loot++; $lootKeys += $o.Key; $lootNames += $o.Name }
            if (-not $o.IsEquipped) { $allEq = $false; $lines += Get-Lines-ForArmor $o; $diff += "$($o.Name) [$fam]" }
        }
    }
    if ($MinTier -gt 0 -and $tier -lt $MinTier) { return 'tier' }
    if ($vault -gt 1) { return 'vault' }
    if ($loot -gt $MaxLootItems) { return 'loot' }
    if ($allEq) { return $null }
    return [pscustomobject]@{
        Name = $name; Picks = $picks; Lines = $lines; Diff = ($diff -join ' ; '); Tier = $tier; Vault = $vault; Loot = $loot
        LootKeys = $lootKeys; LootNames = $lootNames; Key = (($keys | Sort-Object) -join '|'); Deltas = @{}
    }
}

$combos = [System.Collections.Generic.List[object]]::new()
$idx = @(0) * $famOrder.Count
$counts = @($famOrder | ForEach-Object { $slotOptions[$_].Count })
$cNo = 0
$total = Get-ComboCount
$rejTier = 0; $rejVault = 0
$seenKeys = @{}
for ($n = 0; $n -lt $total; $n++) {
    $picks = [ordered]@{}
    for ($i = 0; $i -lt $famOrder.Count; $i++) { $picks[$famOrder[$i]] = $slotOptions[$famOrder[$i]][$idx[$i]] }
    for ($i = 0; $i -lt $famOrder.Count; $i++) { $idx[$i]++; if ($idx[$i] -lt $counts[$i]) { break } ; $idx[$i] = 0 }
    $obj = Build-Combo $picks ("C{0:D4}" -f ($cNo + 1))
    if ($null -eq $obj) { continue }
    if ($obj -is [string]) { if ($obj -eq 'tier') { $rejTier++ } elseif ($obj -eq 'vault') { $rejVault++ } ; continue }
    if ($seenKeys.ContainsKey($obj.Key)) { continue }
    $seenKeys[$obj.Key] = $true
    $cNo++
    $combos.Add($obj)
}

Write-Host ""
Write-Host "=== Passe 2 : options retenues (sans la table de loot) ===" -ForegroundColor Cyan
foreach ($fam in $famOrder) {
    $names = @($slotOptions[$fam] | ForEach-Object { if ($_.IsEquipped) { "[equipe]" } else { $_.Name } })
    Write-Host ("  {0,-9} {1}" -f $fam, ($names -join ' | ')) -ForegroundColor DarkGray
}
Write-Host ("  -> {0} combinaisons a simmer ({1} rejetees : tier < {2}, {3} rejetees : 2+ items de coffre)" -f $combos.Count, $rejTier, $MinTier, $rejVault) -ForegroundColor Cyan
if ($p1Count -gt 0) {
    $tPer = $p1Time / $p1Count
    $ratio = [math]::Pow(($Pass1Error / $Pass2Error), 2)
    $est = $tPer * $ratio * $combos.Count * $profiles.Count
    Write-Host ("  Temps estime passe 2 : ~{0:hh\:mm\:ss} (base : {1:0.0}s par profileset en passe 1)" -f [TimeSpan]::FromSeconds($est), $tPer) -ForegroundColor DarkGray
    if ($est -gt 3600) { Write-Host "  (long : monte -Pass2Error, baisse -MaxCombos, ou essaie -WorkThreads 4)" -ForegroundColor DarkYellow }
}

# ----------------------------------------------------------------------------
# 7. Passe 2 : combinaisons x profils
# ----------------------------------------------------------------------------
function Invoke-ComboPass([string]$Prefix, $ComboList, [double]$TargetErr, [string]$Title) {
    # lance un run par profil pour la liste de combos, remplit .Deltas ; retourne @{ Time=; Count= }
    $tSum = 0.0; $cnt = 0
    foreach ($pf in $profiles) {
        $dir = Join-Path $OutDir ($Prefix + "_" + $pf.Safe); New-Item -ItemType Directory -Path $dir -Force | Out-Null
        $runFile = Join-Path $dir 'run.simc'
        $lines = @()
        foreach ($c in $ComboList) { foreach ($gl in $c.Lines) { $lines += "profileset.`"$($c.Name)`"+=$gl" } }
        New-RunFile -Path $runFile -Base $baseLines -Options $pf.Options -Profilesets $lines -Title ($Title + " / " + $pf.Name)
        if ($DryRun) { Write-Host "  [DryRun] $runFile" -ForegroundColor Yellow; continue }
        Write-Host ("- {0} ..." -f $pf.Name) -ForegroundColor White
        $secs = Invoke-SimcRun -SimcExe $simcExe -RunFile $runFile -JsonPath (Join-Path $dir 'report.json') -HtmlPath (Join-Path $dir 'report.html') -LogPath (Join-Path $dir 'simc.log') -TargetErr $TargetErr -Label $pf.Name
        $tSum += $secs; $cnt += $ComboList.Count
        $res = Read-SimcResults (Join-Path $dir 'report.json')
        foreach ($c in $ComboList) { if ($res.Results.ContainsKey($c.Name)) { $c.Deltas[$pf.Name] = $res.Results[$c.Name].Delta } }
        $rows = foreach ($c in ($ComboList | Where-Object { $_.Deltas.ContainsKey($pf.Name) } | Sort-Object -Property @{Expression = { $_.Deltas[$pf.Name] }; Descending = $true})) {
            [pscustomobject]@{ combo = $c.Name; delta_pct = [math]::Round($c.Deltas[$pf.Name], 3); err_pct = [math]::Round(100.0 * $res.Results[$c.Name].Err / $res.Results[$c.Name].Mean, 3); loot = ($c.LootNames -join ' ; '); changes = $c.Diff }
        }
        $rows | Export-Csv -LiteralPath (Join-Path $dir 'results.csv') -NoTypeInformation -Encoding UTF8
        Write-Host ("  {0} : baseline {1} DPS, {2} sets en {3:mm\:ss}" -f $pf.Name, $res.Base.ToString('N0', $Inv), $ComboList.Count, [TimeSpan]::FromSeconds($secs)) -ForegroundColor DarkGray
    }
    return @{ Time = $tSum; Count = $cnt }
}

$wSum = 0.0; foreach ($pf in $profiles) { $wSum += $pf.Weight }
function Set-Composite($combo) {
    $sc = 0.0
    foreach ($pf in $profiles) { if ($combo.Deltas.ContainsKey($pf.Name)) { $sc += $pf.Weight * $combo.Deltas[$pf.Name] } }
    $combo | Add-Member -NotePropertyName Composite -NotePropertyValue ($sc / $wSum) -Force
}

$p2 = @{ Time = 0.0; Count = 0 }
if ($combos.Count -gt 0) {
    $p2 = Invoke-ComboPass -Prefix 'pass2' -ComboList $combos -TargetErr $Pass2Error -Title 'Passe 2'
} else {
    Write-Host "Passe 2 : rien a simmer, ton set equipe est deja le seul candidat." -ForegroundColor Yellow
}
foreach ($c in $combos) { Set-Composite $c }
$rankedAll = @($combos | Sort-Object -Property Composite -Descending)
$bestByProfile = @{}
foreach ($pf in $profiles) {
    $bestByProfile[$pf.Name] = $combos | Where-Object { $_.Deltas.ContainsKey($pf.Name) } | Sort-Object -Property @{Expression = { $_.Deltas[$pf.Name] }; Descending = $true} | Select-Object -First 1
}

# ----------------------------------------------------------------------------
# 8. Resultats passe 2 (ce que tu peux equiper des maintenant)
# ----------------------------------------------------------------------------
if (-not $DryRun -and $combos.Count -gt 0) {
    Write-Host ""
    Write-Host "=== Meilleur set par profil, avec ce que tu as (delta vs equipe) ===" -ForegroundColor Cyan
    foreach ($pf in $profiles) {
        $b = $bestByProfile[$pf.Name]
        if ($b) { Write-Host ("  {0,-14} {1,7}  {2}" -f $pf.Name, (Format-Pct $b.Deltas[$pf.Name] $true), $b.Diff) -ForegroundColor Green }
    }
    Write-Host ""
    Write-Host ("=== Classement global pondere (poids : {0}) ===" -f (($profiles | ForEach-Object { "$($_.Name)=$($_.Weight)" }) -join ', ')) -ForegroundColor Cyan
    $hdr = '{0,3}  {1,7}  ' -f '#', 'Global'
    foreach ($pf in $profiles) { $hdr += ('{0,9}  ' -f $pf.Name.Substring(0, [math]::Min(9, $pf.Name.Length))) }
    $hdr += 'Changements vs equipe'
    Write-Host $hdr -ForegroundColor White
    $rank = 0
    foreach ($c in $rankedAll) {
        $rank++
        if ($Top -gt 0 -and $rank -gt $Top) { break }
        $line = '{0,3}  {1,7}  ' -f $rank, (Format-Pct $c.Composite $true)
        foreach ($pf in $profiles) { $d = if ($c.Deltas.ContainsKey($pf.Name)) { Format-Pct $c.Deltas[$pf.Name] $true } else { '-' } ; $line += ('{0,9}  ' -f $d) }
        $line += $c.Diff
        Write-Host $line -ForegroundColor $(if ($c.Composite -gt 0) { 'Green' } else { 'Gray' })
    }
    $g = $rankedAll[0]
    $swapThreshold = [math]::Max(0.3, 2 * $Pass2Error)
    Write-Host ""
    Write-Host "=== Regret : si tu gardes le set global #1 partout, tu perds par profil ===" -ForegroundColor Cyan
    foreach ($pf in $profiles) {
        $b = $bestByProfile[$pf.Name]
        if (-not $b -or -not $g.Deltas.ContainsKey($pf.Name)) { continue }
        $regret = $b.Deltas[$pf.Name] - $g.Deltas[$pf.Name]
        $msg = '  {0,-14} {1,7}' -f $pf.Name, (Format-Pct (-$regret) $true)
        if ($regret -gt $swapThreshold -and $b.Name -ne $g.Name) { $msg += "   -> vaut le swap : $($b.Diff)" }
        Write-Host $msg -ForegroundColor $(if ($regret -gt 0.5) { 'DarkYellow' } else { 'DarkGray' })
    }
}

# ----------------------------------------------------------------------------
# 9. Passe 3 : table de loot inseree dans les meilleurs sets (droptimizer re-optimise)
# ----------------------------------------------------------------------------
$lootCombos = [System.Collections.Generic.List[object]]::new()
$lootReport = @()
$lootCands = @($cands | Where-Object { $_.IsLoot })
if ($lootCands.Count -gt 0) {
    if ($Pass3Error -le 0) { $Pass3Error = $Pass2Error }
    $lootKeep = @($lootCands | Where-Object { $_.Family -ne 'main_hand' -and $_.Family -ne 'off_hand' -and ($SkipPass1 -or -not $p1.ContainsKey($_.Key) -or (Get-MaxDelta $_.Key) -ge $PruneBelow) })
    $lootWep  = @($wepCombos | Where-Object { $_.LootCount -ge 1 -and $_.LootCount -le $MaxLootItems -and ($SkipPass1 -or -not $p1.ContainsKey($_.Key) -or (Get-MaxDelta $_.Key) -ge $PruneBelow) })
    $nDropped = $lootCands.Count - $lootKeep.Count - @($lootCands | Where-Object { $_.Family -eq 'main_hand' -or $_.Family -eq 'off_hand' }).Count

    # sets de base : equipe + top N global + top N par profil
    $baseSets = [ordered]@{}
    $eqPicks = [ordered]@{}
    foreach ($fam in $famOrder) { $eqPicks[$fam] = ($slotOptions[$fam] | Where-Object { $_.IsEquipped } | Select-Object -First 1) }
    $baseSets['EQ'] = $eqPicks
    $take = $(if ($LootBase -le 0) { [math]::Max(1, $combos.Count) } else { $LootBase })
    foreach ($c in ($rankedAll | Select-Object -First $take)) { $baseSets[$c.Name] = $c.Picks }
    foreach ($pf in $profiles) {
        foreach ($c in ($combos | Where-Object { $_.Deltas.ContainsKey($pf.Name) } | Sort-Object -Property @{Expression = { $_.Deltas[$pf.Name] }; Descending = $true} | Select-Object -First $take)) { $baseSets[$c.Name] = $c.Picks }
    }

    $xNo = 0; $rejL = 0
    foreach ($bsKey in @($baseSets.Keys)) {
        $bs = $baseSets[$bsKey]
        # insertions simples : famille -> option contenant 1 item de loot
        $inserts = @()
        foreach ($lc in $lootKeep) {
            if ($lc.Family -eq 'finger' -or $lc.Family -eq 'trinket') {
                $bp = $bs[$lc.Family]
                if ($bp) { foreach ($keepItem in @($bp.A, $bp.B)) { if ($keepItem.Id -ne $lc.Id) { $inserts += @{ $lc.Family = (New-Pair $lc $keepItem) } } } }
            } elseif ($armorFamilies -contains $lc.Family) {
                $inserts += @{ $lc.Family = $lc }
            }
        }
        foreach ($w in $lootWep) { if ($w.LootCount -eq 1) { $inserts += @{ 'weapon' = $w } } }
        $all = @($inserts)
        if ($MaxLootItems -ge 2) {
            for ($i = 0; $i -lt $inserts.Count; $i++) {
                for ($j = $i + 1; $j -lt $inserts.Count; $j++) {
                    $fi = @($inserts[$i].Keys)[0]; $fj = @($inserts[$j].Keys)[0]
                    if ($fi -ne $fj) { $all += ($inserts[$i] + $inserts[$j]) }
                }
            }
            foreach ($fam in @('finger', 'trinket')) {
                $lj = @($lootKeep | Where-Object { $_.Family -eq $fam })
                for ($i = 0; $i -lt $lj.Count; $i++) { for ($j = $i + 1; $j -lt $lj.Count; $j++) { if ($lj[$i].Id -ne $lj[$j].Id) { $all += @{ $fam = (New-Pair $lj[$i] $lj[$j]) } } } }
            }
            foreach ($w in $lootWep) { if ($w.LootCount -eq 2) { $all += @{ 'weapon' = $w } } }
        }
        foreach ($ins in $all) {
            $picks = [ordered]@{}
            foreach ($fam in $famOrder) { $picks[$fam] = $(if ($ins.ContainsKey($fam)) { $ins[$fam] } else { $bs[$fam] }) }
            $obj = Build-Combo $picks ("X{0:D5}" -f ($xNo + 1))
            if ($null -eq $obj) { continue }
            if ($obj -is [string]) { $rejL++; continue }
            if ($seenKeys.ContainsKey($obj.Key)) { continue }
            $seenKeys[$obj.Key] = $true
            $xNo++
            $lootCombos.Add($obj)
        }
    }

    Write-Host ""
    Write-Host ("=== Passe 3 : {0} items de loot ({1} ecartes en passe 1) inseres dans {2} sets de base -> {3} sets a simmer ({4} rejetes : tier/coffre) ===" -f ($lootKeep.Count + $lootWep.Count), $nDropped, $baseSets.Count, $lootCombos.Count, $rejL) -ForegroundColor Cyan
    if ($p2.Count -gt 0) {
        $tPer = $p2.Time / $p2.Count
        $est = $tPer * [math]::Pow(($Pass2Error / $Pass3Error), 2) * $lootCombos.Count * $profiles.Count
        Write-Host ("  Temps estime passe 3 : ~{0:hh\:mm\:ss}" -f [TimeSpan]::FromSeconds($est)) -ForegroundColor DarkGray
    }
    if ($lootCombos.Count -gt 0) {
        $p3 = Invoke-ComboPass -Prefix 'pass3' -ComboList $lootCombos -TargetErr $Pass3Error -Title 'Passe 3 loot'
        foreach ($c in $lootCombos) { Set-Composite $c }
    }

    if (-not $DryRun -and $lootCombos.Count -gt 0) {
        # reference "sans loot" = max(0, meilleur set possible) par profil et global
        $noLoot = @{}
        foreach ($pf in $profiles) { $b = $bestByProfile[$pf.Name]; $noLoot[$pf.Name] = [math]::Max(0.0, $(if ($b) { $b.Deltas[$pf.Name] } else { 0.0 })) }
        $noLoot['Composite'] = [math]::Max(0.0, $(if ($rankedAll.Count -gt 0) { $rankedAll[0].Composite } else { 0.0 }))

        # valeur "simple" (passe 1, un seul swap) par item : composite pondere
        function Get-SimpleComposite($lc) {
            $keysToUse = @()
            if ($lc.Family -eq 'main_hand' -or $lc.Family -eq 'off_hand') { $keysToUse = @($wepCombos | Where-Object { ($_.MH.Key -eq $lc.Key) -or ($_.OH -and $_.OH.Key -eq $lc.Key) } | ForEach-Object { $_.Key }) }
            else { $keysToUse = @($lc.Key) }
            $sc = 0.0
            foreach ($pf in $profiles) {
                $best = $null
                foreach ($k in $keysToUse) { if ($p1.ContainsKey($k) -and $p1[$k].ContainsKey($pf.Name)) { $v = $p1[$k][$pf.Name]; if ($null -eq $best -or $v -gt $best) { $best = $v } } }
                if ($null -ne $best) { $sc += $pf.Weight * $best }
            }
            return ($sc / $wSum)
        }

        $allLootItems = @($lootKeep) + @($lootCands | Where-Object { $_.Family -eq 'main_hand' -or $_.Family -eq 'off_hand' })
        foreach ($lc in $allLootItems) {
            $with = @($lootCombos | Where-Object { $_.Loot -eq 1 -and $_.LootKeys -contains $lc.Key })
            if ($with.Count -eq 0) { continue }
            $bestC = $with | Sort-Object -Property Composite -Descending | Select-Object -First 1
            $per = @{}
            foreach ($pf in $profiles) {
                $bw = $with | Where-Object { $_.Deltas.ContainsKey($pf.Name) } | Sort-Object -Property @{Expression = { $_.Deltas[$pf.Name] }; Descending = $true} | Select-Object -First 1
                $per[$pf.Name] = $(if ($bw) { $bw.Deltas[$pf.Name] - $noLoot[$pf.Name] } else { $null })
            }
            $lootReport += [pscustomobject]@{
                Item = $lc.Name; Slot = $lc.Family; Id = $lc.Id; Ilvl = $lc.Ilvl; Source = $lc.LootSource
                Real = ($bestC.Composite - $noLoot['Composite']); Simple = (Get-SimpleComposite $lc); Per = $per; Best = $bestC
            }
        }
        $lootReport = @($lootReport | Sort-Object -Property Real -Descending)

        Write-Host ""
        Write-Host "=== Droptimizer re-optimise : gain reel = meilleur set AVEC l'item - meilleur set SANS (global pondere) ===" -ForegroundColor Cyan
        Write-Host ("    reference sans loot : global {0}%" -f (Format-Pct $noLoot['Composite'] $true)) -ForegroundColor DarkGray
        $hdr = '{0,3}  {1,7}  {2,7}  ' -f '#', 'Reel', 'Simple'
        foreach ($pf in $profiles) { $hdr += ('{0,9}  ' -f $pf.Name.Substring(0, [math]::Min(9, $pf.Name.Length))) }
        $hdr += 'Item [slot] (source)'
        Write-Host $hdr -ForegroundColor White
        $rank = 0
        foreach ($r in $lootReport) {
            $rank++
            if ($Top -gt 0 -and $rank -gt $Top) { break }
            $line = '{0,3}  {1,7}  {2,7}  ' -f $rank, (Format-Pct $r.Real $true), (Format-Pct $r.Simple $true)
            foreach ($pf in $profiles) { $d = if ($null -ne $r.Per[$pf.Name]) { Format-Pct $r.Per[$pf.Name] $true } else { '-' } ; $line += ('{0,9}  ' -f $d) }
            $line += "$($r.Item) [$($r.Slot)]"
            if ($r.Source) { $line += " ($($r.Source))" }
            Write-Host $line -ForegroundColor $(if ($r.Real -gt 0) { 'Green' } else { 'Gray' })
            Write-Host ("{0,23}-> set : {1}" -f '', $r.Best.Diff) -ForegroundColor DarkGray
        }
        if ($lootReport.Count -gt $Top -and $Top -gt 0) { Write-Host ("... {0} autres dans loot_reopt.csv" -f ($lootReport.Count - $Top)) -ForegroundColor DarkGray }

        if ($MaxLootItems -ge 2) {
            $bestPerPair = @{}
            foreach ($c in ($lootCombos | Where-Object { $_.Loot -ge 2 })) {
                $pk = (($c.LootKeys | Sort-Object) -join '+')
                if (-not $bestPerPair.ContainsKey($pk) -or $c.Composite -gt $bestPerPair[$pk].Composite) { $bestPerPair[$pk] = $c }
            }
            $pairsL = @($bestPerPair.Values | Sort-Object -Property Composite -Descending | Select-Object -First $(if ($Top -gt 0) { $Top } else { 10 }))
            if ($pairsL.Count -gt 0) {
                Write-Host ""
                Write-Host "=== Meilleures combinaisons de 2 items de loot (gain reel global vs meilleur set sans loot) ===" -ForegroundColor Cyan
                foreach ($c in $pairsL) {
                    Write-Host ("  {0,7}  {1}" -f (Format-Pct ($c.Composite - $noLoot['Composite']) $true), ($c.LootNames -join ' + ')) -ForegroundColor $(if ($c.Composite -gt $noLoot['Composite']) { 'Green' } else { 'Gray' })
                    Write-Host ("{0,11}-> set : {1}" -f '', $c.Diff) -ForegroundColor DarkGray
                }
            }
        }

        $withSrc = @($lootReport | Where-Object { $_.Source })
        $nSrc = @($withSrc | ForEach-Object { $_.Source } | Sort-Object -Unique).Count
        if ($nSrc -ge 2) {
            Write-Host ""
            Write-Host "Expected Value par source (gain reel moyen, pertes comptees 0) :" -ForegroundColor White
            $groups = $withSrc | Group-Object -Property Source | ForEach-Object {
                $items = @($_.Group); $ev = 0.0
                foreach ($it in $items) { if ($it.Real -gt 0) { $ev += $it.Real } }
                $bestItem = $items | Sort-Object -Property Real -Descending | Select-Object -First 1
                [pscustomobject]@{ Source = $_.Name; EV = ($ev / $items.Count); Best = $bestItem.Real; BestItem = $bestItem.Item; Up = "$(@($items | Where-Object { $_.Real -gt 0 }).Count)/$($items.Count)" }
            } | Sort-Object -Property EV -Descending
            Write-Host ('  {0,-28} {1,7}  {2,7}  {3,-9} {4}' -f 'Source', 'EV%', 'Best%', 'Up/Items', 'Meilleur item') -ForegroundColor White
            foreach ($gr in $groups) { Write-Host ('  {0,-28} {1,7}  {2,7}  {3,-9} {4}' -f $gr.Source, (Format-Pct $gr.EV $true), (Format-Pct $gr.Best $true), $gr.Up, $gr.BestItem) }
        }

        # exports loot
        $rank = 0
        $exp = foreach ($r in $lootReport) {
            $rank++
            $o = [ordered]@{ rank = $rank; item = $r.Item; slot = $r.Slot; id = $r.Id; ilvl = $r.Ilvl; source = $r.Source; real_pct = [math]::Round($r.Real, 3); simple_pct = [math]::Round($r.Simple, 3) }
            foreach ($pf in $profiles) { $o[("real_" + $pf.Safe)] = $(if ($null -ne $r.Per[$pf.Name]) { [math]::Round($r.Per[$pf.Name], 3) } else { '' }) }
            $o['best_set'] = $r.Best.Name; $o['best_set_changes'] = $r.Best.Diff; $o['best_set_global_pct'] = [math]::Round($r.Best.Composite, 3)
            [pscustomobject]$o
        }
        $exp | Export-Csv -LiteralPath (Join-Path $OutDir 'loot_reopt.csv') -NoTypeInformation -Encoding UTF8
        $rank = 0
        $exp2 = foreach ($c in ($lootCombos | Sort-Object -Property Composite -Descending)) {
            $rank++
            $o = [ordered]@{ rank = $rank; combo = $c.Name; global_pct = [math]::Round($c.Composite, 3); loot = ($c.LootNames -join ' ; ') }
            foreach ($pf in $profiles) { $o[("delta_" + $pf.Safe)] = $(if ($c.Deltas.ContainsKey($pf.Name)) { [math]::Round($c.Deltas[$pf.Name], 3) } else { '' }) }
            $o['changes'] = $c.Diff; $o['gear_lines'] = ($c.Lines -join ' ')
            [pscustomobject]$o
        }
        $exp2 | Export-Csv -LiteralPath (Join-Path $OutDir 'combos_loot.csv') -NoTypeInformation -Encoding UTF8
    }
}
if ($DryRun) { Write-Host "DryRun termine : fichiers run.simc generes dans $OutDir" -ForegroundColor Yellow; return }

# ----------------------------------------------------------------------------
# 10. Exports communs
# ----------------------------------------------------------------------------
$rank = 0
$export = foreach ($c in $rankedAll) {
    $rank++
    $o = [ordered]@{ rank = $rank; combo = $c.Name; global_pct = [math]::Round($c.Composite, 3) }
    foreach ($pf in $profiles) { $o[("delta_" + $pf.Safe)] = $(if ($c.Deltas.ContainsKey($pf.Name)) { [math]::Round($c.Deltas[$pf.Name], 3) } else { '' }) }
    $o['tier_pieces'] = $c.Tier; $o['vault_items'] = $c.Vault; $o['changes'] = $c.Diff
    $o['gear_lines'] = ($c.Lines -join ' ')
    [pscustomobject]$o
}
if ($export) { $export | Export-Csv -LiteralPath (Join-Path $OutDir 'combos.csv') -NoTypeInformation -Encoding UTF8 }

$sbs = New-Object System.Text.StringBuilder
function Add-SetBlock([string]$title, $combo) {
    [void]$sbs.AppendLine("# ===== $title =====")
    if ($combo) { [void]$sbs.AppendLine("# changements : $($combo.Diff)") }
    $gear = [ordered]@{}
    foreach ($s in @('head', 'neck', 'shoulder', 'back', 'chest', 'wrist', 'hands', 'waist', 'legs', 'feet', 'finger1', 'finger2', 'trinket1', 'trinket2', 'main_hand', 'off_hand')) {
        if ($equipped.ContainsKey($s)) { $gear[$s] = $equipped[$s] }
    }
    if ($combo) {
        foreach ($gl in $combo.Lines) {
            if ($gl -match '^(\w+)=(.*)$') { $slot = $Matches[1]; $val = $Matches[2]; if ($val -eq '') { $gear.Remove($slot) } else { $gear[$slot] = $val } }
        }
    }
    foreach ($s in $gear.Keys) { [void]$sbs.AppendLine("$s=$($gear[$s])") }
    [void]$sbs.AppendLine('')
}
if ($rankedAll.Count -gt 0) { Add-SetBlock ("Global #1 (" + (Format-Pct $rankedAll[0].Composite $true) + "%)") $rankedAll[0] }
foreach ($pf in $profiles) { $b = $bestByProfile[$pf.Name]; if ($b) { Add-SetBlock ("Meilleur pour '" + $pf.Name + "' (" + (Format-Pct $b.Deltas[$pf.Name] $true) + "%)") $b } }
$k = 0
foreach ($r in $lootReport) { $k++; if ($k -gt 5) { break }; Add-SetBlock ("Si tu obtiens '" + $r.Item + "' : gain reel " + (Format-Pct $r.Real $true) + "% (set global " + (Format-Pct $r.Best.Composite $true) + "%)") $r.Best }
Write-Utf8NoBom (Join-Path $OutDir 'best_sets.simc') $sbs.ToString()

Write-Host ""
Write-Host "Fichiers : $(Join-Path $OutDir 'combos.csv')  (sets avec ce que tu as)" -ForegroundColor DarkGray
if ($lootReport.Count -gt 0) {
    Write-Host "          $(Join-Path $OutDir 'loot_reopt.csv')  (droptimizer re-optimise)" -ForegroundColor DarkGray
    Write-Host "          $(Join-Path $OutDir 'combos_loot.csv')  (tous les sets avec loot)" -ForegroundColor DarkGray
}
Write-Host "          $(Join-Path $OutDir 'best_sets.simc')  (gear complet des meilleurs sets)" -ForegroundColor DarkGray
Write-Host "          $OutDir\pass1_* pass2_* pass3_*  (run.simc, report.html, results.csv par profil)" -ForegroundColor DarkGray
Write-Host "Rappel : compare les deltas a la colonne err_pct des csv ; en dessous, ce n'est pas significatif." -ForegroundColor DarkGray
