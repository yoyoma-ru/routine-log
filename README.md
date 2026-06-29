# routine-log — 日々のルーティン記録アプリ

日々のルーティンを **3段階（✅完了 / 🔸最低限行動 / ✕行動してない）** で記録し、
方眼紙のようなヒートマップで継続を可視化する個人用アプリ（Streamlit製）。

「責めない設計」— 小さな行動でも成功扱いにし、連続日数は途切れにくくして継続を後押しする。

## 特徴
- **開いて3タップで終わる**：今日のルーティンをタップするだけで即保存
- **方眼紙ヒートマップ**：日付を縦・ルーティンを横に詰めて表示（完了=黒塗り / 最低限=斜線半分 / してない=✕ / 未記入=空白）
- **ルーティンの増減に対応**：やめてもアーカイブで履歴は残る（復活可）
- **データは Neon Postgres**：ローカルもデプロイも同じDBを参照。再デプロイでも記録が消えない

## アーキテクチャ（3層）
- `app.py` … フロント（Streamlit UI のみ）
- `services.py` … 処理層（集計・傾向・連続日数・ヒートマップ整形・増減diff）
- `db.py` … データ層（SQLAlchemy モデル + CRUD + 接続/Session）

依存方向は フロント → 処理 → データ の一方向。

## セットアップ

### 1. Neon（無料 Postgres）を用意
1. https://neon.tech でアカウント作成し、無料プロジェクトを新規作成
2. ダッシュボードの「Connection string」をコピー
3. 先頭を `postgresql://` → `postgresql+psycopg2://` に書き換える
4. `.env.example` を `.env` にコピーし、`DATABASE_URL=...` に貼り付ける

```bash
cp .env.example .env
# .env を編集して DATABASE_URL を設定
```

### 2. 依存インストール & テーブル作成 & 起動
```bash
cd routine-log
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python init_db.py          # Neon 上にテーブルを作成
streamlit run app.py
```

ブラウザで http://localhost:8501 が開く。

### スマホから使う（同じ Wi-Fi）
```bash
streamlit run app.py --server.address 0.0.0.0
ipconfig getifaddr en0   # Mac の IP を確認し、スマホで http://<IP>:8501 を開く
```

## デプロイ（後日・無料）
Streamlit Community Cloud にデプロイする場合：
1. このリポジトリを連携
2. Secrets に `DATABASE_URL`（同じ Neon の接続文字列）を設定
3. デプロイ。ローカルと同じDBを見るので記録は継続する

## データモデル
- `routines` … ルーティン（name / sort_order / archived / archived_at / created_at）
- `entries` … 日次の記録（routine_id × date でユニーク、status = done|small|none、note）
- `daily_reflections` … その日のふりかえりメモ（date ユニーク）

すべて JST 基準で日付を扱う。
