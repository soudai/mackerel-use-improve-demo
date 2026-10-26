<?php

namespace App\Http\Controllers;

use App\Models\Order;
use App\Support\Telemetry;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class OrderController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $input = $request->validate(['limit' => 'sometimes|integer|min:1|max:100']);

        return Telemetry::span('orders.list', function () use ($input): JsonResponse {
            $orders = Order::query()->orderByDesc('id')->limit($input['limit'] ?? 50)->get();
            $data = $orders->map(fn (Order $order) => [
                'id' => $order->id,
                'customer' => $order->customer->name,
                'status' => $order->status,
                'total_cents' => $order->total_cents,
                'created_at' => $order->created_at->toIso8601String(),
            ]);

            return response()->json(['data' => $data]);
        });
    }

    public function search(Request $request): JsonResponse
    {
        $request->mergeIfMissing(['from' => '2026-01-01', 'to' => '2026-01-02']);
        $input = $request->validate([
            'status' => 'sometimes|in:paid,pending,cancelled',
            'from' => 'sometimes|date_format:Y-m-d',
            'to' => 'sometimes|date_format:Y-m-d|after_or_equal:from',
            'limit' => 'sometimes|integer|min:1|max:200',
        ]);
        $from = $input['from'] ?? '2026-01-01';
        $to = $input['to'] ?? '2026-01-02';

        return Telemetry::span('orders.search', function () use ($input, $from, $to): JsonResponse {
            $orders = Order::query()
                ->where('status', $input['status'] ?? 'paid')
                ->whereDate('created_at', '>=', $from)
                ->whereDate('created_at', '<=', $to)
                ->orderByDesc('created_at')
                ->orderByDesc('id')
                ->limit($input['limit'] ?? 50)
                ->get(['id', 'customer_id', 'status', 'total_cents', 'created_at']);

            return response()->json(['data' => $orders, 'count' => $orders->count()]);
        });
    }
}
