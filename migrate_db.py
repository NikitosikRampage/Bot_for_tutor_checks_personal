import os
import sys
from sqlalchemy import create_engine, inspect, text
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from database import Base, Payment, WeeklyReport, Template, User

OLD_DB = os.environ.get("OLD_DATABASE_PATH", "")
_db_dir = os.path.dirname(os.path.abspath(__file__))
_default_new = f"sqlite:///{os.path.join(_db_dir, 'payments.db').replace(chr(92), '/')}"
NEW_DB = os.environ.get("DATABASE_URL", _default_new)
if not NEW_DB.startswith("sqlite"):
    NEW_DB = _default_new


def get_old_path():
    if OLD_DB:
        path = OLD_DB.replace("sqlite:///", "").strip("/")
        return path
    if len(sys.argv) >= 2:
        return sys.argv[1]
    return None


def migrate(old_path: str, new_url: str = NEW_DB):
    if not os.path.exists(old_path):
        print(f"Ошибка: файл не найден: {old_path}")
        return False
    old_url = f"sqlite:///{old_path}"
    engine_old = create_engine(old_url)
    engine_new = create_engine(new_url)

    Base.metadata.create_all(engine_new)
    insp_old = inspect(engine_old)
    insp_new = inspect(engine_new)

    tables = [
        ("payments", Payment),
        ("weekly_reports", WeeklyReport),
        ("templates", Template),
        ("users", User),
    ]

    for table_name, model in tables:
        if not insp_old.has_table(table_name):
            print(f"  Пропуск {table_name}: нет в старой базе")
            continue
        cols_old = {c["name"] for c in insp_old.get_columns(table_name)}
        cols_new = {c["name"] for c in insp_new.get_columns(table_name)}
        common = cols_old & cols_new
        if not common:
            print(f"  Пропуск {table_name}: нет общих столбцов")
            continue
        cols_list = ", ".join(sorted(common))
        with engine_old.connect() as c_old:
            rows = c_old.execute(text(f"SELECT {cols_list} FROM {table_name}")).fetchall()
        if not rows:
            print(f"  {table_name}: 0 записей")
            continue
        placeholders = ", ".join(":" + c for c in sorted(common))
        insert_sql = f"INSERT OR REPLACE INTO {table_name} ({cols_list}) VALUES ({placeholders})"
        with engine_new.connect() as c_new:
            for row in rows:
                params = dict(zip(sorted(common), row))
                c_new.execute(text(insert_sql), params)
            c_new.commit()
        print(f"  {table_name}: перенесено {len(rows)} записей")
    print("Готово.")
    return True


if __name__ == "__main__":
    old = get_old_path()
    if not old:
        print("Укажите путь к старой базе:")
        print("  python migrate_db.py путь/к/старой_payments.db")
        print("или задайте переменную OLD_DATABASE_PATH в .env")
        sys.exit(1)
    migrate(old)
