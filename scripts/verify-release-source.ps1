#Requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$DispatchRef,

    [Parameter(Mandatory)]
    [string]$WorkflowSha,

    [Parameter(Mandatory)]
    [string]$SourceSha,

    [Parameter(Mandatory)]
    [string]$MasterSha,

    [Parameter(Mandatory)]
    [ValidatePattern("\A[^/]+/[^/]+\z")]
    [string]$Repository,

    [Parameter()]
    [string]$WorkflowId = "compatibility.yml",

    [Parameter()]
    [string]$ApiBaseUrl = "https://api.github.com",

    [Parameter()]
    [string]$Token = $env:GITHUB_TOKEN,

    [Parameter()]
    [string]$RunsJsonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-FullSha {
    param([string]$Name, [string]$Value)
    if ($Value -cnotmatch '\A[0-9a-f]{40}\z') {
        throw "$Name must be a normalized 40-character lowercase SHA."
    }
}

function Invoke-GitHubApi {
    param([Parameter(Mandatory)] [string]$Path)
    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "GITHUB_TOKEN is required for release provenance verification."
    }
    $uri = $ApiBaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
    try {
        return Invoke-RestMethod -Uri $uri -Headers @{
            Authorization = "Bearer $Token"
            Accept = "application/vnd.github+json"
            "X-GitHub-Api-Version" = "2022-11-28"
        } -Method Get
    }
    catch {
        throw "GitHub provenance API request failed."
    }
}

Assert-FullSha "WorkflowSha" $WorkflowSha
Assert-FullSha "SourceSha" $SourceSha
Assert-FullSha "MasterSha" $MasterSha
if ($DispatchRef -cne "refs/heads/master") {
    throw "Release workflow must be dispatched from refs/heads/master."
}
if ($WorkflowSha -cne $SourceSha -or $MasterSha -cne $SourceSha) {
    throw "Workflow, input, and current master SHA must be identical."
}
if ($WorkflowId -cne "compatibility.yml") {
    throw "Unexpected compatibility workflow ID."
}

if ($RunsJsonPath) {
    if (-not (Test-Path -LiteralPath $RunsJsonPath -PathType Leaf)) {
        throw "Synthetic run payload is unavailable."
    }
    $payload = Get-Content -LiteralPath $RunsJsonPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -AsHashtable -Depth 100
    if (-not $payload.Contains("workflow_runs")) {
        throw "Synthetic run payload is incomplete."
    }
    $runs = @($payload.workflow_runs)
}
else {
    $runs = [Collections.Generic.List[object]]::new()
    $page = 1
    do {
        $path = (
            "repos/$Repository/actions/workflows/$WorkflowId/runs" +
            "?branch=master&event=push&status=completed&per_page=100&page=$page"
        )
        $payload = Invoke-GitHubApi -Path $path
        if ($null -eq $payload.workflow_runs -or $null -eq $payload.total_count) {
            throw "GitHub workflow run response is incomplete."
        }
        $pageRuns = @($payload.workflow_runs)
        if ($pageRuns.Count -eq 0 -and $runs.Count -lt [int]$payload.total_count) {
            throw "GitHub workflow run pagination ended before total_count."
        }
        foreach ($run in $pageRuns) { $runs.Add($run) }
        $page++
    } while ($runs.Count -lt [int]$payload.total_count)
}

$matching = @(
    $runs | Where-Object {
        [string]$_.head_sha -ceq $SourceSha -and
        [string]$_.event -ceq "push" -and
        [string]$_.head_branch -ceq "master" -and
        [string]$_.status -ceq "completed" -and
        [string]$_.conclusion -ceq "success"
    }
)
if ($matching.Count -ne 1) {
    throw "Expected exactly one successful master compatibility run for SourceSha."
}
$run = $matching[0]
if ($RunsJsonPath) {
    $jobs = @($run.jobs)
}
else {
    $jobsPayload = Invoke-GitHubApi -Path (
        "repos/$Repository/actions/runs/$($run.id)/jobs?per_page=100"
    )
    if ($null -eq $jobsPayload.jobs -or [int]$jobsPayload.total_count -gt 100) {
        throw "GitHub job response is missing or requires unsupported pagination."
    }
    $jobs = @($jobsPayload.jobs)
}
$required = @(
    $jobs | Where-Object {
        [string]$_.name -ceq "master-required" -and
        [string]$_.status -ceq "completed" -and
        [string]$_.conclusion -ceq "success"
    }
)
if ($required.Count -ne 1) {
    throw "The unique master compatibility run lacks a successful master-required job."
}

Write-Output $SourceSha
