# routine-log — 日々のルーティン記録アプリ

日々のルーティンを **3段階（✅完了 / 🔸最低限行動 / ✕行動してない）** で記録し、
方眼紙のようなヒートマップで継続を可視化する個人用アプリ（Streamlit製）。
体重・睡眠・朝夜の気分も記録できる。

「責めない設計」— 小さな行動でも成功扱いにし、連続日数は途切れにくくして継続を後押しする。

## 特徴
- **開いて3タップで終わる**：タップ/選択して「保存」で確定
- **方眼紙ヒートマップ**：日付を縦・ルーティンを横に詰めて表示（完了=黒塗り / 最低限=斜線半分 / してない=✕ / 未記入=空白）
- **ルーティンの増減に対応**：やめてもアーカイブで履歴は残る（復活可）
- **データは Google スプレッドシート**：無料・コンピュート枠やスリープの制限が無く、表で中身を直接確認できる

## アーキテクチャ（3層）
- `app.py` … フロント（Streamlit UI のみ）。読み取りは `st.cache_data` でキャッシュ。
- `services.py` … 処理層（集計・傾向・連続日数・ヒートマップ整形・体重予測）
- `db.py` … データ層（Google Sheets を gspread で読み書き。関数I/Fは従来どおり）

依存方向は フロント → 処理 → データ の一方向。

## セットアップ（Google スプレッドシート）

### 1. スプレッドシートとサービスアカウントを用意
1. Google ドライブで空のスプレッドシートを新規作成（例: 名前 `routine-log-db`）。
   タブは**アプリ起動時に自動作成**されるので、中身は空でOK。
2. Google サービスアカウントを用意（study-tracker で使っているものを再利用可）。
3. 作成したスプレッドシートを、**サービスアカウントのメール（`client_email`）に「編集者」で共有**。

### 2. Secrets を設定
`.streamlit/secrets.toml.example` を `.streamlit/secrets.toml` にコピーして値を埋める
（Streamlit Cloud の場合は「Manage app → Settings → Secrets」に同じ内容を貼り付け）。

- `spreadsheet_name`（または `spreadsheet_id`）… 対象のスプレッドシート
- `[gcp_service_account]` … サービスアカウントの鍵（JSON の各項目）

### 3. 依存インストール & 起動
```bash
cd routine-log
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py     # 初回にタブを自動作成
```

ブラウザで http://localhost:8501 が開く。

## デプロイ（Streamlit Community Cloud・無料）
1. このリポジトリを連携（main file: `app.py`）
2. Secrets に `[gcp_service_account]` と `spreadsheet_name`（または `spreadsheet_id`）を設定
3. デプロイ。初回起動でタブが自動作成される。

## データモデル（スプレッドシートのタブ = テーブル）
- `routines` … id / name / sort_order / archived / archived_at / created_at
- `entries` … id / routine_id / date / status(done|small|none) / note
- `daily_logs` … date / sleep_hours / mood(旧・互換) / mood_morning / mood_night
- `weight_logs` … date / weight(kg)
- `settings` … key / value（体重の目標体重・目標日など）

日付は 'YYYY-MM-DD'・JST 基準。ヒートマップは日付を縦・ルーティンを横に並べ、
右端に睡眠(数値)・朝の気分・夜の気分（😊良い/😞悪い）の列を表示する。
