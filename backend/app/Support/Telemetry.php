<?php

namespace App\Support;

use Illuminate\Database\Events\QueryExecuted;
use OpenTelemetry\API\Common\Time\Clock;
use OpenTelemetry\API\Globals;
use OpenTelemetry\API\Trace\SpanKind;
use OpenTelemetry\API\Trace\StatusCode;
use Throwable;

final class Telemetry
{
    public static function span(string $name, callable $callback, array $attributes = []): mixed
    {
        $frames = debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS, 2);
        $caller = $frames[1] ?? [];
        $location = $frames[0] ?? [];
        $file = $location['file'] ?? '';
        $attributes += [
            'code.file.path' => str_replace(base_path().DIRECTORY_SEPARATOR, '', $file),
            'code.line.number' => $location['line'] ?? 0,
            'code.function.name' => ($caller['class'] ?? '').($caller['type'] ?? '').($caller['function'] ?? $name),
        ];
        $span = Globals::tracerProvider()->getTracer('mackerel-demo')->spanBuilder($name)
            ->setAttributes($attributes)->startSpan();
        $scope = $span->activate();

        try {
            return $callback();
        } catch (Throwable $exception) {
            $span->recordException($exception);
            $span->setStatus(StatusCode::STATUS_ERROR, $exception->getMessage());
            throw $exception;
        } finally {
            $scope->detach();
            $span->end();
        }
    }

    /** Record Laravel's observed prepare/execute/fetch duration, without query bindings. */
    public static function query(QueryExecuted $query): void
    {
        if ($query->time === null || ! is_finite((float) $query->time) || $query->time < 0) {
            return;
        }

        $end = Clock::getDefault()->now();
        $duration = (int) round($query->time * 1_000_000);
        $operation = strtoupper(strtok(ltrim($query->sql), " \t\n"));
        $driver = $query->connection->getDriverName();
        $attributes = [
            'db.system.name' => $driver === 'pgsql' ? 'postgresql' : $driver,
            'db.namespace' => $query->connection->getDatabaseName(),
            'db.operation.name' => $operation,
            'db.query.text' => $query->sql,
            'demo.db.execution' => true,
            'demo.db.duration_source' => 'laravel.query_executed',
        ];

        foreach (debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS, 40) as $frame) {
            $file = $frame['file'] ?? '';
            if (str_starts_with($file, app_path().DIRECTORY_SEPARATOR)
                && $file !== __FILE__
                && ! str_contains($file, DIRECTORY_SEPARATOR.'Providers'.DIRECTORY_SEPARATOR)) {
                $attributes['code.file.path'] = substr($file, strlen(base_path()) + 1);
                $attributes['code.line.number'] = $frame['line'] ?? 0;
                break;
            }
        }

        $span = Globals::tracerProvider()->getTracer('mackerel-demo')->spanBuilder($operation.' database')
            ->setSpanKind(SpanKind::KIND_CLIENT)
            ->setStartTimestamp($end - $duration)
            ->setAttributes($attributes)
            ->startSpan();
        $span->end($end);
    }
}
