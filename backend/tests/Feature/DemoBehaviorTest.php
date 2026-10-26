<?php

namespace Tests\Feature;

use App\Models\Customer;
use App\Models\Inventory;
use App\Models\Order;
use App\Models\Product;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class DemoBehaviorTest extends TestCase
{
    use RefreshDatabase;

    public function test_tests_are_isolated_from_the_demo_database(): void
    {
        $this->assertSame('sqlite', DB::connection()->getDriverName());
        $this->assertSame(':memory:', config('database.connections.sqlite.database'));
    }

    private function catalog(int $stock = 10): array
    {
        $customer = Customer::create(['name' => 'Demo Customer', 'tier' => 'regular']);
        $product = Product::create(['name' => 'Demo Product', 'price_cents' => 1000, 'active' => true]);
        Inventory::create(['product_id' => $product->id, 'quantity' => $stock]);

        return [$customer, $product];
    }

    private function order(Customer $customer, Product $product, string $status, string $date, int $quantity): Order
    {
        $order = Order::create(['customer_id' => $customer->id, 'status' => $status, 'total_cents' => $quantity * 1000]);
        $order->forceFill(['created_at' => $date, 'updated_at' => $date])->save();
        $order->items()->create(['product_id' => $product->id, 'quantity' => $quantity, 'unit_price_cents' => 1000]);

        return $order;
    }

    public function test_order_listing_preserves_customer_and_order(): void
    {
        [$customer, $product] = $this->catalog();
        $first = $this->order($customer, $product, 'paid', '2026-01-01 12:00:00', 1);
        $second = $this->order($customer, $product, 'pending', '2026-01-02 12:00:00', 2);

        $this->getJson('/api/orders?limit=2')->assertOk()->assertJsonCount(2, 'data')
            ->assertJsonPath('data.0.id', $second->id)->assertJsonPath('data.0.customer', 'Demo Customer')
            ->assertJsonPath('data.1.id', $first->id)->assertHeader('X-App-Revision');
    }

    public function test_search_includes_both_date_boundaries_and_filters_status(): void
    {
        [$customer, $product] = $this->catalog();
        $start = $this->order($customer, $product, 'paid', '2026-01-01 00:00:00', 1);
        $end = $this->order($customer, $product, 'paid', '2026-01-02 23:59:59', 1);
        $this->order($customer, $product, 'paid', '2026-01-03 00:00:00', 1);
        $this->order($customer, $product, 'cancelled', '2026-01-02 12:00:00', 1);

        $this->getJson('/api/orders/search?from=2026-01-01&to=2026-01-02&status=paid')
            ->assertOk()->assertJsonPath('count', 2)->assertJsonPath('data.0.id', $end->id)->assertJsonPath('data.1.id', $start->id);
    }

    public function test_report_aggregates_paid_order_items_and_keeps_last_day(): void
    {
        [$customer, $product] = $this->catalog();
        $this->order($customer, $product, 'paid', '2026-01-01 00:00:00', 2);
        $this->order($customer, $product, 'paid', '2026-01-31 23:59:59', 3);
        $this->order($customer, $product, 'cancelled', '2026-01-02 12:00:00', 100);
        $this->order($customer, $product, 'paid', '2026-02-01 00:00:00', 100);

        $this->getJson('/api/reports/sales?from=2026-01-01&to=2026-01-31')->assertOk()
            ->assertJsonPath('orders_count', 2)->assertJsonPath('items_quantity', 5)->assertJsonPath('gross_cents', 5000)
            ->assertJsonPath('by_date.2026-01-01', 2000)->assertJsonPath('by_date.2026-01-31', 3000);
    }

    public function test_checkout_updates_stock_order_and_total_atomically(): void
    {
        [$customer, $product] = $this->catalog(10);
        Http::fake(['*' => Http::response(['shipping_cents' => 500])]);

        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])
            ->assertSuccessful()->assertJsonPath('total_cents', 2500)->assertJsonPath('remaining_stock', 8);
        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 8]);
        $this->assertDatabaseHas('order_items', ['product_id' => $product->id, 'quantity' => 2]);
        $this->assertDatabaseCount('orders', 1);
    }

    public function test_insufficient_stock_creates_no_order_and_calls_no_shipping(): void
    {
        [$customer, $product] = $this->catalog(1);
        Http::fake();
        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])->assertUnprocessable();
        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 1]);
        $this->assertDatabaseCount('orders', 0);
        Http::assertNothingSent();
    }

    public function test_shipping_failure_rolls_back_stock_and_order(): void
    {
        [$customer, $product] = $this->catalog(10);
        Http::fake(['*' => Http::response([], 503)]);
        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])->assertServerError();
        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 10]);
        $this->assertDatabaseCount('orders', 0);
    }

    public function test_invalid_quantity_is_rejected_before_writes(): void
    {
        [$customer, $product] = $this->catalog();
        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => -1])->assertUnprocessable();
        $this->assertDatabaseCount('orders', 0);
    }

    public function test_reversed_search_range_is_rejected(): void
    {
        $this->getJson('/api/orders/search?from=2026-01-03&to=2026-01-01')->assertUnprocessable();
    }
}
