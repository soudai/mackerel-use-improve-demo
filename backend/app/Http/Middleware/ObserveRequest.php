<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use OpenTelemetry\API\Globals;
use OpenTelemetry\API\Trace\Propagation\TraceContextPropagator;
use OpenTelemetry\API\Trace\SpanKind;
use OpenTelemetry\API\Trace\StatusCode;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\HttpKernel\Exception\HttpExceptionInterface;
use Throwable;

final class ObserveRequest
{
    public function handle(Request $request, Closure $next): Response
    {
        $start = hrtime(true);
        $request->attributes->set('demo.query_count', 0);
        $carrier = [];
        foreach (['traceparent', 'tracestate'] as $header) {
            if ($request->hasHeader($header)) {
                $carrier[$header] = $request->header($header);
            }
        }
        $parent = TraceContextPropagator::getInstance()->extract($carrier);
        $span = Globals::tracerProvider()->getTracer('mackerel-demo')->spanBuilder($request->method().' request')
            ->setParent($parent)->setSpanKind(SpanKind::KIND_SERVER)
            ->setAttributes(['http.request.method' => $request->method(), 'url.scheme' => $request->getScheme()])
            ->startSpan();
        $scope = $span->activate();
        $status = 500;

        try {
            $response = $next($request);
            $status = $response->getStatusCode();
            $response->headers->set('X-Trace-Id', $span->getContext()->getTraceId());
            $response->headers->set('X-App-Revision', config('demo.revision'));
            $response->headers->set('X-Query-Count', (string) $request->attributes->get('demo.query_count', 0));
            $response->headers->set('X-Response-Time-Ms', (string) round((hrtime(true) - $start) / 1e6, 3));

            return $response;
        } catch (Throwable $exception) {
            $status = $exception instanceof HttpExceptionInterface ? $exception->getStatusCode() : 500;
            if ($status >= 500) {
                $span->recordException($exception);
            }
            throw $exception;
        } finally {
            $route = '/'.ltrim($request->route()?->uri() ?? 'unmatched', '/');
            $queryCount = (int) $request->attributes->get('demo.query_count', 0);
            $span->updateName($request->method().' '.$route);
            $span->setAttributes(['http.route' => $route, 'http.response.status_code' => $status, 'demo.sql.count' => $queryCount]);
            if ($status >= 500) {
                $span->setStatus(StatusCode::STATUS_ERROR);
            }
            $entry = [
                'timestamp' => now('UTC')->format('Y-m-d\TH:i:s.u\Z'),
                'level' => $status >= 500 ? 'ERROR' : 'INFO',
                'method' => $request->method(), 'route' => $route, 'status' => $status,
                'request_time' => round((hrtime(true) - $start) / 1e9, 6),
                'query_count' => $queryCount, 'peak_memory_bytes' => memory_get_peak_usage(true),
                'trace_id' => $span->getContext()->getTraceId(),
                'span_id' => $span->getContext()->getSpanId(),
                'service_name' => config('demo.service_name'),
                'service_version' => config('demo.revision'), 'environment' => config('demo.environment'),
            ];
            file_put_contents(storage_path('logs/access.jsonl'), json_encode($entry, JSON_THROW_ON_ERROR).PHP_EOL, FILE_APPEND | LOCK_EX);
            $scope->detach();
            $span->end();
        }
    }
}
