# デモのシナリオ

mainとタグ`demo-before`は、業務上は動くが性能・保守性に問題がある改善前のベースラインです。修正版をフラグで同居させず、各デモでこのタグからブランチを作り、観測・Issue・修正・検証を経てPRにします。この文書の改善案は仮説です。実測と実行計画を確認して採否を決めます。

## 共通の進め方

```sh
git switch -c codex/demo-n-plus-one demo-before
./scripts/demo setup
python3 scripts/load.py orders --requests 100 --concurrency 4 --warmup 3 --output artifacts/runs/orders-before.json
python3 scripts/evidence.py --load artifacts/runs/orders-before.json --output artifacts/issues/orders-before
```

起動時の`APP_REVISION`は実際のcommit SHAに合わせます。ブランチを切り替えたらアプリを再作成し、レスポンスの`X-App-Revision`と対象コードを照合します。変更中のコードはcommitの内容と一致しないため、トレースのソース帰属は確定しません。修正後はcommitしてから再起動・測定します。

Issueの下書きは`artifacts/issues/.../issue.md`です。`evidence.py`は通常GitHubへ投稿しません。デモでユーザーがIssue作成を依頼した段階で、GitHubツールまたは次を使います。

```sh
python3 scripts/evidence.py --load artifacts/runs/orders-before.json --output artifacts/issues/orders-publish --title '注文一覧のN+1を改善する' --create-issue --repo soudai/mackerel-use-improve-demo
```

before/afterでseed件数、同時接続数、リクエスト数、ウォームアップ、計装、DB統計の観測期間を揃えます。checkoutはDBを更新するので在庫・注文件数の変化を記録します。データの完全一致が必要なら、各測定を独立した初期DBから始めます。ウォームアップは測定の母数に含めませんがcheckoutの在庫は消費します。

性能値は`load.py`の全リクエストと成功リクエストの分布を区別します。エラーが増えて速く見える状態を改善にしません。APMの受信スパン数を負荷生成側の全リクエスト数と同一視せず、ネストしたスパンの時間も合算しません。

## 1. 注文一覧のN+1

- 入口: `GET /api/orders?limit=50`。
- 再現: `python3 scripts/load.py orders --requests 100 --concurrency 4 --output artifacts/runs/orders-before.json`。
- 観測: route別p95、`X-Query-Count`、同一trace内の顧客取得SQLの反復。SQL全体の件数だけでN+1とは断定しません。
- 調査先: 注文一覧の顧客リレーション参照とController。必要な関連情報とAPIの返却項目を確認します。
- 改善候補: Eager Loading。対象の注文・顧客取得だけなら51回から2回へ減らせる設計ですが、実値は計測します。
- 受入条件: 注文の順番・顧客名・件数が同じ。取得件数を増やしてもSQL数が比例増加しない。p95・DB時間・メモリに回帰がない。
- ブランチ例: `codex/demo-n-plus-one`。

## 2. 在庫引当のロック待ち

- 入口: `POST /api/checkout`、同じ`product_id=1`へ集中。
- 再現: `python3 scripts/load.py checkout --requests 40 --concurrency 12 --warmup 1 --timeout 60 --output artifacts/runs/checkout-before.json`。
- 負荷中に別ターミナルで: `python3 scripts/db_snapshot.py --output artifacts/db/checkout-during.json`。
- 観測: 注文確定の遅延、在庫行の取得スパン、配送見積りHTTPスパン、`pg_stat_activity`のLock待機とblocking PID。
- 原因仮説: 外部配送API待ちの間も在庫の行ロックを保持し、同一商品の注文を直列化している。
- 改善候補: 配送見積りを先に取得し、在庫の再確認・更新を短いトランザクションにする。
- 受入条件: 在庫が負数にならず、成功注文数と在庫減少数が一致する。配送失敗時に不完全な注文を残さない。ロック待ちとp95が改善し、タイムアウト・失敗率が悪化しない。
- ブランチ例: `codex/demo-lock-wait`。

ロック件数だけを待ち時間やblocking件数と扱わないでください。traceでDB処理が長いことに加え、負荷中のDB待機情報を保存します。

## 3. 日付検索の全走査

- 入口: `GET /api/orders/search?status=paid&from=2026-01-01&to=2026-01-02`。
- 再現: `python3 scripts/load.py search --requests 100 --concurrency 4 --output artifacts/runs/search-before.json`。
- 実行計画: `python3 scripts/db_snapshot.py --explain-search --output artifacts/db/search-before.json`。
- 観測: クエリ別時間、走査ブロック数、実際の返却行数、Seq Scan・Sortなどの計画。DBスナップショットの固定SQLは改善前APIの日付キャストと順番に合わせています。
- 改善候補: UTC日付境界を維持した半開区間への書換えと、状態・日時・並び順に合う複合索引。最適な索引は実データの選択率で確認します。
- 受入条件: 日付境界、ステータス、降順、同時刻のid順とlimitを維持する。読込量・p95を同条件で比較する。
- ブランチ例: `codex/demo-order-search`。

小さいテーブルや大量に返す検索ではSeq Scanが合理的な場合もあります。遅延のない全走査を一律に障害扱いせず、必要なら初期化時のseedを10万件以上へ増やします。

## 4. 売上集計の大量行取得とPHP内処理

- 入口: `GET /api/reports/sales?from=2026-01-01&to=2026-02-01`。
- 再現: `python3 scripts/load.py report --requests 30 --concurrency 2 --output artifacts/runs/report-before.json`。
- 観測: `reports.fetch_rows`と`reports.aggregate`の時間、DBのSELECT返却行数、アプリのメモリ、レスポンス時間。DBからPHPへの大量転送と、最終レスポンスの大きさは別物です。
- 改善候補: SQL集約で必要な集計結果だけを取得する。
- 受入条件: 集計対象ステータス・日付境界・件数・金額が同じ。ゼロ件と数量2以上もテストする。返却行数・メモリ・p95を比較する。
- ブランチ例: `codex/demo-sales-report`。

`pg_stat_statements.rows`はSELECTでは返却行数を表します。テーブルで走査した全行数とは区別します。累積値のbefore/after差分と実行回数を照合します。

## 5. 観測負荷で使われないインデックス

- 対象候補: 旧検索用`orders_legacy_reference_idx`。
- 観測: `db_snapshot.py`で`idx_scan`、サイズ、primary/unique/制約用途、DBとクエリ統計のreset情報を保存し、全業務の負荷を流した後でもう一度保存する。
- 判断: 代表性のある期間に利用がないこと、月次処理・移行処理・外部利用・制約用途がないことを確認した段階で削除候補のIssueにする。
- 改善候補: 専用migrationで削除し、復元migrationも用意する。
- 受入条件: 全業務・制約が動作する。必要なら同じ書込み負荷でストレージ・更新コストを比較する。短時間の0回から不要と断定しない。
- ブランチ例: `codex/demo-unused-index`。

## 6. 割引ロジックの認知複雑度・循環的複雑度

- 対象: `PricingService`。会員ランク、数量、クーポン、配送条件が入れ子になった改善前の実装。
- 計測: `./scripts/install-tools`の後に`python3 scripts/quality.py`。PHPUnit生XML、独立したテスト一覧、CCCC全件JSON、対象ソースmanifest、正規化bundle、投稿dry-run結果を保存する。
- 観測: `cccc.php_static.cognitive.*`と`cccc.php_static.cyclomatic.*`を別系列で追い、`analysis.complete`と対象件数を先に確認する。関数名やcommitをメトリック名へ展開しない。
- 改善候補: 仕様を決定表・テストで確認し、条件分岐や責務を整理する。別の巨大関数へ移しただけの改善にしない。
- 受入条件: 価格・割引・送料・クーポン併用条件を維持する。関数分割後の明細と差分を確認する。複雑度の低下だけで性能向上や未知のバグ減少を主張しない。
- ブランチ例: `codex/demo-pricing-complexity`。

`quality.py`は送信を行いません。実際の成果物をHTTPSの保存先へアップロードし、cleanな基準commit・run・attemptを照合してから、同梱Skillの`publish.py --send --expected-org ...`を使います。PRごとの結果を共有基準系列へ混ぜないでください。詳細は`.agents/skills/mackerel-dev-improve/references/report-tools.md`にあります。

## トレースからコード・Issue・PRへ

アクセスログではroute、時間、status、trace IDから遅いリクエストを絞ります。内部メソッドの原因は業務子スパンとSQL・DB統計で調べます。個別トレースの全メソッド・行番号が自動計装だけで得られるとは扱いません。

`evidence.py`はローカルCollectorのOTLP JSONを読み、負荷レポートにあるtrace IDで絞ります。service.versionとcleanなHEADが一致したコード属性だけをソースリンクにします。別revision、欠測、取得上限は警告として残します。MackerelのトレースURLは画面で確認した実URLをIssueへ追加してください。ローカルファイルにあるtrace IDだけからMackerelへの保存成功は判定しません。

アクセスログから遅い入口を調べるときは、`python3 scripts/log_summary.py --output artifacts/logs/routes-before.json`を使います。現在のHEADと一致する`service_version`の記録を集計し、route別の総処理時間・p95・クエリ数・メモリと、遅いリクエストのtrace IDを出力します。`--since`と`--until`で負荷レポートと同じUTC期間に絞り、必要なら`--revision`で対象commitを明示します。内部メソッドの特定はそのtraceを使って行います。

Issueには観測期間、環境、revision、負荷条件、証拠、原因仮説と確認済み事項、受入条件を記載します。修正後は同条件で再測定し、PRに実測の前後値とテスト結果・限界を記載します。未実行の検証を成功と書かないでください。
