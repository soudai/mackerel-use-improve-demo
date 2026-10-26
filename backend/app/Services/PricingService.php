<?php

namespace App\Services;

use App\Support\Telemetry;
use InvalidArgumentException;

class PricingService
{
    public function calculate(array $input): array
    {
        return Telemetry::span('pricing.calculate', function () use ($input): array {
            $price = (int) ($input['unit_price_cents'] ?? 0);
            $quantity = (int) ($input['quantity'] ?? 0);
            $tier = $input['customer_tier'] ?? 'regular';
            $coupon = $input['coupon'] ?? null;
            $region = $input['region'] ?? 'tokyo';
            $express = (bool) ($input['express'] ?? false);
            $this->validateInput($price, $quantity, $tier, $coupon, $region);

            $subtotal = $price * $quantity;
            $memberDiscount = intdiv($subtotal * $this->memberRate($tier, $quantity), 100);
            $couponDiscount = $this->couponDiscount($coupon, $subtotal, $memberDiscount);
            $net = $subtotal - $memberDiscount - $couponDiscount;
            $shipping = $this->shipping($region, $coupon, $net, $express);

            return [
                'subtotal_cents' => $subtotal,
                'member_discount_cents' => $memberDiscount,
                'coupon_discount_cents' => $couponDiscount,
                'shipping_cents' => $shipping,
                'total_cents' => $net + $shipping,
            ];
        });
    }

    private function validateInput(int $price, int $quantity, mixed $tier, mixed $coupon, mixed $region): void
    {
        if ($price < 1 || $price > 1000000 || $quantity < 1 || $quantity > 100) {
            throw new InvalidArgumentException('Price or quantity is outside the supported range.');
        }
        foreach ([[$tier, ['regular', 'silver', 'gold']], [$coupon, [null, 'SAVE10', 'FREESHIP']], [$region, ['tokyo', 'osaka', 'remote']]] as [$value, $allowed]) {
            if (! in_array($value, $allowed, true)) {
                throw new InvalidArgumentException('Unknown tier, coupon, or region.');
            }
        }
    }

    private function memberRate(string $tier, int $quantity): int
    {
        $rules = [
            'regular' => [[20, 5], [1, 0]],
            'silver' => [[10, 10], [5, 7], [1, 5]],
            'gold' => [[10, 15], [5, 12], [1, 10]],
        ];
        foreach ($rules[$tier] as [$minimum, $rate]) {
            if ($quantity >= $minimum) {
                return $rate;
            }
        }

        return 0;
    }

    private function couponDiscount(?string $coupon, int $subtotal, int $memberDiscount): int
    {
        if ($coupon !== 'SAVE10' || $subtotal < 3000) {
            return 0;
        }

        return min(2000, intdiv(($subtotal - $memberDiscount) * 10, 100));
    }

    private function shipping(string $region, ?string $coupon, int $net, bool $express): int
    {
        if ($region === 'remote') {
            return ($net >= 10000 ? 600 : 1200) + ($express ? 800 : 0);
        }
        $base = ($net >= 10000 || $coupon === 'FREESHIP') ? 0 : 600;

        return $base + ($express ? 400 : 0);
    }
}
