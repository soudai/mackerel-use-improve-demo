<?php

namespace App\Providers;

use Illuminate\Database\Events\QueryExecuted;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        //
    }

    public function boot(): void
    {
        DB::listen(function (QueryExecuted $query): void {
            if ($this->app->bound('request')) {
                $attributes = $this->app->make('request')->attributes;
                $attributes->set('demo.query_count', (int) $attributes->get('demo.query_count', 0) + 1);
            }
        });
    }
}
