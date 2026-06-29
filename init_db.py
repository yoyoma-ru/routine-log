"""テーブルを作成・確認するスクリプト。

DATABASE_URL（.env の Neon Postgres）に対して全テーブルを作成する。
通常の起動時には呼ばず、初回セットアップ時やスキーマ追加時に手動で実行する:

    python init_db.py
"""
from db import init_db


def main() -> None:
    init_db()
    print("✅ テーブルを作成・確認しました")


if __name__ == "__main__":
    main()
