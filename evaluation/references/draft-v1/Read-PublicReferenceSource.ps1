# Read-only reference preparation, independent of the application importer/index.
# Dot-source this file; it has no side effects until Read-PublicReferenceSource is called.
function Read-PublicReferenceSource {
    param(
        [string]$ArchivePath = (Join-Path $PSScriptRoot '../data/raw/stapferappdb_final.sql.zip'),
        [int[]]$AnswerTranscriptionIds = @(),
        [switch]$MetadataOnly
    )
    $expectedHash = '68eba6c4a7cc13eb3e0b6239b00a6ee21e2e0996a24de69224c3915480941c97'
    if ((Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
        throw 'Reference source differs from the pinned archive.'
    }
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ArchivePath))
    try {
        $entry = $archive.GetEntry('stapferappdb_final_10.5.16.sql')
        if ($null -eq $entry) { throw 'Pinned SQL member is missing.' }
        # Latin1 is a reversible byte container here, never a text-encoding inference.
        $reader = [IO.StreamReader]::new($entry.Open(), [Text.Encoding]::Latin1, $false)
        try { $byteView = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $archive.Dispose() }
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    function Decode-PublicToken([string]$token) {
        if ($token -eq 'NULL') { return $null }
        if ($token[0] -ne "'") { return [int]::Parse($token, [Globalization.CultureInfo]::InvariantCulture) }
        $inner = $token.Substring(1, $token.Length - 2)
        if (-not $inner.Contains('\') -and -not $inner.Contains("''")) {
            return $utf8.GetString([Text.Encoding]::Latin1.GetBytes($inner))
        }
        $decoded = [Text.StringBuilder]::new()
        for ($position = 0; $position -lt $inner.Length; $position++) {
            $character = $inner[$position]
            if ($character -eq '\') {
                $position++
                if ($position -ge $inner.Length) { throw 'Truncated escape in public source.' }
                $escaped = $inner[$position]
                $character = switch ($escaped) {
                    '0' { [char]0 } 'b' { [char]8 } 'n' { [char]10 }
                    'r' { [char]13 } 't' { [char]9 } 'Z' { [char]26 }
                    "'" { [char]39 } '"' { [char]34 } '\' { [char]92 }
                    default { throw 'Unsupported escape in public source.' }
                }
            } elseif ($character -eq "'" -and $position + 1 -lt $inner.Length -and $inner[$position + 1] -eq "'") {
                $position++
            }
            [void]$decoded.Append($character)
        }
        return $utf8.GetString([Text.Encoding]::Latin1.GetBytes($decoded.ToString()))
    }
    $specifications = [ordered]@{
        t_frage = @{count=60; width=4; fields=[ordered]@{id=0; text=1; code=2; french=3}}
        t_transkription = @{count=2250; width=17; fields=[ordered]@{id=0; archive=1; location=2; header=4; facsimile=10; release=13; multiple_schools=15}}
        t_schule = @{count=3229; width=16; fields=[ordered]@{id=0; name=7; transcription_id=10; place_id=15}}
        t_antwort = @{count=92524; width=8; fields=[ordered]@{id=0; text=4; question_id=5; transcription_id=6; assignment_raw=7}}
    }
    $stringToken = "'(?:\\[\s\S]|''|[^'\\])*'"
    $token = "(?:$stringToken|NULL|0x[0-9A-Fa-f]+|[-+]?\d+(?:\.\d+)?)"
    $wanted = [Collections.Generic.HashSet[int]]::new($AnswerTranscriptionIds)
    $result = [ordered]@{source_sha256=$expectedHash; sql_executed=$false; binary_fields_decoded=$false; source_row_counts=[ordered]@{}; answer_profiles=@{}}
    foreach ($table in $specifications.Keys) {
        if ($MetadataOnly -and $table -eq 't_antwort') { continue }
        $rows = [Collections.Generic.List[object]]::new()
        $sourceRows = 0
        $columnPatterns = for ($column=0; $column -lt $specifications[$table].width; $column++) {
            '(?<c' + $column + '>' + $token + ')'
        }
        $rowPattern = [regex]::new('\(' + ($columnPatterns -join ',') + '\)(?:,|;)',
            [Text.RegularExpressions.RegexOptions]::NonBacktracking,
            [TimeSpan]::FromSeconds(30))
        $insertPattern = '(?m)^INSERT INTO `' + $table + '` VALUES (?<values>[^\r\n]*);\r?$'
        foreach ($insert in [regex]::Matches($byteView, $insertPattern)) {
            $values = $insert.Groups['values'].Value + ';'
            $offset = 0
            foreach ($row in $rowPattern.Matches($values)) {
                if ($row.Index -ne $offset) { throw "Unparsed tuple in $table at $offset" }
                $sourceRows++
                $offset += $row.Length
                if ($table -eq 't_antwort') {
                    $answerDocumentId = [int]::Parse($row.Groups['c6'].Value)
                    if (-not $result.answer_profiles.ContainsKey($answerDocumentId)) {
                        $result.answer_profiles[$answerDocumentId] = [PSCustomObject]@{
                            answer_count=0; has_null=$false; has_markup=$false; has_free_text=$false; max_raw_token_bytes=0
                        }
                    }
                    $profile = $result.answer_profiles[$answerDocumentId]
                    $rawText = $row.Groups['c4'].Value
                    $profile.answer_count++
                    $profile.has_null = $profile.has_null -or $rawText -eq 'NULL'
                    $profile.has_markup = $profile.has_markup -or $rawText.Contains('@') -or $rawText.Contains('$')
                    $profile.has_free_text = $profile.has_free_text -or [int]::Parse($row.Groups['c5'].Value) -ge 57
                    $profile.max_raw_token_bytes = [Math]::Max($profile.max_raw_token_bytes,$rawText.Length)
                    if ($wanted.Count -gt 0 -and -not $wanted.Contains($answerDocumentId)) { continue }
                }
                $projected = [ordered]@{}
                foreach ($name in $specifications[$table].fields.Keys) {
                    $projected[$name] = Decode-PublicToken $row.Groups[('c' + $specifications[$table].fields[$name])].Value
                }
                $rows.Add([PSCustomObject]$projected)
            }
            if ($offset -ne $values.Length) { throw "Unparsed final tuple in $table" }
        }
        if ($sourceRows -ne $specifications[$table].count) { throw "Unexpected reference row count in $table" }
        $result.source_row_counts[$table] = $sourceRows
        $result[$table] = $rows
    }
    if (@($result.t_transkription | Where-Object { $_.release -ne 'Internet' }).Count) {
        throw 'An unadmitted release state needs explicit review.'
    }
    return [PSCustomObject]$result
}
