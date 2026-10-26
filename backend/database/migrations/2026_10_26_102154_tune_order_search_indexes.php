<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('orders', function (Blueprint $table) {
            $table->index(['status', 'created_at', 'id'], 'orders_status_created_id_idx');
            $table->dropIndex('orders_legacy_reference_idx');
        });
    }

    public function down(): void
    {
        Schema::table('orders', function (Blueprint $table) {
            $table->dropIndex('orders_status_created_id_idx');
            $table->index('legacy_reference', 'orders_legacy_reference_idx');
        });
    }
};
