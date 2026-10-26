<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <title>Mackerel Market — 受注・在庫デモ</title>
    <style>
        :root{color-scheme:light;--ink:#16312f;--muted:#667c77;--line:#dce6df;--bg:#f5f5ed;--green:#116b57;--lime:#d8f197}
        *{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif;background:var(--bg);color:var(--ink)}
        button,input,select{font:inherit}button,a,input,select{outline-offset:4px}button{cursor:pointer}header{border-bottom:1px solid var(--line);background:#fff;padding:22px 5vw;display:flex;align-items:center;justify-content:space-between;gap:18px}.brand{font-size:22px;font-weight:850;letter-spacing:-1px}.brand span{color:var(--green)}.tag{font-size:12px;padding:6px 11px;border-radius:20px;background:#eff2e8;color:#42584f}
        main{max-width:1250px;margin:auto;padding:48px 5vw 80px}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:2px;font-weight:750;color:var(--green)}h1{font-size:clamp(30px,4vw,48px);line-height:1.25;letter-spacing:-1.7px;margin:16px 0}p{line-height:1.85;color:var(--muted)}.intro{max-width:680px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:30px}.card{border:1px solid var(--line);border-radius:16px;background:#fff;padding:24px;display:flex;flex-direction:column}.card h2{font-size:19px;margin:12px 0 4px}.card p{font-size:14px;margin:8px 0 20px;flex:1}.number{font-size:12px;font-weight:750;color:var(--green)}button.primary{border:0;background:var(--green);color:#fff;border-radius:9px;padding:12px 16px;font-weight:700;width:100%;transition:background .2s}button.primary:hover{background:#095241}button.primary:disabled{opacity:.55;cursor:wait}.meta{font:11px ui-monospace,monospace;color:var(--muted);margin-top:12px;overflow-wrap:anywhere}
        .section{margin-top:42px}.section-title{display:flex;align-items:baseline;justify-content:space-between;gap:12px}.section-title h2{font-size:22px;letter-spacing:-.6px}.panel{background:var(--ink);color:#d9eee1;border-radius:15px;padding:24px}.panel-header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.panel-header strong{font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:430px;overflow:auto;font-size:12px;line-height:1.65;margin:0}.status{font-size:12px;color:var(--lime)}.quote{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;align-items:end;border:1px solid var(--line);background:#fff;border-radius:15px;padding:24px}label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:var(--muted)}input,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;color:var(--ink);background:white}.check{flex-direction:row;align-items:center;padding-bottom:12px}.check input{width:auto}footer{font-size:12px;color:var(--muted);margin-top:24px}.hint{font-size:12px}.toast{font-size:12px;color:var(--muted)}
        @media(max-width:850px){.grid{grid-template-columns:repeat(2,1fr)}.quote{grid-template-columns:repeat(2,1fr)}}@media(max-width:550px){header{align-items:flex-start;flex-direction:column}main{padding-top:30px}.grid{grid-template-columns:1fr}.quote{grid-template-columns:1fr}.section-title{align-items:flex-start;flex-direction:column;gap:0}.panel{padding:18px}}
    </style>
</head>
<body>
<header><div class="brand">Mackerel <span>Market</span></div><div class="tag">受注・在庫管理 / デモ環境</div></header>
<main>
    <div class="intro"><div class="eyebrow">From observation to improvement</div><h1>注文が増えたとき、<br>どこで時間を使っている？</h1><p>商品を買う、注文を探す、売上を確認する。実際の業務操作から、Mackerelで遅い処理を観測するための小さなマーケットです。</p></div>
    <div class="grid">
        <article class="card"><div class="number">01 / CATALOG</div><h2>商品カタログ</h2><p>販売中の商品と在庫を確認します。最初の商品は、同時購入のデモに使う人気商品です。</p><button class="primary" data-action="products">商品を見る</button><div class="meta">GET /api/products</div></article>
        <article class="card"><div class="number">02 / ORDERS</div><h2>最近の注文</h2><p>最新50件の注文と、注文したお客様を一覧で確認します。</p><button class="primary" data-action="orders">注文一覧を取得</button><div class="meta">GET /api/orders?limit=50</div></article>
        <article class="card"><div class="number">03 / CHECKOUT</div><h2>人気商品を購入</h2><p>顧客ID 1が人気商品を1点購入します。送料を確認し、在庫を引き当てて注文を確定します。</p><button class="primary" data-action="checkout">1点購入する</button><div class="meta">POST /api/checkout</div></article>
        <article class="card"><div class="number">04 / SEARCH</div><h2>注文を検索</h2><p>2026年1月1日〜2日の支払済み注文を、注文日時の新しい順に探します。</p><button class="primary" data-action="search">注文を検索</button><div class="meta">GET /api/orders/search</div></article>
        <article class="card"><div class="number">05 / SALES REPORT</div><h2>月間売上レポート</h2><p>2026年1月の支払済み注文から、注文数・販売数量・日別の売上を集計します。</p><button class="primary" data-action="report">売上を集計</button><div class="meta">GET /api/reports/sales</div></article>
        <article class="card"><div class="number">06 / PRICING</div><h2>会員向け見積り</h2><p>会員ランク・数量・クーポン・配送先を組み合わせて購入金額を計算します。</p><button class="primary" id="quote-focus">見積り条件を選ぶ</button><div class="meta">POST /api/quotes</div></article>
    </div>
    <section class="section" id="quote-section"><div class="section-title"><h2>購入金額の見積り</h2><span class="hint">金額の入力・結果は整数 cents。表示上の金額は100 cents = 1.00。</span></div>
        <form class="quote" id="quote-form">
            <label>単価（cents）<input name="unit_price_cents" type="number" min="1" max="1000000" value="1000" required></label>
            <label>数量<input name="quantity" type="number" min="1" max="100" value="10" required></label>
            <label>会員ランク<select name="customer_tier"><option value="gold">Gold</option><option value="silver">Silver</option><option value="regular">Regular</option></select></label>
            <label>クーポン<select name="coupon"><option value="SAVE10">SAVE10</option><option value="FREESHIP">FREESHIP</option><option value="">なし</option></select></label>
            <label>配送先<select name="region"><option value="tokyo">東京</option><option value="osaka">大阪</option><option value="remote">遠隔地域</option></select></label>
            <label class="check"><input type="checkbox" name="express">速達配送</label><div></div><button class="primary" type="submit">見積りを計算</button>
        </form>
    </section>
    <section class="section" aria-live="polite"><div class="section-title"><h2>操作結果</h2><span class="toast" id="result-summary">操作するとAPIの結果を表示します。</span></div><div class="panel"><div class="panel-header"><strong id="result-title">Ready</strong><span class="status" id="result-status">待機中</span></div><pre id="result-body">商品カタログや注文一覧から操作を始めてください。</pre></div></section>
    <footer>デモ用の架空データを使用しています。購入操作は在庫と注文データを更新します。</footer>
</main>
<script>
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    const actions = {
        products: ['/api/products'], orders: ['/api/orders?limit=50'],
        checkout: ['/api/checkout', {customer_id: 1, product_id: 1, quantity: 1}],
        search: ['/api/orders/search?status=paid&from=2026-01-01&to=2026-01-02'],
        report: ['/api/reports/sales?from=2026-01-01&to=2026-01-31']
    };
    async function execute(url, data, button) {
        button.disabled = true;
        document.getElementById('result-title').textContent = (data ? 'POST ' : 'GET ') + url;
        document.getElementById('result-status').textContent = '実行中…';
        const started = performance.now();
        try {
            const response = await fetch(url, {method: data ? 'POST' : 'GET', headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRF-TOKEN': csrf}, ...(data ? {body: JSON.stringify(data)} : {})});
            const body = await response.json();
            const elapsed = (performance.now() - started).toFixed(1);
            document.getElementById('result-status').textContent = response.status + ' / ' + elapsed + ' ms';
            document.getElementById('result-summary').textContent = 'trace ID: ' + (response.headers.get('X-Trace-Id') || 'レスポンスヘッダーを確認');
            document.getElementById('result-body').textContent = JSON.stringify(body, null, 2);
        } catch (error) {
            document.getElementById('result-status').textContent = '通信エラー';
            document.getElementById('result-body').textContent = error.message;
        } finally { button.disabled = false; }
    }
    document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', () => {
        const [url, data] = actions[button.dataset.action];
        execute(url, data, button);
    }));
    document.getElementById('quote-focus').addEventListener('click', () => { document.getElementById('quote-section').scrollIntoView({behavior: 'smooth'}); document.querySelector('[name="unit_price_cents"]').focus(); });
    document.getElementById('quote-form').addEventListener('submit', event => {
        event.preventDefault();
        const form = event.currentTarget;
        execute('/api/quotes', {unit_price_cents: Number(form.unit_price_cents.value), quantity: Number(form.quantity.value), customer_tier: form.customer_tier.value, coupon: form.coupon.value || null, region: form.region.value, express: form.express.checked}, form.querySelector('button'));
    });
</script>
</body>
</html>
