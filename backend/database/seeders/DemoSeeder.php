<?php

namespace Database\Seeders;

use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\DB;
use RuntimeException;

class DemoSeeder extends Seeder
{
    public function run(): void
    {
        if (DB::table('products')->exists()) {
            $this->command?->info('Demo data already exists; seeding skipped. Use the documented reset command for a fresh dataset.');

            return;
        }

        $orderCount = (int) env('DEMO_SEED_ORDERS', 20000);
        if ($orderCount < 100 || $orderCount > 1000000) {
            throw new RuntimeException('DEMO_SEED_ORDERS must be between 100 and 1000000.');
        }

        mt_srand(20260101);
        DB::transaction(function () use ($orderCount): void {
            $customers = [];
            $products = [];
            $inventory = [];
            $now = '2026-01-01 00:00:00';
            for ($id = 1; $id <= 1000; $id++) {
                $customers[] = ['id' => $id, 'name' => sprintf('デモ顧客 %04d', $id), 'tier' => ['regular', 'silver', 'gold'][($id - 1) % 3], 'created_at' => $now, 'updated_at' => $now];
                $products[] = ['id' => $id, 'name' => $id === 1 ? '人気のサバ缶セット' : sprintf('デモ商品 %04d', $id), 'price_cents' => 500 + (($id * 137) % 9500), 'active' => true, 'created_at' => $now, 'updated_at' => $now];
                $inventory[] = ['id' => $id, 'product_id' => $id, 'quantity' => $id === 1 ? 100000 : 1000, 'created_at' => $now, 'updated_at' => $now];
            }
            DB::table('customers')->insert($customers);
            DB::table('products')->insert($products);
            DB::table('inventories')->insert($inventory);

            $orders = [];
            $items = [];
            $itemId = 1;
            $start = strtotime('2026-01-01 00:00:00 UTC');
            for ($id = 1; $id <= $orderCount; $id++) {
                $created = gmdate('Y-m-d H:i:s', $start + mt_rand(0, 31 * 86400 - 1));
                $total = 0;
                for ($line = 0; $line < 3; $line++) {
                    $product = mt_rand(1, 1000);
                    $quantity = mt_rand(1, 3);
                    $price = 500 + (($product * 137) % 9500);
                    $total += $quantity * $price;
                    $items[] = ['id' => $itemId++, 'order_id' => $id, 'product_id' => $product, 'quantity' => $quantity, 'unit_price_cents' => $price, 'created_at' => $created, 'updated_at' => $created];
                }
                $orders[] = ['id' => $id, 'customer_id' => (($id - 1) % 1000) + 1, 'status' => $id % 10 === 0 ? 'cancelled' : ($id % 5 === 0 ? 'pending' : 'paid'), 'total_cents' => $total, 'legacy_reference' => sprintf('legacy-%08d', $id), 'created_at' => $created, 'updated_at' => $created];

                if (count($orders) === 500 || $id === $orderCount) {
                    DB::table('orders')->insert($orders);
                    DB::table('order_items')->insert($items);
                    $orders = [];
                    $items = [];
                }
            }

            if (DB::getDriverName() === 'pgsql') {
                foreach (['customers', 'products', 'inventories', 'orders', 'order_items'] as $table) {
                    DB::statement("SELECT setval(pg_get_serial_sequence('{$table}', 'id'), (SELECT MAX(id) FROM {$table}))");
                }
            }
        });

        if (DB::getDriverName() === 'pgsql') {
            DB::statement('ANALYZE');
        }
        $this->command?->info("Seeded {$orderCount} orders and ".($orderCount * 3).' order items (seed 20260101, January 2026 UTC).');
    }
}
