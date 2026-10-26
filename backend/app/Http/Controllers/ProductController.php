<?php

namespace App\Http\Controllers;

use App\Models\Product;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class ProductController extends Controller
{
    public function index(Request $request): JsonResponse
    {
        $input = $request->validate(['limit' => 'sometimes|integer|min:1|max:100']);
        $products = Product::query()->where('active', true)->with('inventory')->orderBy('id')->limit($input['limit'] ?? 12)->get();

        return response()->json(['data' => $products->map(fn (Product $product) => [
            'id' => $product->id,
            'name' => $product->name,
            'price_cents' => $product->price_cents,
            'stock' => $product->inventory?->quantity ?? 0,
        ])]);
    }
}
