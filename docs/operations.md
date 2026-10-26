# ローカル起動と観測

WSL のリポジトリルートで実行します。Docker Engine / Docker Desktop と Compose が必要です。

```sh
cp .env.example .env
./scripts/demo setup
curl -fsS http://localhost:18080/up
```

setup は依存インストール、APP_KEY 生成、migration、seed、起動を行います。Node ビルドは不要です。

| 対象 | 場所 |
| --- | --- |
| 画面/API | http://localhost:18080 |
| PostgreSQL | localhost:55432 (ユーザー demo / パスワード demo / DB demo) |
| トレース | artifacts/otel/traces.jsonl |
| 収集後のアクセスログ | artifacts/otel/logs.jsonl |
| DB メトリックス | artifacts/otel/metrics.jsonl |
| アプリの元アクセスログ | backend/storage/logs/access.jsonl |

shipping・PHP-FPM・Collector の受信ポートは Docker ネットワーク内だけで公開します。外部ポートは localhost に bind します。app の作業ディレクトリは /var/www/html、成果物は /workspace/artifacts に mount します。

```sh
./scripts/demo test
./scripts/demo artisan route:list
./scripts/demo logs --tail=100 collector app
./scripts/demo down
```

down はデータ volume を保持します。初期データの作り直しは `./scripts/demo reset --yes` です。対象はこの Compose プロジェクトの demo データベースです。

## 再現条件

.env の DEMO_SEED_ORDERS (既定 20000)、SHIPPING_DELAY_MS (既定 300ms)、APP_REVISION を記録します。走査の差を見せる際はデータ件数を増やした新規 seed を使います。PHP-FPM は16 worker、配送モックは並行処理します。同じ在庫行で競合した待ち時間を再現できます。

setup / up / restart は、環境変数 APP_REVISION が未指定なら現在の Git commit を自動設定します。初回 commit 前は baseline です。.env に残った baseline より環境変数が優先されます。測定前には変更を commit してください。未コミットの変更を測定する場合は APP_REVISION に説明文字列を明示し、commit と同一とみなしません。

```sh
export APP_REVISION="$(git rev-parse HEAD)"
./scripts/demo up
```

## Mackerel への送信

既定構成はローカル JSON ファイルへ保存します。デモ用の送信先組織を確認し、Write 権限の API key を .env の MACKEREL_APIKEY に設定したうえで、追加 Compose を有効化します。.env は Git 管理しません。

```sh
DEMO_MACKEREL=1 ./scripts/demo up
DEMO_MACKEREL=1 ./scripts/demo logs --tail=100 collector
```

traces/logs は OTLP HTTP、DB メトリックスは OTLP gRPC で送信します。アプリの service.name は mackerel-improve-demo、namespace は demo、環境は development です。Collector が旧ログを読み込む場合も、ログ内の service_version を保持します。

DBクエリはLaravelの`QueryExecuted`で成功した実行を1件のCLIENTスパンとして記録し、`demo.db.execution=true`を付けます。SQL本文はプレースホルダーを保持し、bindingsを展開しません。時間はアプリ側で観測したprepare・execute・fetch（再試行があればその経過を含む）で、DBサーバー内部だけの実行時間ではありません。失敗クエリはこのイベントに出ないため、HTTPエラー・例外とDB側の証拠を別途確認します。PDO自動計装は二重計上を避けるため無効です。旧トレースのPDO execute→prepareリンクは引き続き読み取れます。

通常の `./scripts/demo up` に戻すと Collector がローカル設定で再作成されます。デモ終了時は同じ設定で down します。

Collector 設定の検証:

```sh
docker compose run --rm --no-deps collector validate --config=/etc/otelcol/local.yaml
MACKEREL_APIKEY=validation-only docker compose -f compose.yaml -f compose.mackerel.yaml run --rm --no-deps collector validate --config=/etc/otelcol/local.yaml --config=/etc/otelcol/mackerel.yaml
```

API key をセットした追加 Compose は起動と同時に外部へ送信します。サンプルデータだけを使い、実データ・個人情報を混ぜないでください。Mackerel 側でトレース・ログ・ラベル付きメトリックスを確認し、service/version/観測時間が一致しているか確認します。ローカル検証の成功だけでは Mackerel への保存・画面表示を確認したことにはなりません。

Collector のメモリ内 queue と有限 retry は再起動や上限到達で欠落することがあります。file_log の読取位置は artifacts/otel/checkpoints に永続化します。checkpoint を削除した場合や元ログをコピーし直した場合は、既存ログを再読込する可能性があります。期間・trace ID で絞って調査し、ログ件数をリクエストの完全な母数と扱わないでください。
