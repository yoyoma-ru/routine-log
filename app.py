"""フロントエンド（Streamlit UI）。

画面の組み立てと入力受付・表示だけを行い、集計やDB操作は services / db に委ねる。
タブ構成: 今日 / ヒートマップ / 集計・傾向 / ルーティン管理。
"""

import streamlit as st

st.set_page_config(page_title="routine-log", page_icon="🌱", layout="wide")

# DATABASE_URL 未設定や接続不可は、画面上で分かりやすく案内する。
try:
    import db
    import services
except RuntimeError as e:
    st.error(str(e))
    st.info("`.env` に Neon の DATABASE_URL を設定し、`python init_db.py` を実行してください。")
    st.stop()


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
  border-bottom:1px solid currentColor;font-size:13px;
  display:flex;align-items:flex-start;justify-content:center;padding:6px 0;
  writing-mode:vertical-rl;text-orientation:upright;letter-spacing:1px;white-space:nowrap;overflow:hidden;}
.rl-date{position:sticky;left:0;z-index:1;background:var(--background-color);
  border-right:1px solid currentColor;border-bottom:0.5px solid rgba(128,128,128,.35);
  display:flex;align-items:center;padding:0 8px;font-size:11px;white-space:nowrap;opacity:.85;}
.rl-date.today{opacity:1;font-weight:600;}
.rl-cell{border-bottom:0.5px solid rgba(128,128,128,.35);border-right:0.5px solid rgba(128,128,128,.35);
  display:flex;align-items:center;justify-content:center;padding:3px;box-sizing:border-box;}
.rl-mark{width:100%;height:100%;box-sizing:border-box;}
.rl-done{background:currentColor;}
.rl-small{background:linear-gradient(135deg,currentColor 0 50%,transparent 50% 100%);}
.rl-none{display:flex;align-items:center;justify-content:center;font-size:13px;line-height:1;}
.rl-strip{display:flex;align-items:center;gap:8px;margin:3px 0;}
.rl-strip-name{width:120px;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.rl-strip-cells{display:flex;}
.rl-scell{width:18px;height:18px;border:0.5px solid rgba(128,128,128,.4);box-sizing:border-box;
  display:flex;align-items:center;justify-content:center;font-size:11px;line-height:1;}
.rl-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:10px;font-size:12px;opacity:.8;}
.rl-legend .box{width:16px;height:16px;border:0.5px solid rgba(128,128,128,.5);display:inline-flex;
  align-items:center;justify-content:center;vertical-align:-3px;margin-right:5px;font-size:11px;}
</style>
"""

CELL = 26
DATEW = 84


def _mark_html(status: str | None) -> str:
    if status == "done":
        return '<div class="rl-mark rl-done"></div>'
    if status == "small":
        return '<div class="rl-mark rl-small"></div>'
    if status == "none":
        return '<div class="rl-mark rl-none">✕</div>'
    return ""  # 未記入


def render_heatmap(routines: list, days: int, end) -> str:
    """方眼紙スタイルのヒートマップ HTML を返す（行=日付・列=ルーティン・縦書き見出し）。"""
    if not routines:
        return "<p style='opacity:.7'>表示できるルーティンがありません。</p>"
    dates, matrix = services.heatmap_matrix(routines, days, end)
    cols = f"{DATEW}px " + " ".join([f"{CELL}px"] * len(routines))
    cells = [f'<div class="rl-corner">日付＼行動</div>']
    head_h = 96
    for r in routines:
        cells.append(f'<div class="rl-head" style="height:{head_h}px" title="{r.name}">{r.name}</div>')
    dow = ["月", "火", "水", "木", "金", "土", "日"]
    today = db.today()
    for d in dates:
        cls = "rl-date today" if d == today else "rl-date"
        label = f'{d.month}/{d.day} <span style="opacity:.6;margin-left:3px">{dow[d.weekday()]}</span>'
        cells.append(f'<div class="{cls}" style="height:{CELL}px">{label}</div>')
        for r in routines:
            status = matrix[r.id].get(d)
            cells.append(f'<div class="rl-cell" style="height:{CELL}px">{_mark_html(status)}</div>')
    grid = f'<div class="rl-grid" style="grid-template-columns:{cols}">' + "".join(cells) + "</div>"
    return f'<div class="rl-wrap">{grid}</div>'


def render_strip(routines: list, days: int, end) -> str:
    """今日タブ用のコンパクトな横ストリップ（行=ルーティン・列=直近N日）。"""
    if not routines:
        return ""
    dates, matrix = services.heatmap_matrix(routines, days, end)
    dates = list(reversed(dates))  # 左=古い → 右=今日
    rows = []
    for r in routines:
        scells = []
        for d in dates:
            scells.append(f'<div class="rl-scell">{_mark_html(matrix[r.id].get(d))}</div>')
        rows.append(
            f'<div class="rl-strip"><div class="rl-strip-name">{r.name}</div>'
            f'<div class="rl-strip-cells">{"".join(scells)}</div></div>'
        )
    return "".join(rows)


def legend_html() -> str:
    return (
        '<div class="rl-legend">'
        '<span><span class="box rl-done"></span>完了</span>'
        '<span><span class="box rl-small"></span>最低限行動</span>'
        '<span><span class="box">✕</span>行動してない</span>'
        '<span><span class="box"></span>未記入</span>'
        "</div>"
    )


# ---- コールバック ----------------------------------------------------------

def _save_entry(rid: int, day, key: str):
    db.set_entry(rid, day, st.session_state.get(key))


def _save_reflection(day, key: str):
    db.upsert_reflection(day, st.session_state.get(key, ""))


# ---- タブ本体 --------------------------------------------------------------

st.markdown(HEATMAP_CSS, unsafe_allow_html=True)
st.title("🌱 routine-log")

tab_today, tab_heat, tab_stats, tab_manage = st.tabs(
    ["今日", "ヒートマップ", "集計・傾向", "ルーティン管理"]
)


with tab_today:
    day = st.date_input("日付", value=db.today(), format="YYYY/MM/DD")
    routines = db.list_routines()

    if not routines:
        st.info("まだルーティンがありません。例から追加して始めましょう。")
        st.write("、".join(services.EXAMPLE_ROUTINES))
        if st.button("例のルーティンを追加", type="primary"):
            for i, name in enumerate(services.EXAMPLE_ROUTINES):
                db.add_routine(name, sort_order=i + 1)
            st.rerun()
    else:
        recorded, total = services.today_progress(day, routines)
        streak = services.current_streak(day)
        c1, c2 = st.columns(2)
        c1.metric("今日の記録", f"{recorded} / {total}")
        c2.metric("連続行動日数", f"{streak} 日")

        st.caption("直近2週間")
        st.markdown(render_strip(routines, 14, day), unsafe_allow_html=True)

        st.divider()
        st.caption("ルーティン（タップで即保存）")
        current = db.get_entries_for_day(day)
        for r in routines:
            key = f"seg_{r.id}_{day.isoformat()}"
            st.segmented_control(
                r.name,
                options=services.STATUS_ORDER,
                format_func=lambda s: services.STATUS_LABELS[s],
                default=current.get(r.id),
                key=key,
                on_change=_save_entry,
                args=(r.id, day, key),
            )

        st.divider()
        rkey = f"reflect_{day.isoformat()}"
        st.text_area(
            "今日のふりかえり",
            value=db.get_reflection(day),
            key=rkey,
            on_change=_save_reflection,
            args=(day, rkey),
            placeholder="気づいたこと・明日への一言など",
        )

    st.markdown(legend_html(), unsafe_allow_html=True)


with tab_heat:
    days = st.radio("表示期間", [30, 60, 90], horizontal=True, format_func=lambda d: f"{d}日")
    end = db.today()
    active = db.list_routines()
    st.markdown(render_heatmap(active, days, end), unsafe_allow_html=True)
    st.caption("⬍ 縦スクロールで過去の日付まで辿れます")

    archived = [r for r in db.list_routines(include_archived=True) if r.archived]
    if archived:
        with st.expander(f"アーカイブ済み（{len(archived)}件）"):
            st.markdown(render_heatmap(archived, days, end), unsafe_allow_html=True)

    st.markdown(legend_html(), unsafe_allow_html=True)


with tab_stats:
    end = db.today()
    active = db.list_routines()
    if not active:
        st.info("ルーティンを追加すると集計が表示されます。")
    else:
        st.dataframe(services.summarize(active, end), hide_index=True, use_container_width=True)

    archived = [r for r in db.list_routines(include_archived=True) if r.archived]
    if archived:
        with st.expander(f"アーカイブ済み（{len(archived)}件）"):
            st.dataframe(
                services.summarize(archived, end), hide_index=True, use_container_width=True
            )


with tab_manage:
    st.caption("表を直接編集できます。行の追加・名前変更・並び順・アーカイブをまとめて行い、保存してください。")
    all_routines = db.list_routines(include_archived=True)
    import pandas as pd

    df = pd.DataFrame(
        [
            {"id": r.id, "ルーティン名": r.name, "並び順": r.sort_order, "アーカイブ": r.archived}
            for r in all_routines
        ],
        columns=["id", "ルーティン名", "並び順", "アーカイブ"],
    )
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
    if st.button("保存", type="primary"):
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
        st.success("保存しました。")
        st.rerun()
