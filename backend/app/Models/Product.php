<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasOne;

class Product extends Model
{
    protected $fillable = ['name', 'price_cents', 'active'];

    public function inventory(): HasOne
    {
        return $this->hasOne(Inventory::class);
    }

    protected function casts(): array
    {
        return ['price_cents' => 'integer', 'active' => 'boolean'];
    }
}
