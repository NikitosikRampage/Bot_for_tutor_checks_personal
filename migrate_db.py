import os
import sys
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv

load_dotenv()

# ===================== НАСТРОЙКИ =====================
OLD_DB_PATH = os.environ.get("OLD_DATABASE_PATH")  # путь к старой базе
NEW_DB_PATH = "payments.db"  # новая база

if not OLD_DB_PATH:
    print("❌ Укажите путь к старой базе в .env (OLD_DATABASE_PATH=старый_payments.db)")
    sys.exit(1)

old_url = f"sqlite:///{OLD_DB_PATH}"
new_url = f"sqlite:///{NEW_DB_PATH}"

print(f"Миграция из: {OLD_DB_PATH}")
print(f"В новую базу: {NEW_DB_PATH}\n")
# ====================================================

from database import Base, Payment, Template, User, WeeklyReport

engine_old = create_engine(old_url, echo=False)
engine_new = create_engine(new_url, echo=False)

# Создаём новую структуру
Base.metadata.create_all(engine_new)

insp_old = inspect(engine_old)
insp_new = inspect(engine_new)

tables = [
    ("payments", Payment),
    ("templates", Template),
    ("users", User),
    ("weekly_reports", WeeklyReport),
]

for table_name, model in tables:
    if not insp_old.has_table(table_name):
        print(f"⚠️ Таблица {table_name} отсутствует в старой базе — пропускаем")
        continue

    print(f"📋 Перенос таблицы: {table_name}")

    # Получаем общие колонки
    old_cols = {col["name"] for col in insp_old.get_columns(table_name)}
    new_cols = {col["name"] for col in insp_new.get_columns(table_name)}
    common_cols = old_cols & new_cols

    if not common_cols:
        print(f"   Нет общих колонок — пропускаем")
        continue

    cols_list = ", ".join(sorted(common_cols))
    placeholders = ", ".join(":" + col for col in sorted(common_cols))

    with engine_old.connect() as conn_old:
        result = conn_old.execute(text(f"SELECT {cols_list} FROM {table_name}"))
        rows = result.fetchall()

    if not rows:
        print(f"   Таблица пуста")
        continue

    inserted = 0
    with engine_new.connect() as conn_new:
        for row in rows:
            data = dict(zip(sorted(common_cols), row))
            try:
                conn_new.execute(
                    text(f"INSERT INTO {table_name} ({cols_list}) VALUES ({placeholders})"),
                    data
                )
                inserted += 1
            except Exception as e:
                print(f"   Ошибка при вставке строки: {e}")

        conn_new.commit()

    print(f"   Успешно перенесено: {inserted} записей")

print("\n✅ Миграция завершена!")
print(f"Новая база создана: {NEW_DB_PATH}")