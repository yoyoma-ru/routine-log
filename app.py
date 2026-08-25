"""フロントエンド（Streamlit UI）。

画面の組み立てと入力受付・表示だけを行い、集計やDB操作は services / db に委ねる。
タブ構成: 今日 / ヒートマップ / 体重 / 管理。
"""

from collections import namedtuple
from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="routine-log", page_icon="🌱", layout="wide")

# 体重の選択肢: 62.0 → 54.0 を 0.1 刻み（表示は小数第1位）
WEIGHT_OPTIONS = [round(62.0 - 0.1 * i, 1) for i in range(81)]
# 睡眠の選択肢: 12.0 → 0.0 を 0.5 刻み（プルダウン）
SLEEP_OPTIONS = [round(12.0 - 0.5 * i, 1) for i in range(25)]

# DATABASE_URL 未設定や接続不可は、画面上で分かりやすく案内する。
try:
    import db
    import services
except RuntimeError as e:
    st.error(str(e))
    st.info("`.env` に Neon の DATABASE_URL を設定し、`python init_db.py` を実行してください。")
    st.stop()


# ---- 読み取りキャッシュ ----------------------------------------------------
# Neon への往復を減らすため、読み取りは st.cache_data でキャッシュする。
# 返り値は「素のデータ（tuple/namedtuple）」のみ（ORMオブジェクトはキャッシュしない）。
# 書き込み後は各所で st.cache_data.clear() を呼び、最新を反映する。
RoutineView = namedtuple("RoutineView", "id name sort_order archived")


@st.cache_data(ttl=300, show_spinner=False)
def _routines(include_archived: bool):
    return [
        RoutineView(r.id, r.name, r.sort_order, r.archived)
        for r in db.list_routines(include_archived=include_archived)
    ]


@st.cache_data(ttl=300, show_spinner=False)
def _entries_range(start, end):
    return db.get_entries_range(start, end)


@st.cache_data(ttl=300, show_spinner=False)
def _daily_logs_range(start, end):
    return db.get_daily_logs_range(start, end)


@st.cache_data(ttl=300, show_spinner=False)
def _weight_logs():
    return db.get_weight_logs()


@st.cache_data(ttl=300, show_spinner=False)
def _weight_goal():
    return db.get_weight_goal()


def _matrix(routines: list, days: int, end):
    """ヒートマップ用 (dates[新しい順], {routine_id: {date: status}}) をキャッシュ経由で作る。"""
    start = end - timedelta(days=days - 1)
    ids = {r.id for r in routines}
    matrix = {r.id: {} for r in routines}
    for rid, d, status in _entries_range(start, end):
        if rid in ids:
            matrix[rid][d] = status
    dates = [end - timedelta(days=i) for i in range(days)]
    return dates, matrix


# 方眼紙ヒートマップ用のスタイル（記号: 完了=黒塗り / 最低限=斜線半分 / してない=✕ / 未記入=空白）。
# 色は currentColor を使い、ライト/ダークのテーマ文字色に自動追従させる。
HEATMAP_CSS = """
<style>
.rl-wrap{max-height:460px;overflow:auto;border:1px solid currentColor;border-radius:4px;width:fit-content;max-width:100%;}
.rl-grid{display:grid;}
.rl-corner{position:sticky;top:0;left:0;z-index:3;background:var(--background-color);
  border-right:1px solid currentColor;border-bottom:1px solid currentColor;
  font-size:11px;opacity:.6;display:flex;align-items:flex-end;justify-content:center;padding-bottom:4px;}
.rl-head{position:sticky;top:0;z-index:2;background:var(--background-color);
  border-bottom:1px solid currentColor;font-size:14px;line-height:1.15;
  display:flex;align-items:flex-start;justify-content:center;padding:8px 2px;
  writing-mode:vertical-rl;text-orientation:upright;letter-spacing:1.5px;white-space:nowrap;}
.rl-date{position:sticky;left:0;z-index:1;background:var(--background-color);
  border-right:1px solid currentColor;border-bottom:0.5px solid rgba(128,128,128,.35);
  display:flex;align-items:center;padding:0 6px;font-size:11px;white-space:nowrap;opacity:.85;}
.rl-date.today{opacity:1;font-weight:600;}
.rl-cell{border-bottom:0.5px solid rgba(128,128,128,.35);border-right:0.5px solid rgba(128,128,128,.35);
  display:flex;align-items:center;justify-content:center;padding:3px;box-sizing:border-box;}
.rl-mark{width:100%;height:100%;box-sizing:border-box;}
.rl-done{background:currentColor;}
.rl-small{background:linear-gradient(135deg,currentColor 0 50%,transparent 50% 100%);}
.rl-none{display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;line-height:1;}
.rl-mgood,.rl-mbad{display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;}
.rl-mgood{background:#EAF3DE;}
.rl-mbad{background:#FCEBEB;}
.rl-num{font-size:12px;font-variant-numeric:tabular-nums;}
.rl-stripgrid{display:grid;align-items:center;overflow-x:auto;}
.rl-saxis{font-size:10px;opacity:.7;text-align:center;padding-bottom:3px;white-space:nowrap;}
.rl-strip-name{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:8px;}
.rl-scell{height:22px;border:0.5px solid rgba(128,128,128,.4);box-sizing:border-box;
  display:flex;align-items:center;justify-content:center;}
.rl-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:10px;font-size:12px;opacity:.8;}
.rl-legend .box{width:16px;height:16px;border:0.5px solid rgba(128,128,128,.5);display:inline-flex;
  align-items:center;justify-content:center;vertical-align:-3px;margin-right:5px;font-size:11px;}
.rl-recent-h{font-size:12px;opacity:.6;margin-bottom:6px;}
.rl-only-mobile{display:none;}
@media (max-width:640px){.rl-only-desktop{display:none;}.rl-only-mobile{display:block;}}
@media (max-width:640px){
  .st-key-today3 [data-testid="stHorizontalBlock"]{flex-direction:column-reverse;}
  .st-key-today3 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{
    width:100%!important;flex:1 1 100%!important;min-width:100%!important;}
}
.st-key-today3 [data-testid="stButtonGroup"] button{
  padding-left:7px!important;padding-right:7px!important;font-size:13px!important;white-space:nowrap;}
</style>
"""

CELL = 28
DATEW = 60


def _mark_html(status: str | None) -> str:
    if status == "done":
        return '<div class="rl-mark rl-done"></div>'
    if status == "small":
        return '<div class="rl-mark rl-small"></div>'
    if status == "none":
        return '<div class="rl-mark rl-none">✕</div>'
    return ""  # 未記入


# セル/凡例で使う記号（今日タブの入力ボタンとヒートマップで共通）
STATUS_SYMBOL = {"done": "■", "small": "◤", "none": "✕"}
SHORT_STATUS = {"done": "完了", "small": "最低限", "none": "してない"}
# 気分は色付きの顔で表現（良い=緑背景の笑顔 / 悪い=赤背景の困り顔）
MOOD_EMOJI = {"good": "😊", "bad": "😞"}


def _mood_html(mood: str | None) -> str:
    if mood == "good":
        return '<div class="rl-mark rl-mgood">😊</div>'
    if mood == "bad":
        return '<div class="rl-mark rl-mbad">😞</div>'
    return ""  # 未記入


SLEEPW = 44  # 睡眠時間の列幅
MOODW = 30   # 気分の列幅


def render_heatmap(routines: list, days: int, end, show_daily: bool = False) -> str:
    """方眼紙スタイルのヒートマップ HTML を返す（行=日付・列=ルーティン・縦書き見出し）。

    show_daily=True のとき、右端に「睡眠時間（数値）」「朝の気分」「夜の気分」の列を足す。
    睡眠・気分は日付ごとの記録（ルーティン非依存）なので現役ヒートマップにのみ表示する。
    """
    if not routines:
        return "<p style='opacity:.7'>表示できるルーティンがありません。</p>"
    dates, matrix = _matrix(routines, days, end)
    daily = {}
    if show_daily:
        daily = {
            d: (sh, mm, mn)
            for d, sh, mm, mn in _daily_logs_range(dates[-1], dates[0])
        }

    cols = f"{DATEW}px " + " ".join([f"{CELL}px"] * len(routines))
    if show_daily:
        cols += f" {SLEEPW}px {MOODW}px {MOODW}px"

    # 見出しは高さ固定せず、名前の全長に合わせて伸ばす（切れ防止）。
    cells = ['<div class="rl-corner">日付＼行動</div>']
    for r in routines:
        cells.append(f'<div class="rl-head" title="{r.name}">{r.name}</div>')
    if show_daily:
        cells.append('<div class="rl-head">睡眠</div>')
        cells.append('<div class="rl-head">朝の気分</div>')
        cells.append('<div class="rl-head">夜の気分</div>')

    dow = ["月", "火", "水", "木", "金", "土", "日"]
    today = db.today()
    for d in dates:
        cls = "rl-date today" if d == today else "rl-date"
        label = f'{d.month}/{d.day} <span style="opacity:.6;margin-left:3px">{dow[d.weekday()]}</span>'
        cells.append(f'<div class="{cls}" style="height:{CELL}px">{label}</div>')
        for r in routines:
            status = matrix[r.id].get(d)
            cells.append(f'<div class="rl-cell" style="height:{CELL}px">{_mark_html(status)}</div>')
        if show_daily:
            sh, mm, mn = daily.get(d, (None, None, None))
            sleep_txt = f"{sh:g}" if sh is not None else ""
            cells.append(f'<div class="rl-cell rl-num" style="height:{CELL}px">{sleep_txt}</div>')
            cells.append(f'<div class="rl-cell" style="height:{CELL}px">{_mood_html(mm)}</div>')
            cells.append(f'<div class="rl-cell" style="height:{CELL}px">{_mood_html(mn)}</div>')
    grid = f'<div class="rl-grid" style="grid-template-columns:{cols}">' + "".join(cells) + "</div>"
    return f'<div class="rl-wrap">{grid}</div>'


def render_strip(routines: list, days: int, end) -> str:
    """今日タブ用のコンパクトな横ストリップ（行=ルーティン・列=直近N日）。

    日付は左=古い → 右=最新。上端に日付ラベル（曜日なし。月初は M/D、それ以外は日のみ）。
    """
    if not routines:
        return ""
    dates, matrix = _matrix(routines, days, end)
    dates = list(reversed(dates))  # 左=古い → 右=今日
    name_w, sc = 120, 28
    cols = f"{name_w}px " + " ".join([f"{sc}px"] * len(dates))

    # 気分（朝・夜）を日付ごとに取得。ルーティンの上に行として表示する。
    mood = {
        d: (mm, mn) for d, _sh, mm, mn in _daily_logs_range(dates[0], dates[-1])
    }

    cells = ['<div></div>']  # 日付軸の左端（名前列の上）
    prev_month = None
    for d in dates:
        label = f"{d.month}/{d.day}" if d.month != prev_month else f"{d.day}"
        prev_month = d.month
        cells.append(f'<div class="rl-saxis">{label}</div>')

    # 朝の気分 / 夜の気分（筋トレの上）
    for idx, mlabel in enumerate(("朝の気分", "夜の気分")):
        cells.append(f'<div class="rl-strip-name">{mlabel}</div>')
        for d in dates:
            m = mood.get(d, (None, None))[idx]
            cells.append(f'<div class="rl-scell">{_mood_html(m)}</div>')

    for r in routines:
        cells.append(f'<div class="rl-strip-name" title="{r.name}">{r.name}</div>')
        for d in dates:
            cells.append(f'<div class="rl-scell">{_mark_html(matrix[r.id].get(d))}</div>')

    return f'<div class="rl-stripgrid" style="grid-template-columns:{cols}">' + "".join(cells) + "</div>"


def render_recent(routines: list, day) -> str:
    """直近の帯をレスポンシブに返す。PCは2週間(14日)、スマホ幅は1週間(7日)を表示。"""
    desktop = (
        '<div class="rl-only-desktop"><div class="rl-recent-h">直近2週間</div>'
        + render_strip(routines, 14, day)
        + "</div>"
    )
    mobile = (
        '<div class="rl-only-mobile"><div class="rl-recent-h">直近1週間</div>'
        + render_strip(routines, 7, day)
        + "</div>"
    )
    return desktop + mobile


def legend_html(with_daily: bool = False) -> str:
    items = (
        '<span><span class="box rl-done"></span>完了</span>'
        '<span><span class="box rl-small"></span>最低限行動</span>'
        '<span><span class="box">✕</span>行動してない</span>'
        '<span><span class="box"></span>未記入</span>'
    )
    if with_daily:
        items += (
            '<span><span class="box rl-mgood">😊</span>気分：良い</span>'
            '<span><span class="box rl-mbad">😞</span>気分：悪い</span>'
            "<span>睡眠：時間（数値）</span>"
        )
    return f'<div class="rl-legend">{items}</div>'


def _save_day(d, routines) -> None:
    """指定日1日分（体重・睡眠・気分・全ルーティン）をフォームの入力値から保存する。"""
    # 体重・睡眠は未選択(None)なら既存値を消さないようスキップ（プルダウンの選択肢外の既存値保護）。
    w = st.session_state.get(f"f_weight_{d.isoformat()}")
    if w is not None:
        db.set_weight(d, w)
    s = st.session_state.get(f"f_sleep_{d.isoformat()}")
    if s is not None:
        db.set_sleep(d, s)
    db.set_mood_morning(d, st.session_state.get(f"f_moodm_{d.isoformat()}"))
    db.set_mood_night(d, st.session_state.get(f"f_moodn_{d.isoformat()}"))
    for r in routines:
        db.set_entry(r.id, d, st.session_state.get(f"f_seg_{r.id}_{d.isoformat()}"))


# ---- タブ本体 --------------------------------------------------------------

st.markdown(HEATMAP_CSS, unsafe_allow_html=True)
st.title("🌱 routine-log")

# 保存先（Google スプレッドシート）の疎通チェック＋初回のタブ自動作成。
@st.cache_resource(show_spinner=False)
def _bootstrap_schema():
    db.init_db()  # 冪等（不足タブのみ作成）
    return True


try:
    db.ping()
    _bootstrap_schema()
except Exception as e:  # noqa: BLE001 - 接続/権限系はまとめて拾って案内する
    st.error("データ保存先（Google スプレッドシート）に接続できませんでした。")
    st.info(
        "Streamlit の Secrets に `[gcp_service_account]` と `spreadsheet_id`（または `spreadsheet_name`）を設定し、"
        "対象スプレッドシートをサービスアカウントに『編集者』で共有してください。"
    )
    st.caption(f"詳細: {str(e)[:300]}")
    st.stop()

tab_today, tab_heat, tab_weight, tab_manage = st.tabs(
    ["今日", "ヒートマップ", "体重", "管理"]
)


DOW = ["月", "火", "水", "木", "金", "土", "日"]


with tab_today:
    day = st.date_input(
        "基準日", value=db.today(), format="YYYY/MM/DD", help="この日＋前2日の3日分を表示します"
    )
    routines = _routines(False)

    if not routines:
        st.info("まだルーティンがありません。例から追加して始めましょう。")
        st.write("、".join(services.EXAMPLE_ROUTINES))
        if st.button("例のルーティンを追加", type="primary"):
            for i, name in enumerate(services.EXAMPLE_ROUTINES):
                db.add_routine(name, sort_order=i + 1)
            st.cache_data.clear()
            st.rerun()
    else:
        st.markdown(render_recent(routines, day), unsafe_allow_html=True)
        st.divider()

        # DOM順は 前々日 → 前日 → 選択日。
        # PC(>640px): st.columns(3) で横一列（左=古い → 右=選択日）。
        # スマホ(<=640px): CSS で column-reverse にして縦積み＆選択日を最上部に。
        disp_days = [day - timedelta(days=2), day - timedelta(days=1), day]
        ent = {(rid, d): s for rid, d, s in _entries_range(day - timedelta(days=2), day)}
        # 睡眠・気分は1回のレンジ取得でまとめる（get_daily_log を3回叩かない）
        _dl = {d: (sh, mm, mn) for d, sh, mm, mn in _daily_logs_range(day - timedelta(days=2), day)}
        logs = {d: _dl.get(d, (None, None, None)) for d in disp_days}
        weights = dict(_weight_logs())  # 体重タブと同じ WeightLog を参照

        st.caption("編集中は保存されません。まとめて入力し、下の「保存」を押してください。")
        day_submits = {}
        with st.form("today_form"):
            with st.container(key="today3"):
                cols = st.columns(3, gap="small")
                for i, d in enumerate(disp_days):
                    with cols[i]:
                        with st.container(border=True):
                            head = f"{d.month}/{d.day}（{DOW[d.weekday()]}）"
                            st.markdown(f"**{head}**" + ("　·　選択中" if d == day else ""))

                            _wt = weights.get(d)
                            _widx = WEIGHT_OPTIONS.index(_wt) if _wt in WEIGHT_OPTIONS else None
                            st.selectbox(
                                "体重(kg)" if _wt is not None else "体重(kg)（未入力）",
                                WEIGHT_OPTIONS,
                                index=_widx,
                                format_func=lambda x: f"{x:.1f}",
                                key=f"f_weight_{d.isoformat()}",
                                placeholder="選択",
                            )

                            _sleep = logs[d][0]
                            _sidx = SLEEP_OPTIONS.index(_sleep) if _sleep in SLEEP_OPTIONS else None
                            st.selectbox(
                                "睡眠(h)" if _sleep is not None else "睡眠(h)（未入力）",
                                SLEEP_OPTIONS,
                                index=_sidx,
                                format_func=lambda x: f"{x:.1f}",
                                key=f"f_sleep_{d.isoformat()}",
                                placeholder="選択",
                            )
                            _mm, _mn = logs[d][1], logs[d][2]
                            st.segmented_control(
                                "朝の気分" if _mm is not None else "朝の気分（未入力）",
                                options=services.MOOD_ORDER,
                                format_func=lambda m: f"{MOOD_EMOJI[m]} {services.MOOD_LABELS[m]}",
                                default=_mm,
                                key=f"f_moodm_{d.isoformat()}",
                            )
                            st.segmented_control(
                                "夜の気分" if _mn is not None else "夜の気分（未入力）",
                                options=services.MOOD_ORDER,
                                format_func=lambda m: f"{MOOD_EMOJI[m]} {services.MOOD_LABELS[m]}",
                                default=_mn,
                                key=f"f_moodn_{d.isoformat()}",
                            )

                            for r in routines:
                                st.segmented_control(
                                    r.name,
                                    options=services.STATUS_ORDER,
                                    format_func=lambda s: f"{STATUS_SYMBOL[s]} {SHORT_STATUS[s]}",
                                    default=ent.get((r.id, d)),
                                    key=f"f_seg_{r.id}_{d.isoformat()}",
                                )

                            # この日だけを登録するボタン（各カード末尾）
                            # ラベルは日付入りで一意にする（form_submit_button はラベルからキーを生成するため）
                            day_submits[d] = st.form_submit_button(
                                f"{d.month}/{d.day} を登録",
                                type="primary",
                                use_container_width=True,
                            )

            submitted = st.form_submit_button(
                "3日分を保存", type="primary", use_container_width=True
            )

        if submitted:
            for d in disp_days:
                _save_day(d, routines)
            st.cache_data.clear()
            st.success("3日分を保存しました。")
            st.rerun()
        else:
            for d, clicked in day_submits.items():
                if clicked:
                    _save_day(d, routines)
                    st.cache_data.clear()
                    st.success(f"{d.month}/{d.day} の1日分を保存しました。")
                    st.rerun()
                    break

    st.markdown(legend_html(), unsafe_allow_html=True)


with tab_heat:
    days = st.radio("表示期間", [30, 60, 90], horizontal=True, format_func=lambda d: f"{d}日")
    end = db.today()
    active = _routines(False)
    st.markdown(render_heatmap(active, days, end, show_daily=True), unsafe_allow_html=True)
    st.caption("⬍ 縦スクロールで過去の日付まで辿れます")

    archived = [r for r in _routines(True) if r.archived]
    if archived:
        with st.expander(f"アーカイブ済み（{len(archived)}件）"):
            st.markdown(render_heatmap(archived, days, end), unsafe_allow_html=True)

    st.markdown(legend_html(with_daily=True), unsafe_allow_html=True)


with tab_manage:
    st.caption("表を直接編集できます。編集中は保存されません。行の追加・名前変更・並び順・アーカイブをまとめて行い、最後に「保存」を押してください。")
    all_routines = _routines(True)
    import pandas as pd

    df = pd.DataFrame(
        [
            {"id": r.id, "ルーティン名": r.name, "並び順": r.sort_order, "アーカイブ": r.archived}
            for r in all_routines
        ],
        columns=["id", "ルーティン名", "並び順", "アーカイブ"],
    )
    # フォームで囲むことで、セル編集ごとの再実行・保存を止め、「保存」押下時のみ確定する。
    with st.form("routine_form"):
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("id", disabled=True),
                "ルーティン名": st.column_config.TextColumn("ルーティン名", required=True),
                "並び順": st.column_config.NumberColumn("並び順", min_value=0, step=1),
                "アーカイブ": st.column_config.CheckboxColumn("アーカイブ"),
            },
            key="routine_editor",
        )
        submitted = st.form_submit_button("保存", type="primary")

    if submitted:
        rows = [
            {
                "id": row["id"],
                "name": row["ルーティン名"],
                "sort_order": row["並び順"],
                "archived": row["アーカイブ"],
            }
            for row in edited.to_dict("records")
        ]
        services.apply_routine_edits(rows, all_routines)
        st.cache_data.clear()
        st.success("保存しました。")
        st.rerun()


with tab_weight:
    # 記録フォーム（保存ボタン方式）
    with st.form("weight_form"):
        wc1, wc2, wc3 = st.columns([2, 2, 1])
        w_day = wc1.date_input("日付", value=db.today(), format="YYYY/MM/DD")
        existing = dict(_weight_logs()).get(w_day)
        idx = WEIGHT_OPTIONS.index(existing) if existing in WEIGHT_OPTIONS else None
        w_val = wc2.selectbox(
            "体重 (kg)",
            WEIGHT_OPTIONS,
            index=idx,
            format_func=lambda x: f"{x:.1f}",
            placeholder="選択",
        )
        wc3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        rec = wc3.form_submit_button("記録", type="primary")
    if rec:
        if w_val is None:
            st.warning("体重を選択してください。")
        else:
            db.set_weight(w_day, w_val)
            st.cache_data.clear()
            st.success(f"{w_day.isoformat()} の体重を {w_val:.1f} kg で記録しました。")
            st.rerun()

    # 目標設定
    target_w, target_d = _weight_goal()
    with st.expander("目標を設定"):
        with st.form("weight_goal_form"):
            gc1, gc2 = st.columns(2)
            g_w = gc1.number_input(
                "目標体重 (kg)", min_value=0.0, max_value=300.0, step=0.1,
                value=target_w if target_w is not None else 55.0,
            )
            g_d = gc2.date_input(
                "目標日", value=target_d if target_d else (db.today() + timedelta(days=90)),
                format="YYYY/MM/DD",
            )
            if st.form_submit_button("目標を保存", type="primary"):
                db.set_weight_goal(g_w, g_d)
                st.cache_data.clear()
                st.success("目標を保存しました。")
                st.rerun()

    # グラフ
    logs = _weight_logs()
    if not logs:
        st.info("体重を記録するとグラフが表示されます。")
    else:
        series = services.weight_series(logs, target_w, target_d)
        fig = go.Figure()
        ax = [d for d, _w in series["actual"]]
        ay = [w for _d, w in series["actual"]]
        fig.add_trace(
            go.Scatter(x=ax, y=ay, mode="lines+markers", name="実績体重",
                       line=dict(color="#378ADD", width=2),
                       hovertemplate="%{y:.1f} kg<extra>実績体重</extra>")
        )
        if series["target"]:
            tx = [d for d, _w in series["target"]]
            ty = [w for _d, w in series["target"]]
            fig.add_trace(
                go.Scatter(x=tx, y=ty, mode="lines", name="目標ライン",
                           line=dict(color="#E24B4A", width=2, dash="dash"),
                           hovertemplate="%{y:.1f} kg<extra>目標ライン</extra>")
            )
        if series["forecast"]:
            fx = [d for d, _w in series["forecast"]]
            fy = [w for _d, w in series["forecast"]]
            fig.add_trace(
                go.Scatter(x=fx, y=fy, mode="lines", name="予測トレンド",
                           line=dict(color="#639922", width=2, dash="dot"),
                           hovertemplate="%{y:.1f} kg<extra>予測トレンド</extra>")
            )
        fig.update_layout(
            hovermode="x unified",
            height=420,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            yaxis=dict(title="体重 (kg)", tickformat=".1f"),
        )
        st.plotly_chart(fig, use_container_width=True)
