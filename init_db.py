"""スプレッドシートのタブ（テーブル）を作成・確認するスクリプト。

通常はアプリ起動時に自動作成される（app.py の _bootstrap_schema）。
手動で用意したい場合のみ、認証情報を環境変数に入れて実行する:

    export GCP_SERVICE_ACCOUNT_JSON='{...service account json...}'
    export SPREADSHEET_NAME='routine-log-db'   # もしくは SPREADSHEET_ID
    python init_db.py
"""
from db import init_db


def main() -> None:
    init_db()
    print("✅ スプレッドシートのタブ（routines/entries/daily_logs/weight_logs/settings）を作成・確認しました")


if __name__ == "__main__":
    main()
