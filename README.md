# Mackerel Use Improve Demo

Laravel 13 / PHP 8.4 / PostgreSQL 18 の小規模な受注・在庫管理アプリです。
**main は改善前の基準実装**です。N+1、ロック待ち、全走査、大量行取得、未使用インデックス候補、複雑な価格計算を、Mackerel Skillで観測してシナリオ別PRで改善します。

説明資料は **[HTMLハンドブック](docs/index.html)** にまとめています。GitHub Pagesの公開URLは https://soudai.github.io/mackerel-use-improve-demo/ です。

実データでの確認結果は **[HTML検証レポート](docs/validation.html)** を参照してください。`demo-before-v2` はMackerel実送信まで検証した基準で、旧 `demo-before` タグは初期状態の記録として残します。

## 起動

WSLのリポジトリ内でDocker ComposeとPython 3.12以降を使います。ホストPHPの拡張は不要です。

```sh
cd /home/soudai/work/mackerel/mackerel-use-improve-demo
./scripts/demo setup
./scripts/install-tools
```

アプリ: http://localhost:18080 。初期データは20,000注文・60,000明細です。
`.env` の `APP_PORT` / `DEMO_SEED_ORDERS` でポートと初期seed規模を変更できます。
既にseed済みなら再投入しません。デモDBを初期化するときだけ `./scripts/demo reset --yes` を使います。

## 改善デモ

```sh
git switch -c codex/demo-n-plus-one demo-before-v2
./scripts/demo restart
python3 scripts/load.py orders --requests 100 --concurrency 4 --output artifacts/runs/orders-before.json
python3 scripts/evidence.py --load artifacts/runs/orders-before.json --output artifacts/issues/orders-before
python3 scripts/quality.py
```

Issue下書き・生データは `artifacts/` に保存されGit対象外です。修正はそのブランチで行い、commit後にrestartして同条件で再測定します。`X-App-Revision` が対象SHAと一致することを確認します。

- [HTML資料](docs/index.html): シナリオ、観測方法、受入条件、デモ用プロンプト、運用、業務仕様。
- [Skill](.agents/skills/mackerel-dev-improve/SKILL.md): 調査・改善・比較と品質投稿の手順。
- `scripts/load.py`: 実HTTP負荷と全サンプル・成功/全体分位数。
- `scripts/db_snapshot.py`: クエリ・索引・待機統計と検索の実行計画。
- `scripts/log_summary.py`: route別p95・クエリ数・メモリ・遅いtrace ID。
- `scripts/evidence.py`: ローカルトレース→同一版ソース→Issue下書き。
- `scripts/quality.py`: PHPUnit/CCCCの実レポート→Skillの正規化→投稿dry-run。

## 検証

```sh
./scripts/demo test
python3 -m unittest discover -s tests/python -v
python3 scripts/quality.py
docker compose run --rm --no-deps -e OTEL_SDK_DISABLED=true app vendor/bin/pint --format agent
```

PHPUnitはテスト専用SQLiteメモリDBで動作します。実際の並行制御・実行計画の検証にはPostgreSQLを使ったHTTP負荷とDBスナップショットを併用します。

## Mackerelへの接続

標準構成はローカルの `artifacts/otel/` に保存します。Mackerelに接続するときは、デモ組織の書込み用 `MACKEREL_APIKEY` をGit対象外の `.env` に設定し、明示的に次を実行します。

```sh
DEMO_MACKEREL=1 ./scripts/demo up
```

Collectorはトレース・ログ・DBメトリックスを送ります。品質のサービスメトリックス投稿は別経路で、`quality.py` 自体は送信しません。実際の成果物URL、組織、commit/run/attemptを確認し、同梱Skillの `publish.py --send --expected-org ...` を使います。受信・保存・画面表示は接続後に確認してください。

## GitHub Pages

`docs/index.html` と `docs/assets/` だけで動作する静的HTMLです。依存インストール・ビルド・外部CDNは不要です。

1. GitHubの **Settings → Pages → Source → GitHub Actions** を選択します。
2. mainへpushするか、Actionsの **Deploy documentation to GitHub Pages** を手動実行します。

`.github/workflows/pages.yml` が `docs/` を配信します。HTML内の相対リンクはリポジトリのサブパスにも対応しています。
ローカル確認は `python3 -m http.server 18081 --bind 127.0.0.1 --directory docs` です。

## 来歴

`.agents/skills/mackerel-dev-improve/` は同名Skillのスナップショットを同梱しています。
品質解析器は [moznion/cccc](https://github.com/moznion/cccc) 1.8.3、計装はOpenTelemetry PHP、Collector Contribは0.163.2を使います。アプリのComposer依存は `backend/composer.lock` に固定します。
