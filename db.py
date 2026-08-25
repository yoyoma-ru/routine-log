"""データ層（Google Sheets 版）。

routine-log のデータを1つの Google スプレッドシート（タブ=テーブル）に保存する。
以前は Neon(Postgres) だったが、無料枠のコンピュート時間制限を避けるため Sheets へ移行。
関数名・返り値は従来のまま保つので、app.py / services.py はほぼ変更不要。

- 認証: Google サービスアカウント。
  Streamlit Secrets の `[gcp_service_account]`（study-tracker と同じものを再利用）
  もしくは 環境変数 `GCP_SERVICE_ACCOUNT_JSON`（JSON文字列）。
- 対象シート: Secrets の `spreadsheet_id` または `spreadsheet_name`
  （env の `SPREADSHEET_ID` / `SPREADSHEET_NAME` も可）。
- タブ: routines / entries / daily_logs / weight_logs / settings（init_db で自動作成）。
- 保存はすべて RAW 文字列。日付は 'YYYY-MM-DD'。JSTの今日は today()。
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

JST = timezone(timedelta(hours=9))
VALID_STATUSES = ("done", "small", "none")
VALID_MOODS = ("good", "bad")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# タブ名 → ヘッダ
SHEETS = {
    "routines": ["id", "name", "sort_order", "archived", "archived_at", "created_at"],
    "entries": ["id", "routine_id", "date", "status", "note"],
    "daily_logs": ["date", "sleep_hours", "mood", "mood_morning", "mood_night"],
    "weight_logs": ["date", "weight"],
    "settings": ["key", "value"],
}


# --- 時刻・変換ヘルパー -----------------------------------------------------

def today() -> date:
    return datetime.now(JST).date()


def now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def _iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _pdate(s):
    s = str(s)[:10]
    return date.fromisoformat(s) if s else None


def _pfloat(s):
    if s in (None, ""):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _pbool(s) -> bool:
    return str(s).strip().upper() in ("TRUE", "1", "YES")


def _pstr(s):
    """空文字/None は None に、それ以外は str に。"""
    return str(s) if s not in (None, "") else None


# --- 認証・接続（遅延・プロセス内キャッシュ）-------------------------------
_ss = None  # 開いたスプレッドシート（gspread）を使い回す


def _conf_and_target():
    """(サービスアカウント情報dict, spreadsheet_id, spreadsheet_name) を返す。"""
    conf = sid = sname = None
    try:
        import streamlit as st

        if "gcp_service_account" in st.secrets:
            conf = dict(st.secrets["gcp_service_account"])
            sid = st.secrets.get("spreadsheet_id")
            sname = st.secrets.get("spreadsheet_name")
    except Exception:
        pass
    if conf is None:
        raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
        if raw:
            conf = json.loads(raw)
    sid = sid or os.getenv("SPREADSHEET_ID")
    sname = sname or os.getenv("SPREADSHEET_NAME")
    if conf is None:
        raise RuntimeError(
            "Google認証情報が見つかりません。Streamlit Secrets の [gcp_service_account]"
            "（または環境変数 GCP_SERVICE_ACCOUNT_JSON）を設定してください。"
        )
    if not (sid or sname):
        raise RuntimeError(
            "対象スプレッドシートが未指定です。Secrets に spreadsheet_id か spreadsheet_name"
            "（または env SPREADSHEET_ID / SPREADSHEET_NAME）を設定してください。"
        )
    return conf, sid, sname


def _spreadsheet():
    global _ss
    if _ss is None:
        conf, sid, sname = _conf_and_target()
        gc = gspread.authorize(Credentials.from_service_account_info(conf, scopes=SCOPES))
        _ss = gc.open_by_key(sid) if sid else gc.open(sname)
    return _ss


def _ws(name):
    return _spreadsheet().worksheet(name)


def _records(name):
    return _ws(name).get_all_records()


def ping() -> None:
    """疎通確認（スプレッドシートを開けるか）。失敗時は例外。"""
    _spreadsheet()


def init_db() -> None:
    """必要なタブを作成しヘッダを整える（冪等）。"""
    ss = _spreadsheet()
    existing = {w.title for w in ss.worksheets()}
    for name, headers in SHEETS.items():
        if name not in existing:
            ws = ss.add_worksheet(title=name, rows=2000, cols=max(6, len(headers)))
            ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        else:
            ws = ss.worksheet(name)
            if not ws.row_values(1):
                ws.update(range_name="A1", values=[headers], value_input_option="RAW")


def _append(name, row_values):
    _ws(name).append_row(row_values, value_input_option="RAW")


def _update_row(name, rownum, ncols, row_values):
    last_col = chr(ord("A") + ncols - 1)
    _ws(name).update(
        range_name=f"A{rownum}:{last_col}{rownum}",
        values=[row_values],
        value_input_option="RAW",
    )


# --- Routine ---------------------------------------------------------------

class _Row:
    """属性アクセスできる軽量レコード（ORM互換の見た目）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def list_routines(include_archived: bool = False) -> list:
    out = []
    for r in _records("routines"):
        if str(r.get("id")).strip() == "":
            continue
        archived = _pbool(r.get("archived"))
        if not include_archived and archived:
            continue
        out.append(
            _Row(
                id=int(r["id"]),
                name=str(r.get("name", "")),
                sort_order=int(r.get("sort_order") or 0),
                archived=archived,
                archived_at=_pstr(r.get("archived_at")),
                created_at=_pstr(r.get("created_at")),
            )
        )
    out.sort(key=lambda x: (x.sort_order, x.id))
    return out


def add_routine(name: str, sort_order: int | None = None):
    name = (name or "").strip()
    if not name:
        raise ValueError("ルーティン名が空です。")
    recs = _records("routines")
    ids = [int(r["id"]) for r in recs if str(r.get("id")).strip().lstrip("-").isdigit()]
    new_id = (max(ids) + 1) if ids else 1
    if sort_order is None:
        orders = [int(r.get("sort_order") or 0) for r in recs]
        sort_order = (max(orders) + 1) if orders else 1
    _append(
        "routines",
        [new_id, name, int(sort_order), "FALSE", "", now_jst().strftime("%Y-%m-%d %H:%M:%S")],
    )
    return _Row(id=new_id, name=name, sort_order=int(sort_order), archived=False)


def update_routine(routine_id, *, name=None, sort_order=None, archived=None) -> None:
    recs = _records("routines")
    for i, r in enumerate(recs):
        if str(r.get("id")).strip() == "" or int(r["id"]) != int(routine_id):
            continue
        rownum = i + 2
        new_name = name.strip() if (name is not None and name.strip()) else str(r.get("name", ""))
        new_sort = int(sort_order) if sort_order is not None else int(r.get("sort_order") or 0)
        cur_arch = _pbool(r.get("archived"))
        new_arch = cur_arch if archived is None else bool(archived)
        arch_at = _pstr(r.get("archived_at")) or ""
        if archived is not None and new_arch != cur_arch:
            arch_at = now_jst().strftime("%Y-%m-%d %H:%M:%S") if new_arch else ""
        created = _pstr(r.get("created_at")) or ""
        _update_row(
            "routines",
            rownum,
            6,
            [int(r["id"]), new_name, new_sort, "TRUE" if new_arch else "FALSE", arch_at, created],
        )
        return


# --- Entry -----------------------------------------------------------------

def set_entry(routine_id, day: date, status) -> None:
    recs = _records("entries")
    diso = _iso(day)
    rownum = existing = None
    for i, r in enumerate(recs):
        if str(r.get("routine_id")).strip() == "":
            continue
        if int(r["routine_id"]) == int(routine_id) and str(r.get("date"))[:10] == diso:
            rownum, existing = i + 2, r
            break
    if status is None:
        if rownum:
            _ws("entries").delete_rows(rownum)
        return
    if status not in VALID_STATUSES:
        raise ValueError(f"不正な status: {status!r}")
    if rownum:
        _update_row(
            "entries", rownum, 5,
            [existing["id"], int(routine_id), diso, status, _pstr(existing.get("note")) or ""],
        )
    else:
        ids = [int(r["id"]) for r in recs if str(r.get("id")).strip().lstrip("-").isdigit()]
        new_id = (max(ids) + 1) if ids else 1
        _append("entries", [new_id, int(routine_id), diso, status, ""])


def get_entries_for_day(day: date) -> dict:
    diso = _iso(day)
    return {
        int(r["routine_id"]): str(r["status"])
        for r in _records("entries")
        if str(r.get("routine_id")).strip() != "" and str(r.get("date"))[:10] == diso
    }


def get_entries_range(start: date, end: date) -> list:
    s, e = _iso(start), _iso(end)
    out = []
    for r in _records("entries"):
        if str(r.get("routine_id")).strip() == "":
            continue
        d = str(r.get("date"))[:10]
        if s <= d <= e:
            out.append((int(r["routine_id"]), _pdate(d), str(r["status"])))
    return out


def get_all_entries() -> list:
    out = []
    for r in _records("entries"):
        if str(r.get("routine_id")).strip() == "" or not r.get("date"):
            continue
        out.append((int(r["routine_id"]), _pdate(str(r.get("date"))[:10]), str(r["status"])))
    return out


# --- DailyLog（睡眠・気分 朝/夜）------------------------------------------

def get_daily_log(day: date):
    diso = _iso(day)
    for r in _records("daily_logs"):
        if str(r.get("date"))[:10] == diso:
            return (_pfloat(r.get("sleep_hours")), _pstr(r.get("mood_morning")), _pstr(r.get("mood_night")))
    return (None, None, None)


def _set_daily_field(day: date, field: str, value) -> None:
    recs = _records("daily_logs")
    diso = _iso(day)
    rownum = rec = None
    for i, r in enumerate(recs):
        if str(r.get("date"))[:10] == diso:
            rownum, rec = i + 2, r
            break
    cur = {
        "date": diso,
        "sleep_hours": "" if rec is None else (_pfloat(rec.get("sleep_hours")) if _pfloat(rec.get("sleep_hours")) is not None else ""),
        "mood": "" if rec is None else (_pstr(rec.get("mood")) or ""),
        "mood_morning": "" if rec is None else (_pstr(rec.get("mood_morning")) or ""),
        "mood_night": "" if rec is None else (_pstr(rec.get("mood_night")) or ""),
    }
    cur[field] = "" if value is None else value
    all_empty = all(cur[k] == "" for k in ("sleep_hours", "mood", "mood_morning", "mood_night"))
    if rec is None:
        if all_empty:
            return
        _append(
            "daily_logs",
            [cur["date"], cur["sleep_hours"], cur["mood"], cur["mood_morning"], cur["mood_night"]],
        )
        return
    if all_empty:
        _ws("daily_logs").delete_rows(rownum)
        return
    _update_row(
        "daily_logs", rownum, 5,
        [cur["date"], cur["sleep_hours"], cur["mood"], cur["mood_morning"], cur["mood_night"]],
    )


def set_sleep(day: date, hours) -> None:
    _set_daily_field(day, "sleep_hours", None if hours is None else float(hours))


def _set_mood_field(day: date, field: str, mood) -> None:
    if mood is not None and mood not in VALID_MOODS:
        raise ValueError(f"不正な mood: {mood!r}")
    _set_daily_field(day, field, mood)


def set_mood_morning(day: date, mood) -> None:
    _set_mood_field(day, "mood_morning", mood)


def set_mood_night(day: date, mood) -> None:
    _set_mood_field(day, "mood_night", mood)


def get_daily_logs_range(start: date, end: date) -> list:
    s, e = _iso(start), _iso(end)
    out = []
    for r in _records("daily_logs"):
        d = str(r.get("date"))[:10]
        if d and s <= d <= e:
            out.append((_pdate(d), _pfloat(r.get("sleep_hours")), _pstr(r.get("mood_morning")), _pstr(r.get("mood_night"))))
    out.sort(key=lambda t: t[0])
    return out


# --- WeightLog -------------------------------------------------------------

def get_weight_logs() -> list:
    out = []
    for r in _records("weight_logs"):
        w = _pfloat(r.get("weight"))
        if r.get("date") and w is not None:
            out.append((_pdate(str(r.get("date"))[:10]), w))
    out.sort(key=lambda t: t[0])
    return out


def set_weight(day: date, weight) -> None:
    recs = _records("weight_logs")
    diso = _iso(day)
    rownum = None
    for i, r in enumerate(recs):
        if str(r.get("date"))[:10] == diso:
            rownum = i + 2
            break
    if weight is None:
        if rownum:
            _ws("weight_logs").delete_rows(rownum)
        return
    if rownum:
        _update_row("weight_logs", rownum, 2, [diso, float(weight)])
    else:
        _append("weight_logs", [diso, float(weight)])


# --- Settings --------------------------------------------------------------

def get_setting(key: str):
    for r in _records("settings"):
        if str(r.get("key")) == key:
            return _pstr(r.get("value"))
    return None


def set_setting(key: str, value: str) -> None:
    recs = _records("settings")
    rownum = None
    for i, r in enumerate(recs):
        if str(r.get("key")) == key:
            rownum = i + 2
            break
    if rownum:
        _update_row("settings", rownum, 2, [key, str(value)])
    else:
        _append("settings", [key, str(value)])


def get_weight_goal():
    w = get_setting("weight_target")
    d = get_setting("weight_target_date")
    return (float(w) if w else None, date.fromisoformat(d) if d else None)


def set_weight_goal(target_weight: float, target_date: date) -> None:
    set_setting("weight_target", str(target_weight))
    set_setting("weight_target_date", target_date.isoformat())
