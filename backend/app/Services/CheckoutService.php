<?php

namespace App\Services;

use App\Models\Inventory;
use App\Models\Order;
use App\Models\Product;
use App\Support\Telemetry;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Illuminate\Validation\ValidationException;
use UnexpectedValueException;

class CheckoutService
{
    public function checkout(int $customerId, int $productId, int $quantity): array
    {
        if ($quantity < 1 || $quantity > 100) {
            throw ValidationException::withMessages(['quantity' => '数量は1〜100で指定してください。']);
        }

        return Telemetry::span('checkout.reserve', function () use ($customerId, $productId, $quantity): array {
            Product::query()->where('active', true)->findOrFail($productId);
            $available = Inventory::query()->where('product_id', $productId)->firstOrFail();
            $this->ensureStock($available, $quantity);
            $shipping = $this->shippingQuote();

            return DB::transaction(function () use ($customerId, $productId, $quantity, $shipping): array {
                $product = Product::query()->where('active', true)->findOrFail($productId);
                $inventory = Inventory::query()->where('product_id', $productId)->lockForUpdate()->firstOrFail();
                $this->ensureStock($inventory, $quantity);

                $inventory->quantity -= $quantity;
                $inventory->save();
                $order = Order::create([
                    'customer_id' => $customerId,
                    'status' => 'paid',
                    'total_cents' => $product->price_cents * $quantity + $shipping,
                ]);
                $order->items()->create([
                    'product_id' => $productId,
                    'quantity' => $quantity,
                    'unit_price_cents' => $product->price_cents,
                ]);

                return ['order_id' => $order->id, 'total_cents' => $order->total_cents, 'remaining_stock' => $inventory->quantity];
            });
        });
    }

    private function ensureStock(Inventory $inventory, int $quantity): void
    {
        if ($inventory->quantity < $quantity) {
            throw ValidationException::withMessages(['quantity' => '在庫が不足しています。']);
        }
    }

    private function shippingQuote(): int
    {
        return Telemetry::span('shipping.quote', function (): int {
            $response = Http::timeout(5)->get(rtrim(config('demo.shipping_url'), '/').'/quote', [
                'region' => 'tokyo',
                'delay_ms' => (int) config('demo.shipping_delay_ms', 400),
            ])->throw();
            $amount = $response->json('shipping_cents');
            if (! is_int($amount) || $amount < 0 || $amount > 100000) {
                throw new UnexpectedValueException('Shipping quote must contain a non-negative integer shipping_cents.');
            }

            return $amount;
        });
    }
}
