import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Date, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

_db_dir = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_db_dir, "payments.db")

Base = declarative_base()

def upgrade_database():
    conn = engine.connect()
    inspector = inspect(engine)

    model_map = {
        'payments': Payment,
        'weekly_reports': WeeklyReport,
        'templates': Template,
    }

    for table_name, model in model_map.items():
        if table_name in inspector.get_table_names():
            existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
            for column in model.__table__.columns:
                if column.name not in existing_columns:
                    col_type = column.type.compile(engine.dialect)
                    sql = f'ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}'
                    if not column.nullable:
                        sql += ' NOT NULL DEFAULT '
                        if hasattr(column, 'default') and column.default is not None:
                            def_val = column.default.arg
                            if isinstance(def_val, (int, float)):
                                sql += str(def_val)
                            elif isinstance(def_val, str):
                                sql += f"'{def_val}'"
                            elif callable(def_val):
                                sql += f"'{def_val()}'"
                            else:
                                sql += "'0'"
                        else:
                            if 'CHAR' in col_type or 'TEXT' in col_type:
                                sql += "''"
                            elif 'INT' in col_type or 'REAL' in col_type or 'FLOAT' in col_type:
                                sql += "0"
                            else:
                                sql += "''"
                    conn.execute(sql)
    conn.close()

class Payment(Base):
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False)
    tutor_name = Column(String, nullable=False)
    hours = Column(Float, nullable=False)
    tutor_rate = Column(Float, nullable=False)
    parent_name = Column(String, nullable=False)
    student_name = Column(String, nullable=False)
    receipt_file_id = Column(String, nullable=True)
    receipt_type = Column(String, nullable=True)
    date = Column(DateTime, default=datetime.datetime.now)
    week_start_date = Column(Date, nullable=True)
    status = Column(String, default='pending')
    admin_note = Column(String, nullable=True)
    admin_messages = Column(String, nullable=True)


class WeeklyReport(Base):
    __tablename__ = 'weekly_reports'

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False)
    tutor_name = Column(String, nullable=False)
    week_start_date = Column(Date, nullable=False)
    total_hours = Column(Float, default=0.0)
    total_payment = Column(Float, default=0.0)
    report_generated = Column(DateTime, default=datetime.datetime.now)


class Template(Base):
    __tablename__ = 'templates'

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False)
    display_name = Column(String, nullable=False)
    hours = Column(Float, nullable=False)
    parent_name = Column(String, nullable=False)
    student_name = Column(String, nullable=False)
    tutor_rate = Column(Float, nullable=False)

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, unique=True, nullable=False)
    tutor_name = Column(String, nullable=False)
    registered_at = Column(DateTime, default=datetime.datetime.now)
    last_active = Column(DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)


engine = create_engine(f"sqlite:///{_db_path.replace(chr(92), '/')}", echo=False)


def check_and_update_database():
    inspector = inspect(engine)

    if not inspector.has_table('payments'):
        Base.metadata.create_all(engine)
        print("Созданы таблицы payments и weekly_reports (новая база)")
        return

    conn = engine.connect()

    try:
        existing_cols = {col['name'] for col in inspector.get_columns('payments')}

        required = {
            'tutor_rate': 'FLOAT',
            'week_start_date': 'DATE',
            'receipt_type': 'TEXT',
        }

        for col_name, col_type in required.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(f'ALTER TABLE payments ADD COLUMN {col_name} {col_type}')
                    print(f"Добавлен столбец: {col_name} ({col_type})")
                except Exception as e:
                    print(f"Не удалось добавить столбец {col_name}: {e}")

        for col in ['lesson_cost', 'company_profit']:
            if col in existing_cols:
                try:
                    conn.execute(f'ALTER TABLE payments DROP COLUMN {col}')
                    print(f"Удалён столбец: {col}")
                except Exception as e:
                    print(f"Не удалось удалить столбец {col}: {e}")

        if not inspector.has_table('weekly_reports'):
            WeeklyReport.__table__.create(engine)
            print("Создана таблица weekly_reports")

        if not inspector.has_table('templates'):
            Template.__table__.create(engine)
            print("Создана таблица templates")

        if not inspector.has_table('users'):
            User.__table__.create(engine)
            print("Создана таблица users")

    finally:
        conn.close()


check_and_update_database()

Session = sessionmaker(bind=engine)


def get_session():
    return Session()


def get_week_start_date(date=None):
    if date is None:
        date = datetime.date.today()
    return date - datetime.timedelta(days=date.weekday())


def get_week_end_date(week_start):
    return week_start + datetime.timedelta(days=6)


def get_week_range(date=None):
    monday = get_week_start_date(date)
    sunday = get_week_end_date(monday)
    return monday, sunday