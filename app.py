"""フロントエンド（Streamlit UI）。

画面の組み立てと入力受付・表示だけを行い、集計やDB操作は services / db に委ねる。
タブ構成: 今日 / ヒートマップ / 集計・傾向 / ルーティン管理。
"""

from datetime import timedelta

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="routine-log", page_icon="🌱", layout="wide")

# 別アプリ（学習記録）を埋め込むタブのURL。?embed=true でヘッダ等を外した埋め込み表示にする。
STUDY_APP_URL = "https://my-study-app-yoyo.streamlit.app/?embed=true"

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
  display:flex;align-items:center;padding:0 6px;font-size:11px;white-space:nowrap;opacity:.85;}
.rl-date.today{opacity:1;font-weight:600;}
.rl-cell{border-bottom:0.5px solid rgba(128,128,128,.35);border-right:0.5px solid rgba(128,128,128,.35);
  display:flex;align-items:center;justify-content:center;padding:3px;box-sizing:border-box;}
.rl-mark{width:100%;height:100%;box-sizing:border-box;}
.rl-done{background:currentColor;}
.rl-small{background:linear-gradient(135deg,currentColor 0 50%,transparent 50% 100%);}
.rl-none{display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;line-height:1;}
.rl-mood{display:flex;align-items:center;justify-content:center;font-size:18px;line-height:1;}
.rl-num{font-size:12px;font-variant-numeric:tabular-nums;}
.rl-stripgrid{display:grid;align-items:center;overflow-x:auto;}
.rl-saxis{font-size:10px;opacity:.7;text-align:center;padding-bottom:3px;white-space:nowrap;}
.rl-strip-name{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:8px;}
.rl-scell{height:22px;border:0.5px solid rgba(128,128,128,.4);box-sizing:border-box;
  display:flex;align-items:center;justify-content:center;}
.rl-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:10px;font-size:12px;opacity:.8;}
.rl-legend .box{width:16px;height:16px;border:0.5px solid rgba(128,128,128,.5);display:inline-flex;
  align-items:center;justify-content:center;vertical-align:-3px;margin-right:5px;font-size:11px;}
</style>
"""

CELL = 26
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
MOOD_SYMBOL = {"good": "☺", "bad": "☹"}


def _mood_html(mood: str | None) -> str:
    if mood == "good":
        return '<div class="rl-mark rl-mood">☺</div>'
    if mood == "bad":
        return '<div class="rl-mark rl-mood">☹</div>'
    return ""  # 未記入


SLEEPW = 44  # 睡眠時間の列幅
MOODW = 30   # 気分の列幅


def render_heatmap(routines: list, days: int, end, show_daily: bool = False) -> str:
    """方眼紙スタイルのヒートマップ HTML を返す（行=日付・列=ルーティン・縦書き見出し）。

    show_daily=True のとき、右端に「睡眠時間（数値）」「気分（☺/☹）」の列を足す。
    睡眠・気分は日付ごとの記録（ルーティン非依存）なので現役ヒートマップにのみ表示する。
    """
    if not routines:
        return "<p style='opacity:.7'>表示できるルーティンがありません。</p>"
    dates, matrix = services.heatmap_matrix(routines, days, end)
    daily = {}
    if show_daily:
        daily = {d: (sh, m) for d, sh, m in db.get_daily_logs_range(dates[-1], dates[0])}

    cols = f"{DATEW}px " + " ".join([f"{CELL}px"] * len(routines))
    if show_daily:
        cols += f" {SLEEPW}px {MOODW}px"

    head_h = 96
    cells = [f'<div class="rl-corner">日付＼行動</div>']
    for r in routines:
        cells.append(f'<div class="rl-head" style="height:{head_h}px" title="{r.name}">{r.name}</div>')
    if show_daily:
        cells.append(f'<div class="rl-head" style="height:{head_h}px">睡眠</div>')
        cells.append(f'<div class="rl-head" style="height:{head_h}px">気分</div>')

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
            sh, m = daily.get(d, (None, None))
            sleep_txt = f"{sh:g}" if sh is not None else ""
            cells.append(f'<div class="rl-cell rl-num" style="height:{CELL}px">{sleep_txt}</div>')
            cells.append(f'<div class="rl-cell" style="height:{CELL}px">{_mood_html(m)}</div>')
    grid = f'<div class="rl-grid" style="grid-template-columns:{cols}">' + "".join(cells) + "</div>"
    return f'<div class="rl-wrap">{grid}</div>'


def render_strip(routines: list, days: int, end) -> str:
    """今日タブ用のコンパクトな横ストリップ（行=ルーティン・列=直近N日）。

    日付は左=古い → 右=最新。上端に日付ラベル（曜日なし。月初は M/D、それ以外は日のみ）。
    """
    if not routines:
        return ""
    dates, matrix = services.heatmap_matrix(routines, days, end)
    dates = list(reversed(dates))  # 左=古い → 右=今日
    name_w, sc = 120, 28
    cols = f"{name_w}px " + " ".join([f"{sc}px"] * len(dates))

    cells = ['<div></div>']  # 日付軸の左端（名前列の上）
    prev_month = None
    for d in dates:
        label = f"{d.month}/{d.day}" if d.month != prev_month else f"{d.day}"
        prev_month = d.month
        cells.append(f'<div class="rl-saxis">{label}</div>')
    for r in routines:
        cells.append(f'<div class="rl-strip-name" title="{r.name}">{r.name}</div>')
        for d in dates:
            cells.append(f'<div class="rl-scell">{_mark_html(matrix[r.id].get(d))}</div>')

    return f'<div class="rl-stripgrid" style="grid-template-columns:{cols}">' + "".join(cells) + "</div>"


def legend_html(with_daily: bool = False) -> str:
    items = (
        '<span><span class="box rl-done"></span>完了</span>'
        '<span><span class="box rl-small"></span>最低限行動</span>'
        '<span><span class="box">✕</span>行動してない</span>'
        '<span><span class="box"></span>未記入</span>'
    )
    if with_daily:
        items += (
            '<span><span class="box rl-mood">☺</span>気分：良い</span>'
            '<span><span class="box rl-mood">☹</span>気分：悪い</span>'
            "<span>睡眠：時間（数値）</span>"
        )
    return f'<div class="rl-legend">{items}</div>'


# ---- タブ本体 --------------------------------------------------------------

st.markdown(HEATMAP_CSS, unsafe_allow_html=True)
st.title("🌱 routine-log")

tab_today, tab_heat, tab_stats, tab_manage, tab_weight, tab_study = st.tabs(
    ["今日", "ヒートマップ", "集計・傾向", "ルーティン管理", "体重", "学習"]
)


DOW = ["月", "火", "水", "木", "金", "土", "日"]
COLW = [1.5, 1, 1, 1]  # [ルーティン名, 各日×3]


with tab_today:
    day = st.date_input(
        "基準日", value=db.today(), format="YYYY/MM/DD", help="この日＋前2日の3日分を表示します"
    )
    routines = db.list_routines()

    if not routines:
        st.info("まだルーティンがありません。例から追加して始めましょう。")
        st.write("、".join(services.EXAMPLE_ROUTINES))
        if st.button("例のルーティンを追加", type="primary"):
            for i, name in enumerate(services.EXAMPLE_ROUTINES):
                db.add_routine(name, sort_order=i + 1)
            st.rerun()
    else:
        st.caption("直近2週間")
        st.markdown(render_strip(routines, 14, day), unsafe_allow_html=True)
        st.divider()

        # 選択日＋前2日（左=古い → 右=選択日）
        days3 = [day - timedelta(days=2), day - timedelta(days=1), day]
        ent = {(rid, d): s for rid, d, s in db.get_entries_range(days3[0], days3[2])}
        logs = {d: db.get_daily_log(d) for d in days3}

        st.caption("編集中は保存されません。まとめて入力し、下の「保存」を押してください。")
        with st.form("today_form"):
            # ヘッダ（日付）
            hcols = st.columns(COLW)
            hcols[0].markdown("&nbsp;")
            for i, d in enumerate(days3):
                lbl = f"{d.month}/{d.day}（{DOW[d.weekday()]}）"
                hcols[i + 1].markdown(f"**{lbl}** ・選択" if d == day else lbl)

            # コンディション
            st.caption("コンディション")
            scols = st.columns(COLW)
            scols[0].markdown("睡眠(h)")
            for i, d in enumerate(days3):
                scols[i + 1].number_input(
                    "睡眠時間",
                    min_value=0.0,
                    max_value=24.0,
                    step=0.5,
                    value=logs[d][0],
                    key=f"f_sleep_{d.isoformat()}",
                    label_visibility="collapsed",
                    placeholder="7.5",
                )
            mcols = st.columns(COLW)
            mcols[0].markdown("気分")
            for i, d in enumerate(days3):
                mcols[i + 1].segmented_control(
                    "気分",
                    options=services.MOOD_ORDER,
                    format_func=lambda m: MOOD_SYMBOL[m],
                    default=logs[d][1],
                    key=f"f_mood_{d.isoformat()}",
                    label_visibility="collapsed",
                )

            # ルーティン
            st.caption("ルーティン")
            for r in routines:
                rcols = st.columns(COLW)
                rcols[0].markdown(r.name)
                for i, d in enumerate(days3):
                    rcols[i + 1].segmented_control(
                        r.name,
                        options=services.STATUS_ORDER,
                        format_func=lambda s: STATUS_SYMBOL[s],
                        default=ent.get((r.id, d)),
                        key=f"f_seg_{r.id}_{d.isoformat()}",
                        label_visibility="collapsed",
                    )

            submitted = st.form_submit_button("保存", type="primary")

        if submitted:
            for d in days3:
                db.set_sleep(d, st.session_state.get(f"f_sleep_{d.isoformat()}"))
                db.set_mood(d, st.session_state.get(f"f_mood_{d.isoformat()}"))
                for r in routines:
                    db.set_entry(r.id, d, st.session_state.get(f"f_seg_{r.id}_{d.isoformat()}"))
            st.success("3日分を保存しました。")
            st.rerun()

    st.markdown(legend_html(), unsafe_allow_html=True)


with tab_heat:
    days = st.radio("表示期間", [30, 60, 90], horizontal=True, format_func=lambda d: f"{d}日")
    end = db.today()
    active = db.list_routines()
    st.markdown(render_heatmap(active, days, end, show_daily=True), unsafe_allow_html=True)
    st.caption("⬍ 縦スクロールで過去の日付まで辿れます")

    archived = [r for r in db.list_routines(include_archived=True) if r.archived]
    if archived:
        with st.expander(f"アーカイブ済み（{len(archived)}件）"):
            st.markdown(render_heatmap(archived, days, end), unsafe_allow_html=True)

    st.markdown(legend_html(with_daily=True), unsafe_allow_html=True)


with tab_stats:
    end = db.today()

    cond = services.daily_condition_summary(end, days=30)
    st.caption("睡眠・気分（直近30日）")
    cc1, cc2 = st.columns(2)
    cc1.metric(
        "平均睡眠時間",
        f"{cond['avg_sleep']} 時間" if cond["avg_sleep"] is not None else "—",
        help=f"記録のある {cond['sleep_days']} 日の平均",
    )
    cc2.metric(
        "気分が良い割合",
        f"{cond['good_ratio']}%" if cond["good_ratio"] is not None else "—",
        help=f"記録のある {cond['mood_days']} 日のうち",
    )
    st.divider()

    active = db.list_routines()
    st.caption("ルーティン")
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
    st.caption("表を直接編集できます。編集中は保存されません。行の追加・名前変更・並び順・アーカイブをまとめて行い、最後に「保存」を押してください。")
    all_routines = db.list_routines(include_archived=True)
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
        st.success("保存しました。")
        st.rerun()


with tab_weight:
    # 記録フォーム（保存ボタン方式）
    with st.form("weight_form"):
        wc1, wc2, wc3 = st.columns([2, 2, 1])
        w_day = wc1.date_input("日付", value=db.today(), format="YYYY/MM/DD")
        existing = dict(db.get_weight_logs()).get(w_day)
        w_val = wc2.number_input(
            "体重 (kg)", min_value=0.0, max_value=300.0, step=0.1, value=existing, placeholder="60.0"
        )
        wc3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        rec = wc3.form_submit_button("記録", type="primary")
    if rec:
        db.set_weight(w_day, w_val)
        st.success(f"{w_day.isoformat()} の体重を記録しました。")
        st.rerun()

    # 目標設定
    target_w, target_d = db.get_weight_goal()
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
                st.success("目標を保存しました。")
                st.rerun()

    # グラフ
    logs = db.get_weight_logs()
    if not logs:
        st.info("体重を記録するとグラフが表示されます。")
    else:
        series = services.weight_series(logs, target_w, target_d)
        fig = go.Figure()
        ax = [d for d, _w in series["actual"]]
        ay = [w for _d, w in series["actual"]]
        fig.add_trace(
            go.Scatter(x=ax, y=ay, mode="lines+markers", name="実績体重",
                       line=dict(color="#378ADD", width=2))
        )
        if series["target"]:
            tx = [d for d, _w in series["target"]]
            ty = [w for _d, w in series["target"]]
            fig.add_trace(
                go.Scatter(x=tx, y=ty, mode="lines", name="目標ライン",
                           line=dict(color="#E24B4A", width=2, dash="dash"))
            )
        if series["forecast"]:
            fx = [d for d, _w in series["forecast"]]
            fy = [w for _d, w in series["forecast"]]
            fig.add_trace(
                go.Scatter(x=fx, y=fy, mode="lines", name="予測トレンド",
                           line=dict(color="#639922", width=2, dash="dot"))
            )
        fig.update_layout(
            hovermode="x unified",
            height=420,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
            yaxis_title="体重 (kg)",
        )
        st.plotly_chart(fig, use_container_width=True)


with tab_study:
    st.caption("学習記録アプリ（別アプリを埋め込み表示）")
    components.iframe(STUDY_APP_URL, height=900, scrolling=True)
    st.markdown(
        f"[別タブで開く ↗]({STUDY_APP_URL.replace('?embed=true', '')})",
        unsafe_allow_html=False,
    )
