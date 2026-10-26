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
        $rows = Telemetry::span('reports.fetch_rows', fn () => DB::table('order_items')
            ->join('orders', 'orders.id', '=', 'order_items.order_id')
            ->where('orders.status', 'paid')
            ->where('orders.created_at', '>=', $from.' 00:00:00')
            ->where('orders.created_at', '<', $until.' 00:00:00')
            ->selectRaw('DATE(orders.created_at) AS sales_date, COUNT(DISTINCT orders.id) AS orders_count, SUM(order_items.quantity) AS items_quantity, SUM(CAST(order_items.quantity AS BIGINT) * order_items.unit_price_cents) AS gross_cents')
            ->groupByRaw('DATE(orders.created_at)')
            ->orderBy('sales_date')
            ->get());

        return Telemetry::span('reports.aggregate', function () use ($rows, $from, $to): array {
            $orders = 0;
            $quantity = 0;
            $gross = 0;
            $daily = [];
            foreach ($rows as $row) {
                $orders += (int) $row->orders_count;
                $quantity += (int) $row->items_quantity;
                $gross += (int) $row->gross_cents;
                $daily[$row->sales_date] = (int) $row->gross_cents;
            }

            return ['from' => $from, 'to' => $to, 'orders_count' => $orders, 'items_quantity' => $quantity, 'gross_cents' => $gross, 'by_date' => $daily];
        }, ['demo.fetched_rows' => $rows->count()]);
    }
}
