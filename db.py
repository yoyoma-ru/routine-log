"""データ層。

アプリ全体で、DBへの読み書きはこのファイルの関数だけを通す。
SQL/ORM を書くのはここに限定し、画面側(app.py)・処理層(services.py)は
意味のある関数を呼ぶだけにする。

- 接続先: 環境変数 DATABASE_URL（Neon Postgres）。.env に置く（リポジトリには含めない）。
- 日付は date 型で保持。「今日」は JST 基準（today() 参照）。
- status は 'done'(完了) / 'small'(最低限行動) / 'none'(行動してない) の3値。
  未記入は「Entry レコードが存在しない」状態で表す。
"""

import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()

JST = timezone(timedelta(hours=9))

# 有効な status 値（未記入は Entry 不在で表すのでここには含めない）
VALID_STATUSES = ("done", "small", "none")


def today() -> date:
    """JST の今日を date で返す。"""
    return datetime.now(JST).date()


def now_jst() -> datetime:
    """JST の現在時刻（created_at / archived_at 用、naive で保持）。"""
    return datetime.now(JST).replace(tzinfo=None)


# --- 接続 -------------------------------------------------------------------

def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL が設定されていません。.env に Neon の接続文字列を設定してください"
            "（.env.example 参照）。"
        )
    return url


# engine / Session はモジュール初回 import 時に1つだけ作る。
_engine = create_engine(_database_url(), pool_pre_ping=True)
Session = sessionmaker(bind=_engine, expire_on_commit=False)


# --- モデル -----------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now_jst)


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("routine_id", "date", name="uq_routine_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    routine_id: Mapped[int] = mapped_column(
        ForeignKey("routines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # done|small|none
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DailyLog(Base):
    """1日ごとのコンディション記録（睡眠時間・気分）。ルーティンとは独立。"""

    __tablename__ = "daily_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    mood: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'good'|'bad'


def init_db() -> None:
    """全テーブルを作成（既存ならスキップ）。init_db.py から呼ぶ。"""
    Base.metadata.create_all(_engine)


# --- Routine の CRUD --------------------------------------------------------

def list_routines(include_archived: bool = False) -> list[Routine]:
    """ルーティン一覧を sort_order, id 順で返す。既定では現役のみ。"""
    with Session() as s:
        stmt = select(Routine)
        if not include_archived:
            stmt = stmt.where(Routine.archived.is_(False))
        stmt = stmt.order_by(Routine.sort_order, Routine.id)
        return list(s.scalars(stmt).all())


def add_routine(name: str, sort_order: int | None = None) -> Routine:
    """ルーティンを追加して返す。sort_order 省略時は末尾に置く。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("ルーティン名が空です。")
    with Session() as s:
        if sort_order is None:
            current_max = s.scalar(select(Routine.sort_order).order_by(Routine.sort_order.desc()))
            sort_order = (current_max or 0) + 1
        r = Routine(name=name, sort_order=sort_order)
        s.add(r)
        s.commit()
        s.refresh(r)
        return r


def update_routine(
    routine_id: int,
    *,
    name: str | None = None,
    sort_order: int | None = None,
    archived: bool | None = None,
) -> None:
    """ルーティンの属性を部分更新する。archived の切替で archived_at も整合させる。"""
    with Session() as s:
        r = s.get(Routine, routine_id)
        if r is None:
            return
        if name is not None:
            new_name = name.strip()
            if new_name:
                r.name = new_name
        if sort_order is not None:
            r.sort_order = int(sort_order)
        if archived is not None and archived != r.archived:
            r.archived = archived
            r.archived_at = now_jst() if archived else None
        s.commit()


# --- Entry の CRUD（upsert / 取り消し）-------------------------------------

def set_entry(routine_id: int, day: date, status: str | None) -> None:
    """指定日のルーティンの記録を設定する。

    - status が VALID_STATUSES のいずれか → upsert（無ければ作成、有れば更新）
    - status が None → その日の記録を削除（＝未記入に戻す）
    """
    with Session() as s:
        existing = s.scalar(
            select(Entry).where(Entry.routine_id == routine_id, Entry.date == day)
        )
        if status is None:
            if existing is not None:
                s.delete(existing)
                s.commit()
            return
        if status not in VALID_STATUSES:
            raise ValueError(f"不正な status: {status!r}")
        if existing is None:
            s.add(Entry(routine_id=routine_id, date=day, status=status))
        else:
            existing.status = status
        s.commit()


def get_entries_for_day(day: date) -> dict[int, str]:
    """指定日の {routine_id: status} を返す。記録のないルーティンは含まれない。"""
    with Session() as s:
        rows = s.execute(
            select(Entry.routine_id, Entry.status).where(Entry.date == day)
        ).all()
        return {rid: status for rid, status in rows}


def get_entries_range(start: date, end: date) -> list[tuple[int, date, str]]:
    """[start, end]（両端含む）の全エントリを (routine_id, date, status) で返す。"""
    with Session() as s:
        rows = s.execute(
            select(Entry.routine_id, Entry.date, Entry.status)
            .where(Entry.date >= start, Entry.date <= end)
            .order_by(Entry.date)
        ).all()
        return [(rid, d, status) for rid, d, status in rows]


def get_all_entries() -> list[tuple[int, date, str]]:
    """全期間の全エントリを (routine_id, date, status) で返す（集計用）。"""
    with Session() as s:
        rows = s.execute(
            select(Entry.routine_id, Entry.date, Entry.status).order_by(Entry.date)
        ).all()
        return [(rid, d, status) for rid, d, status in rows]


# --- DailyLog（睡眠時間・気分）---------------------------------------------

VALID_MOODS = ("good", "bad")


def get_daily_log(day: date) -> tuple[float | None, str | None]:
    """指定日の (sleep_hours, mood) を返す。未記入は (None, None)。"""
    with Session() as s:
        r = s.scalar(select(DailyLog).where(DailyLog.date == day))
        if r is None:
            return (None, None)
        return (r.sleep_hours, r.mood)


def _set_daily_field(day: date, field: str, value) -> None:
    """DailyLog の1フィールドを upsert する。両フィールドとも空なら行を削除。"""
    with Session() as s:
        r = s.scalar(select(DailyLog).where(DailyLog.date == day))
        if r is None:
            if value is None:
                return
            r = DailyLog(date=day)
            setattr(r, field, value)
            s.add(r)
            s.commit()
            return
        setattr(r, field, value)
        if r.sleep_hours is None and r.mood is None:
            s.delete(r)
        s.commit()


def set_sleep(day: date, hours: float | None) -> None:
    """睡眠時間（時間）を保存。None で記録取消。"""
    _set_daily_field(day, "sleep_hours", hours)


def set_mood(day: date, mood: str | None) -> None:
    """気分（'good'|'bad'）を保存。None で記録取消。"""
    if mood is not None and mood not in VALID_MOODS:
        raise ValueError(f"不正な mood: {mood!r}")
    _set_daily_field(day, "mood", mood)


def get_daily_logs_range(start: date, end: date) -> list[tuple[date, float | None, str | None]]:
    """[start, end] の DailyLog を (date, sleep_hours, mood) で返す（集計用）。"""
    with Session() as s:
        rows = s.execute(
            select(DailyLog.date, DailyLog.sleep_hours, DailyLog.mood)
            .where(DailyLog.date >= start, DailyLog.date <= end)
            .order_by(DailyLog.date)
        ).all()
        return [(d, sh, m) for d, sh, m in rows]
