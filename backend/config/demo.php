<?php

return [
    'shipping_url' => env('SHIPPING_URL', 'http://shipping:8081'),
    'shipping_delay_ms' => (int) env('SHIPPING_DELAY_MS', 300),
    'revision' => env('APP_REVISION', 'unversioned'),
    'environment' => env('OTEL_DEPLOYMENT_ENVIRONMENT', 'development'),
    'service_name' => env('OTEL_SERVICE_NAME', 'mackerel-improve-demo'),
];
