<?php

namespace App\Services;

use App\Support\Telemetry;
use InvalidArgumentException;

class PricingService
{
    /**
     * Rules are specified in docs/domain.md. This baseline deliberately keeps
     * the growing business rules in one nested method for the complexity demo.
     */
    public function calculate(array $input): array
    {
        return Telemetry::span('pricing.calculate', function () use ($input): array {
            $price = (int) ($input['unit_price_cents'] ?? 0);
            $quantity = (int) ($input['quantity'] ?? 0);
            $tier = $input['customer_tier'] ?? 'regular';
            $coupon = $input['coupon'] ?? null;
            $region = $input['region'] ?? 'tokyo';
            $express = (bool) ($input['express'] ?? false);

            if ($price < 1 || $price > 1000000 || $quantity < 1 || $quantity > 100) {
                throw new InvalidArgumentException('Price or quantity is outside the supported range.');
            }
            if (! in_array($tier, ['regular', 'silver', 'gold'], true) || ! in_array($coupon, [null, 'SAVE10', 'FREESHIP'], true) || ! in_array($region, ['tokyo', 'osaka', 'remote'], true)) {
                throw new InvalidArgumentException('Unknown tier, coupon, or region.');
            }

            $subtotal = $price * $quantity;
            $rate = 0;
            if ($tier === 'gold') {
                if ($quantity >= 10) {
                    $rate = 15;
                } else {
                    if ($quantity >= 5) {
                        $rate = 12;
                    } else {
                        $rate = 10;
                    }
                }
            } else {
                if ($tier === 'silver') {
                    if ($quantity >= 10) {
                        $rate = 10;
                    } else {
                        if ($quantity >= 5) {
                            $rate = 7;
                        } else {
                            $rate = 5;
                        }
                    }
                } else {
                    if ($quantity >= 20) {
                        $rate = 5;
                    }
                }
            }

            $memberDiscount = intdiv($subtotal * $rate, 100);
            $couponDiscount = 0;
            if ($coupon === 'SAVE10') {
                if ($subtotal >= 3000) {
                    $couponDiscount = min(2000, intdiv(($subtotal - $memberDiscount) * 10, 100));
                }
            }

            $net = $subtotal - $memberDiscount - $couponDiscount;
            if ($region === 'remote') {
                if ($net >= 10000) {
                    $shipping = 600;
                } else {
                    $shipping = 1200;
                }
                if ($express) {
                    $shipping += 800;
                }
            } else {
                if ($net >= 10000) {
                    $shipping = 0;
                } else {
                    $shipping = 600;
                }
                if ($coupon === 'FREESHIP') {
                    $shipping = 0;
                }
                if ($express) {
                    $shipping += 400;
                }
            }

            return [
                'subtotal_cents' => $subtotal,
                'member_discount_cents' => $memberDiscount,
                'coupon_discount_cents' => $couponDiscount,
                'shipping_cents' => $shipping,
                'total_cents' => $net + $shipping,
            ];
        });
    }
}
