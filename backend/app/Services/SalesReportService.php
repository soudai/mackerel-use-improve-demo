<?php

namespace App\Services;

use App\Support\Telemetry;
use Carbon\CarbonImmutable;
use Illuminate\Support\Facades\DB;

class SalesReportService
{
    public function generate(string $from, string $to): array
    {
        $until = CarbonImmutable::parse($to, 'UTC')->addDay()->format('Y-m-d');
        // Baseline: transfer every matching detail row, then aggregate in PHP.
        $rows = Telemetry::span('reports.fetch_rows', fn () => DB::table('order_items')
            ->join('orders', 'orders.id', '=', 'order_items.order_id')
            ->where('orders.status', 'paid')
            ->where('orders.created_at', '>=', $from.' 00:00:00')
            ->where('orders.created_at', '<', $until.' 00:00:00')
            ->select('orders.id as order_id', 'orders.created_at', 'order_items.quantity', 'order_items.unit_price_cents')
            ->get());

        return Telemetry::span('reports.aggregate', function () use ($rows, $from, $to): array {
            $orders = [];
            $quantity = 0;
            $gross = 0;
            $daily = [];
            foreach ($rows as $row) {
                $orders[$row->order_id] = true;
                $amount = (int) $row->quantity * (int) $row->unit_price_cents;
                $quantity += (int) $row->quantity;
                $gross += $amount;
                $date = substr($row->created_at, 0, 10);
                $daily[$date] = ($daily[$date] ?? 0) + $amount;
            }
            ksort($daily);

            return [
                'from' => $from,
                'to' => $to,
                'orders_count' => count($orders),
                'items_quantity' => $quantity,
                'gross_cents' => $gross,
                'by_date' => $daily,
            ];
        }, ['demo.fetched_rows' => $rows->count()]);
    }
}
