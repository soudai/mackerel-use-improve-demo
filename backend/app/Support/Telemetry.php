<?php

namespace App\Support;

use OpenTelemetry\API\Globals;
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
}
