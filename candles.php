<?php
declare(strict_types=1);

header('Content-Type: application/json');

$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$path = rtrim($path ?? '', '/');
$segments = explode('/', ltrim($path, '/'));

$ticker = '';
if (count($segments) >= 3 && $segments[0] === 'products' && $segments[2] === 'candles') {
    $ticker = $segments[1];
} elseif (!empty($_GET['ticker'])) {
    $ticker = $_GET['ticker'];
}

if ($ticker === '') {
    http_response_code(400);
    echo json_encode(['error' => 'Missing ticker. Use /products/{ticker}/candles']);
    exit;
}

$start = $_GET['start'] ?? null;
$end = $_GET['end'] ?? null;

function parse_time_param($value): ?int
{
    if ($value === null || $value === '') {
        return null;
    }
    if (is_numeric($value)) {
        return (int)$value;
    }
    $timestamp = strtotime($value);
    if ($timestamp === false) {
        return null;
    }
    return $timestamp;
}

function resolve_api_key(): ?string
{
    if (!empty($_GET['token'])) {
        return trim((string)$_GET['token']);
    }

    if (function_exists('getallheaders')) {
        $headers = getallheaders();
        if (!empty($headers['X-Massive-Token'])) {
            return trim((string)$headers['X-Massive-Token']);
        }
        if (!empty($headers['Authorization'])) {
            $auth = trim((string)$headers['Authorization']);
            if (stripos($auth, 'Bearer ') === 0) {
                return trim(substr($auth, 7));
            }
        }
    }

    $env_key = getenv('MASSIVE_API_KEY');
    if ($env_key !== false && $env_key !== '') {
        return trim((string)$env_key);
    }

    return null;
}

function resolve_granularity(): int
{
    $granularity = isset($_GET['granularity']) ? (int)$_GET['granularity'] : 900;
    return max(1, $granularity);
}

function map_granularity(int $granularity): array
{
    if ($granularity % 86400 === 0) {
        return [$granularity / 86400, 'day'];
    }
    if ($granularity % 3600 === 0) {
        return [$granularity / 3600, 'hour'];
    }
    if ($granularity % 60 === 0) {
        return [$granularity / 60, 'minute'];
    }

    return [$granularity, 'second'];
}

$api_key = resolve_api_key();
$granularity = resolve_granularity();
[$multiplier, $timespan] = map_granularity($granularity);

$from = parse_time_param($start);
$to = parse_time_param($end);
if (($start !== null || $end !== null) && ($from === null || $to === null)) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing or invalid start/end time.']);
    exit;
}

if ($from === null || $to === null) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing start/end time.']);
    exit;
}

$from_ms = $from * 1000;
$to_ms = $to * 1000;
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : null;
if ($limit !== null) {
    $limit = max(1, min($limit, 50000));
}

$path = sprintf(
    'https://api.massive.com/v2/aggs/ticker/%s/range/%d/%s/%d/%d',
    rawurlencode($ticker),
    $multiplier,
    $timespan,
    $from_ms,
    $to_ms
);

$query = [
    'adjusted' => 'true',
    'sort' => 'desc',
];
if ($limit !== null) {
    $query['limit'] = $limit;
}
if ($api_key !== null && $api_key !== '') {
    $query['apiKey'] = $api_key;
}

$context = stream_context_create([
    'http' => [
        'method' => 'GET',
        'header' => "Accept: application/json\r\n",
        'timeout' => 20,
    ],
]);

$url = $path . '?' . http_build_query($query);
$response = @file_get_contents($url, false, $context);
if ($response === false) {
    http_response_code(502);
    echo json_encode(['error' => 'Failed to fetch data from Massive.']);
    exit;
}

$payload = json_decode($response, true);
if (!is_array($payload)) {
    echo json_encode([]);
    exit;
}

$results = $payload['results'] ?? [];
if (!is_array($results)) {
    $results = [];
}

$candles = [];
foreach ($results as $bar) {
    if (!is_array($bar) || !isset($bar['t'], $bar['o'], $bar['h'], $bar['l'], $bar['c'], $bar['v'])) {
        continue;
    }
    $candles[] = [
        (int)floor(((int)$bar['t']) / 1000),
        (float)$bar['l'],
        (float)$bar['h'],
        (float)$bar['o'],
        (float)$bar['c'],
        (float)$bar['v'],
    ];
}

echo json_encode($candles);
