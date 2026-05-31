<?php
/**
 * Proxy de busca — Douglas Rosa · Extrator de Leilão
 * Faz o fetch de qualquer site de leilão com IP do servidor de hospedagem.
 * Faça upload deste arquivo junto com o trello-leilao.html no cPanel.
 */

header('Access-Control-Allow-Origin: *');
header('Content-Type: text/html; charset=utf-8');

$url = $_GET['url'] ?? '';

// Validações básicas
if (!$url) {
    http_response_code(400);
    exit('Parâmetro url não informado');
}
if (!filter_var($url, FILTER_VALIDATE_URL)) {
    http_response_code(400);
    exit('URL inválida');
}
if (!preg_match('/^https?:\/\//i', $url)) {
    http_response_code(400);
    exit('Apenas URLs http/https são permitidas');
}

// Busca com cURL (disponível em todos os cPanels)
$ch = curl_init();
curl_setopt_array($ch, [
    CURLOPT_URL            => $url,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_FOLLOWLOCATION => true,
    CURLOPT_MAXREDIRS      => 5,
    CURLOPT_TIMEOUT        => 20,
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_SSL_VERIFYHOST => false,
    CURLOPT_ENCODING       => 'gzip, deflate',
    CURLOPT_HTTPHEADER     => [
        'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer: https://www.google.com.br/',
        'Cache-Control: max-age=0',
        'DNT: 1',
    ],
]);

$html     = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$erro     = curl_error($ch);
curl_close($ch);

if ($html === false || $erro) {
    http_response_code(502);
    exit('Erro cURL: ' . $erro);
}
if ($httpCode >= 400) {
    http_response_code($httpCode);
    exit('Site retornou erro ' . $httpCode);
}

echo $html;
