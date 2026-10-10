<?php
// Kurage 法案AIインタビュー (khouan) — kurage.exbridge.jp 上の公開入口。
// 当社サーバーの FastAPI（:18395）への透過プロキシ。PATH_INFO で中継する。
// バックエンドと合言葉は同じディレクトリの khouan_config.php で定義する（リポジトリには含めない）
//   <?php define('KHOUAN_BACKEND', 'http://あなたのサーバー:18395'); define('KHOUAN_RELAY_TOKEN', '…');
//
// - 回数の上限は接続元の IP（のハッシュ）で数える。利用者が送ってきた X-Forwarded-For は信じず、
//   REMOTE_ADDR だけを合言葉つきで渡す（合言葉が無い直接の接続では、バックエンドは X-Forwarded-For を使わない）。
// - AI の応答（意見のまとめ）に20秒ほどかかるので、待ち時間は長めにとる。
$__cfg = __DIR__ . '/khouan_config.php';
if (is_file($__cfg)) { require_once $__cfg; }
$BACKEND = defined('KHOUAN_BACKEND') ? KHOUAN_BACKEND : 'http://127.0.0.1:18395';

if (!isset($_SERVER['PATH_INFO']) || $_SERVER['PATH_INFO'] === '') {
    if (substr($_SERVER['REQUEST_URI'], -1) !== '/' && strpos($_SERVER['REQUEST_URI'], '?') === false) {
        header('Location: /khouan.php/', true, 302); exit;
    }
}
$path = isset($_SERVER['PATH_INFO']) ? $_SERVER['PATH_INFO'] : '/';
$qs = isset($_SERVER['QUERY_STRING']) && $_SERVER['QUERY_STRING'] !== '' ? '?' . $_SERVER['QUERY_STRING'] : '';

$ch = curl_init($BACKEND . $path . $qs);
$headers = array('X-Forwarded-Proto: https', 'X-Forwarded-Host: kurage.exbridge.jp');
if (!empty($_SERVER['REMOTE_ADDR'])) { $headers[] = 'X-Forwarded-For: ' . $_SERVER['REMOTE_ADDR']; }
if (defined('KHOUAN_RELAY_TOKEN')) { $headers[] = 'X-Khouan-Relay: ' . KHOUAN_RELAY_TOKEN; }
if (!empty($_SERVER['CONTENT_TYPE'])) { $headers[] = 'Content-Type: ' . $_SERVER['CONTENT_TYPE']; }

curl_setopt_array($ch, array(
    CURLOPT_CUSTOMREQUEST => $_SERVER['REQUEST_METHOD'],
    CURLOPT_RETURNTRANSFER => true, CURLOPT_HEADER => true,
    CURLOPT_HTTPHEADER => $headers, CURLOPT_ENCODING => '',
    CURLOPT_CONNECTTIMEOUT => 10, CURLOPT_TIMEOUT => 180, CURLOPT_FOLLOWLOCATION => false,
));
if ($_SERVER['REQUEST_METHOD'] !== 'GET' && $_SERVER['REQUEST_METHOD'] !== 'HEAD') {
    $in = file_get_contents('php://input', false, null, 0, 20000);   // 1回の答えは600字。大きな本文は送らない
    curl_setopt($ch, CURLOPT_POSTFIELDS, $in);
}
$res = curl_exec($ch);
if ($res === false) {
    http_response_code(503); header('Content-Type: text/plain; charset=utf-8'); header('Retry-After: 120');
    echo '法案AIインタビューのサーバーに接続できません。時間をおいてからもう一度お試しください。'; exit;
}
$status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$hsize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
curl_close($ch);
http_response_code($status);

$isHtml = false;
foreach (explode("\r\n", substr($res, 0, $hsize)) as $h) {
    if (stripos($h, 'Content-Type:') === 0) {
        header($h);
        if (stripos($h, 'text/html') !== false) { $isHtml = true; }
    } elseif (stripos($h, 'Cache-Control:') === 0 || stripos($h, 'Location:') === 0 || stripos($h, 'Access-Control-Allow-Origin:') === 0) {
        header($h);
    }
}
$body = substr($res, $hsize);
// アクセス計測と共通ヘッダー（partner-bar.js）は当社の公開先でだけ入れる。導入先のサーバーから当社へ通信させない
if ($isHtml && isset($_SERVER['HTTP_HOST']) && $_SERVER['HTTP_HOST'] === 'kurage.exbridge.jp') {
    $tag = '<script>(function(){var s=document.createElement("script");s.src="https://kurage.exbridge.jp/simpletrack.php?url="+encodeURIComponent(location.href)+"&ref="+encodeURIComponent(document.referrer);s.async=true;document.head.appendChild(s)})();</script>';
    $body = str_replace('</head>', $tag . '<script src="https://kurage.exbridge.jp/partner-bar.js" defer></script></head>', $body);
}
echo $body;
