<?php

namespace App\Http\Controllers;

use App\Services\PricingService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class QuoteController extends Controller
{
    public function store(Request $request, PricingService $pricing): JsonResponse
    {
        $input = $request->validate([
            'unit_price_cents' => 'required|integer|min:1|max:1000000',
            'quantity' => 'required|integer|min:1|max:100',
            'customer_tier' => 'required|in:regular,silver,gold',
            'coupon' => 'nullable|in:SAVE10,FREESHIP',
            'region' => 'required|in:tokyo,osaka,remote',
            'express' => 'sometimes|boolean',
        ]);

        return response()->json($pricing->calculate($input));
    }
}
