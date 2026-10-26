<?php

namespace Tests\Feature;

use App\Services\PricingService;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

class PricingRulesTest extends TestCase
{
    #[DataProvider('priceCases')]
    public function test_price_rules_preserve_business_results(array $input, array $expected): void
    {
        $input += ['unit_price_cents' => 1000, 'quantity' => 1, 'customer_tier' => 'regular', 'coupon' => null, 'region' => 'tokyo', 'express' => false];
        $result = app(PricingService::class)->calculate($input);

        foreach ($expected as $key => $amount) {
            $this->assertSame($amount, $result[$key], $key);
        }
        $this->assertSame($result['subtotal_cents'] - $result['member_discount_cents'] - $result['coupon_discount_cents'] + $result['shipping_cents'], $result['total_cents']);
    }

    public static function priceCases(): array
    {
        return [
            'regular' => [[], ['total_cents' => 1600, 'member_discount_cents' => 0]],
            'silver below quantity threshold' => [['quantity' => 4, 'customer_tier' => 'silver'], ['member_discount_cents' => 200, 'total_cents' => 4400]],
            'silver quantity five' => [['quantity' => 5, 'customer_tier' => 'silver'], ['member_discount_cents' => 350, 'total_cents' => 5250]],
            'silver quantity ten' => [['quantity' => 10, 'customer_tier' => 'silver'], ['member_discount_cents' => 1000, 'shipping_cents' => 600]],
            'gold quantity one' => [['customer_tier' => 'gold'], ['member_discount_cents' => 100, 'total_cents' => 1500]],
            'gold quantity five' => [['quantity' => 5, 'customer_tier' => 'gold'], ['member_discount_cents' => 600, 'total_cents' => 5000]],
            'gold coupon stacking' => [['quantity' => 10, 'customer_tier' => 'gold', 'coupon' => 'SAVE10'], ['member_discount_cents' => 1500, 'coupon_discount_cents' => 850, 'total_cents' => 8250]],
            'regular quantity twenty' => [['quantity' => 20], ['member_discount_cents' => 1000, 'shipping_cents' => 0, 'total_cents' => 19000]],
            'coupon below minimum' => [['unit_price_cents' => 2999, 'coupon' => 'SAVE10'], ['coupon_discount_cents' => 0, 'total_cents' => 3599]],
            'coupon at minimum' => [['unit_price_cents' => 3000, 'coupon' => 'SAVE10'], ['coupon_discount_cents' => 300, 'total_cents' => 3300]],
            'coupon cap' => [['unit_price_cents' => 10000, 'quantity' => 3, 'coupon' => 'SAVE10'], ['coupon_discount_cents' => 2000, 'total_cents' => 28000]],
            'free shipping coupon' => [['coupon' => 'FREESHIP'], ['shipping_cents' => 0, 'total_cents' => 1000]],
            'remote excludes freeship' => [['coupon' => 'FREESHIP', 'region' => 'remote', 'express' => true], ['shipping_cents' => 2000, 'total_cents' => 3000]],
            'express added after free shipping' => [['quantity' => 10, 'express' => true], ['shipping_cents' => 400, 'total_cents' => 10400]],
            'discount affects shipping threshold' => [['quantity' => 10, 'customer_tier' => 'gold'], ['shipping_cents' => 600, 'total_cents' => 9100]],
            'round down member discount' => [['unit_price_cents' => 99, 'customer_tier' => 'gold'], ['member_discount_cents' => 9, 'total_cents' => 690]],
        ];
    }

    public function test_quote_rejects_unknown_coupon(): void
    {
        $this->postJson('/api/quotes', ['unit_price_cents' => 1000, 'quantity' => 1, 'coupon' => 'UNKNOWN'])
            ->assertUnprocessable()->assertJsonValidationErrors('coupon');
    }
}
