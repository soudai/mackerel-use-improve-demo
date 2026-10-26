<?php

namespace App\Http\Controllers;

use App\Services\SalesReportService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class ReportController extends Controller
{
    public function sales(Request $request, SalesReportService $reports): JsonResponse
    {
        $request->mergeIfMissing(['from' => '2026-01-01', 'to' => '2026-01-31']);
        $input = $request->validate([
            'from' => 'sometimes|date_format:Y-m-d',
            'to' => 'sometimes|date_format:Y-m-d|after_or_equal:from',
        ]);

        return response()->json($reports->generate($input['from'] ?? '2026-01-01', $input['to'] ?? '2026-01-31'));
    }
}
