import os
from dotenv import load_dotenv


load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')

    YANDEX_DISK_TOKEN = os.getenv('YANDEX_DISK_TOKEN')  # ← добавь эту строку

    @staticmethod
    def get_admins():
        admins = os.getenv('ADMIN_IDS', '').split(',')
        return [int(admin.strip()) for admin in admins if admin.strip().isdigit()]

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in Config.get_admins()


ADMIN_IDS = Config.get_admins()
BOT_TOKEN = Config.BOT_TOKEN