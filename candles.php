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

$from = parse_time_param($start);
$to = parse_time_param($end);
if (($start !== null || $end !== null) && ($from === null || $to === null)) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing or invalid start/end time.']);
    exit;
}

$query_string = $_GET['query'] ?? '';
$query_string = $query_string !== '' ? $query_string : 'tt:' . strtolower($ticker);
$limit = isset($_GET['n']) ? (int)$_GET['n'] : 200;
$limit = max(1, min($limit, 200));
$last = $_GET['last'] ?? null;

$query = [
    'q' => $query_string,
    'n' => $limit,
];
if ($last !== null && $last !== '') {
    $query['last'] = $last;
}

$url = 'https://api.tickertick.com/feed?' . http_build_query($query);
$response = @file_get_contents($url);
if ($response === false) {
    http_response_code(502);
    echo json_encode(['error' => 'Failed to fetch data from TickerTick.']);
    exit;
}

$payload = json_decode($response, true);
if (!is_array($payload)) {
    echo json_encode(['stories' => []]);
    exit;
}

$stories = $payload['stories'] ?? [];
if (!is_array($stories)) {
    $stories = [];
}

if ($from !== null && $to !== null) {
    $from_ms = $from * 1000;
    $to_ms = $to * 1000;
    $stories = array_values(array_filter($stories, static function ($story) use ($from_ms, $to_ms) {
        if (!is_array($story) || !isset($story['time'])) {
            return false;
        }
        $time = (int)$story['time'];
        return $time >= $from_ms && $time <= $to_ms;
    }));
}

$payload['stories'] = $stories;
echo json_encode($payload);
