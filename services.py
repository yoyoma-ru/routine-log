"""処理層（ロジック）。

画面(app.py)と データ層(db.py) の間に立ち、業務ルールを担う:
- 今日の進捗・連続行動日数の計算
- ヒートマップ用のデータ整形
- 集計（回数・行動率・達成率・傾向）
- ルーティン管理表（data_editor）の編集差分の適用

DB接続の詳細は知らず、db.py の関数だけを呼ぶ。
"""

from datetime import date, timedelta

import pandas as pd

import db

# 状態の表示用マップ（記号は app 側の方眼紙レンダリングで使用）
STATUS_LABELS = {"done": "完了", "small": "最低限行動", "none": "行動してない"}
STATUS_ORDER = ["done", "small", "none"]

# 「行動した」とみなす状態（連続日数・行動率の分子）
ACTED = {"done", "small"}

# 初回オンボーディングで提案する例ルーティン
EXAMPLE_ROUTINES = ["運動", "読書", "瞑想", "日記をつける", "英語の勉強"]


# --- 今日タブ用 -------------------------------------------------------------

def today_progress(day: date, routines: list) -> tuple[int, int]:
    """その日に記録済みの現役ルーティン数と総数 (recorded, total) を返す。"""
    if not routines:
        return (0, 0)
    entries = db.get_entries_for_day(day)
    recorded = sum(1 for r in routines if r.id in entries)
    return (recorded, len(routines))


def _action_days(start: date, end: date) -> set[date]:
    """[start, end] のうち、1つ以上のルーティンを「行動した」日の集合。"""
    days: set[date] = set()
    for _rid, d, status in db.get_entries_range(start, end):
        if status in ACTED:
            days.add(d)
    return days


def current_streak(day: date) -> int:
    """day を末尾とする「連続行動日数」。

    責めない設計: その日がまだ未記録（行動なし）でも連続は途切れず、
    前日から数える。完了でも最低限行動でも『行動した日』として1日に数える。
    """
    acted = _action_days(day - timedelta(days=400), day)
    streak = 0
    cursor = day
    # 当日に行動がなければ、当日は「まだ」として飛ばし前日から数える
    if cursor not in acted:
        cursor -= timedelta(days=1)
    while cursor in acted:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# --- ヒートマップ用 ---------------------------------------------------------

def heatmap_matrix(routines: list, days: int, end: date) -> tuple[list[date], dict]:
    """ヒートマップ用データを返す。

    戻り値:
      dates  … end から過去 days 日、新しい順（上から）に並べた date のリスト
      matrix … {routine_id: {date: status}}（記録のないセルはキー無し＝未記入）
    """
    start = end - timedelta(days=days - 1)
    ids = {r.id for r in routines}
    matrix: dict[int, dict[date, str]] = {r.id: {} for r in routines}
    for rid, d, status in db.get_entries_range(start, end):
        if rid in ids:
            matrix[rid][d] = status
    dates = [end - timedelta(days=i) for i in range(days)]  # 新しい順
    return dates, matrix


# --- 集計・傾向 -------------------------------------------------------------

def summarize(routines: list, end: date) -> pd.DataFrame:
    """ルーティン別の集計表を返す。

    列: ルーティン / 完了 / 最低限 / してない / 行動率 / 達成率 / 傾向
      行動率 = (完了+最低限) / 記録日数
      達成率 = 完了 / 記録日数
      傾向   = 直近7日の行動率 と その前7日の行動率 を比較（↑ → ↓）
    """
    all_entries = db.get_all_entries()
    rows = []
    last7_start = end - timedelta(days=6)
    prev7_start = end - timedelta(days=13)
    prev7_end = end - timedelta(days=7)

    for r in routines:
        ents = [(d, s) for rid, d, s in all_entries if rid == r.id]
        done = sum(1 for _d, s in ents if s == "done")
        small = sum(1 for _d, s in ents if s == "small")
        none = sum(1 for _d, s in ents if s == "none")
        recorded = done + small + none
        act_rate = (done + small) / recorded if recorded else 0.0
        done_rate = done / recorded if recorded else 0.0

        def rate_in(lo: date, hi: date) -> float | None:
            window = [s for d, s in ents if lo <= d <= hi]
            if not window:
                return None
            return sum(1 for s in window if s in ACTED) / len(window)

        recent = rate_in(last7_start, end)
        prev = rate_in(prev7_start, prev7_end)
        trend = _trend_symbol(recent, prev)

        rows.append(
            {
                "ルーティン": r.name,
                "完了": done,
                "最低限": small,
                "してない": none,
                "行動率": f"{round(act_rate * 100)}%",
                "達成率": f"{round(done_rate * 100)}%",
                "傾向": trend,
            }
        )
    return pd.DataFrame(rows)


def _trend_symbol(recent: float | None, prev: float | None) -> str:
    """直近と前期間の行動率を比べて傾向記号を返す。"""
    if recent is None or prev is None:
        return "—"
    diff = recent - prev
    if diff > 0.1:
        return "↑"
    if diff < -0.1:
        return "↓"
    return "→"


# --- ルーティン管理（data_editor の差分適用）-------------------------------

def apply_routine_edits(edited_rows: list[dict], original: list) -> None:
    """data_editor の編集結果を DB に反映する。

    edited_rows: 各行 {"id": int|None, "name": str, "sort_order": int, "archived": bool}
      - id が None/欠落 かつ name あり → 新規追加
      - id あり → name/sort_order/archived の変更を更新
    original にあって edited から消えた行 → ハードデリートせずアーカイブ（安全側）。
    """
    seen_ids: set[int] = set()
    for row in edited_rows:
        rid = row.get("id")
        name = (row.get("name") or "").strip()
        sort_order = row.get("sort_order")
        archived = bool(row.get("archived", False))
        if rid in (None, "") or pd.isna(rid):
            if name:
                r = db.add_routine(name, sort_order=int(sort_order) if sort_order not in (None, "") and not pd.isna(sort_order) else None)
                if archived:
                    db.update_routine(r.id, archived=True)
            continue
        rid = int(rid)
        seen_ids.add(rid)
        db.update_routine(
            rid,
            name=name or None,
            sort_order=int(sort_order) if sort_order not in (None, "") and not pd.isna(sort_order) else None,
            archived=archived,
        )
    # 表から削除された行はアーカイブにフォールバック（履歴を守る）
    for r in original:
        if r.id not in seen_ids:
            db.update_routine(r.id, archived=True)
