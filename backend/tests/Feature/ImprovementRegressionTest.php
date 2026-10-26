<?php

namespace Tests\Feature;

use App\Models\Customer;
use App\Models\Inventory;
use App\Models\Order;
use App\Models\Product;
use App\Services\PricingService;
use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use InvalidArgumentException;
use Tests\TestCase;

class ImprovementRegressionTest extends TestCase
{
    use RefreshDatabase;

    private function catalog(int $stock = 10): array
    {
        $customer = Customer::create(['name' => 'Customer', 'tier' => 'regular']);
        $product = Product::create(['name' => 'Product', 'price_cents' => 1000, 'active' => true]);
        Inventory::create(['product_id' => $product->id, 'quantity' => $stock]);

        return [$customer, $product];
    }

    public function test_order_listing_fetches_all_customers_in_one_query(): void
    {
        [$customer] = $this->catalog();
        for ($number = 0; $number < 5; $number++) {
            Order::create(['customer_id' => $customer->id, 'status' => 'paid', 'total_cents' => 1000]);
        }
        $queries = [];
        DB::listen(function (QueryExecuted $query) use (&$queries): void {
            if (str_contains($query->sql, 'from "orders"') || str_contains($query->sql, 'from "customers"')) {
                $queries[] = $query->sql;
            }
        });

        $this->getJson('/api/orders?limit=5')->assertOk()->assertJsonCount(5, 'data');

        $this->assertCount(2, $queries);
    }

    public function test_shipping_quote_runs_before_the_inventory_transaction(): void
    {
        [$customer, $product] = $this->catalog();
        $transactionLevel = DB::transactionLevel();
        $shippingTransactionLevel = null;
        Http::fake(function () use (&$shippingTransactionLevel) {
            $shippingTransactionLevel = DB::transactionLevel();

            return Http::response(['shipping_cents' => 500]);
        });

        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])
            ->assertSuccessful()->assertJsonPath('remaining_stock', 8);

        $this->assertSame($transactionLevel, $shippingTransactionLevel);
    }

    public function test_stock_is_rechecked_after_shipping_quote(): void
    {
        [$customer, $product] = $this->catalog();
        Http::fake(function () use ($product) {
            Inventory::where('product_id', $product->id)->update(['quantity' => 0]);

            return Http::response(['shipping_cents' => 500]);
        });

        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])
            ->assertUnprocessable()->assertJsonValidationErrors('quantity');

        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 0]);
        $this->assertDatabaseCount('orders', 0);
        $this->assertDatabaseCount('order_items', 0);
    }

    public function test_product_is_rechecked_after_shipping_quote(): void
    {
        [$customer, $product] = $this->catalog();
        Http::fake(function () use ($product) {
            $product->update(['active' => false]);

            return Http::response(['shipping_cents' => 500]);
        });

        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])
            ->assertNotFound();

        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 10]);
        $this->assertDatabaseCount('orders', 0);
    }

    public function test_invalid_shipping_amount_cannot_change_stock_or_create_an_order(): void
    {
        [$customer, $product] = $this->catalog();
        Http::fake(['*' => Http::response(['shipping_cents' => '500'])]);

        $this->postJson('/api/checkout', ['customer_id' => $customer->id, 'product_id' => $product->id, 'quantity' => 2])
            ->assertServerError();

        $this->assertDatabaseHas('inventories', ['product_id' => $product->id, 'quantity' => 10]);
        $this->assertDatabaseCount('orders', 0);
    }

    public function test_empty_sales_report_preserves_its_response_shape(): void
    {
        $this->getJson('/api/reports/sales?from=2026-01-01&to=2026-01-31')->assertOk()->assertExactJson([
            'from' => '2026-01-01',
            'to' => '2026-01-31',
            'orders_count' => 0,
            'items_quantity' => 0,
            'gross_cents' => 0,
            'by_date' => [],
        ]);
    }

    public function test_sales_report_counts_each_order_once_with_multiple_items(): void
    {
        [$customer, $product] = $this->catalog();
        $order = Order::create(['customer_id' => $customer->id, 'status' => 'paid', 'total_cents' => 3000000700]);
        $order->forceFill(['created_at' => '2026-01-02 12:00:00'])->save();
        $order->items()->create(['product_id' => $product->id, 'quantity' => 100, 'unit_price_cents' => 30000000]);
        $order->items()->create(['product_id' => $product->id, 'quantity' => 2, 'unit_price_cents' => 350]);

        $this->getJson('/api/reports/sales?from=2026-01-01&to=2026-01-31')->assertOk()
            ->assertJsonPath('orders_count', 1)->assertJsonPath('items_quantity', 102)
            ->assertJsonPath('gross_cents', 3000000700)->assertJsonPath('by_date.2026-01-02', 3000000700);
    }

    public function test_direct_pricing_calls_keep_invalid_enum_error_behavior(): void
    {
        $this->expectException(InvalidArgumentException::class);
        app(PricingService::class)->calculate(['unit_price_cents' => 1000, 'quantity' => 1, 'customer_tier' => []]);
    }
}
