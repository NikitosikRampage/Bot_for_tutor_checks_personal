from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Date, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()


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


class WeeklyReport(Base):
    __tablename__ = 'weekly_reports'

    id = Column(Integer, primary_key=True)
    tutor_id = Column(Integer, nullable=False)
    tutor_name = Column(String, nullable=False)
    week_start_date = Column(Date, nullable=False)
    total_hours = Column(Float, default=0.0)
    total_payment = Column(Float, default=0.0)
    report_generated = Column(DateTime, default=datetime.datetime.now)



engine = create_engine('sqlite:///payments.db', echo=False)


def check_and_update_database():
    """Создаёт таблицы, если их нет, и добавляет отсутствующие столбцы"""
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