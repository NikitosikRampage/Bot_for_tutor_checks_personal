import asyncio
import datetime
from datetime import timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.types import InputMediaPhoto, InputMediaDocument, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func

from config import Config, ADMIN_IDS, BOT_TOKEN
from database import Payment, WeeklyReport, get_session, get_week_start_date, get_week_end_date
from keyboards import (
    get_main_keyboard, get_cancel_keyboard, get_admin_keyboard,
    get_pending_actions_keyboard, get_approved_actions_keyboard, get_week_delete_keyboard, get_delete_confirm_keyboard
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class PaymentForm(StatesGroup):
    waiting_for_hours = State()
    waiting_for_names = State()
    waiting_for_tutor_rate = State()
    waiting_for_receipt = State()


class AdminForm(StatesGroup):
    waiting_for_delete_confirm = State()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if Config.is_admin(message.from_user.id):
        await message.answer(
            "Панель администратора\n\n"
            "Команды:\n"
            "/pending   — ожидающие\n"
            "/all       — все платежи\n"
            "/weekly    — отчёты за неделю",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "Бот для учёта оплат репетиторов.\n\n"
            "Нажмите «Добавить оплату»",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.text == "Добавить оплату")
async def start_add_payment(message: Message, state: FSMContext):
    await state.set_state(PaymentForm.waiting_for_hours)
    await message.answer(
        "Шаг 1/4 • Часы\nПример: 1.5, 2, 0.75",
        reply_markup=get_cancel_keyboard()
    )


@dp.message(F.text == "Отмена")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    markup = get_admin_keyboard() if Config.is_admin(message.from_user.id) else get_main_keyboard()
    await message.answer("Отменено.", reply_markup=markup)


@dp.message(PaymentForm.waiting_for_hours)
async def process_hours(message: Message, state: FSMContext):
    try:
        hours = float(message.text.replace(',', '.'))
        if not 0.1 <= hours <= 12:
            await message.answer("От 0.1 до 12 часов")
            return
        await state.update_data(hours=hours)
        await state.set_state(PaymentForm.waiting_for_names)
        await message.answer(
            f"Часы: {hours}\n\n"
            "Шаг 2/4 • Имя родителя и имя ребёнка (через пробел)\nПример: Анна Матвей"
        )
    except ValueError:
        await message.answer("Введите число")


@dp.message(PaymentForm.waiting_for_names)
async def process_names(message: Message, state: FSMContext):
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Нужны имя родителя и имя ребёнка через пробел")
        return
    parent_name = parts[0].strip()
    student_name = ' '.join(parts[1:]).strip()
    if len(parent_name) < 2 or len(student_name) < 2:
        await message.answer("Слишком короткое")
        return
    await state.update_data(parent_name=parent_name, student_name=student_name)
    await state.set_state(PaymentForm.waiting_for_tutor_rate)
    await message.answer(f"Родитель: {parent_name}\nРебёнок: {student_name}\n\nШаг 3/4 • Ваша ставка за занятие (руб)")


@dp.message(PaymentForm.waiting_for_tutor_rate)
async def process_tutor_rate(message: Message, state: FSMContext):
    try:
        rate = float(message.text.replace(',', '.'))
        if rate <= 0:
            await message.answer("Ставка > 0")
            return

        await state.update_data(tutor_rate=rate)
        await state.set_state(PaymentForm.waiting_for_receipt)
        await message.answer(
            f"Ваша ставка: {rate} ₽\n\n"
            "Шаг 4/4 • Отправьте чек"
        )
    except ValueError:
        await message.answer("Введите число")


@dp.message(PaymentForm.waiting_for_receipt, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT}))
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()

    file_id = None
    file_type = None
    if message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"

    if not file_id:
        await message.answer("Нужен фото или документ")
        return

    week_start = get_week_start_date()

    session = None
    try:
        session = get_session()
        payment = Payment(
            tutor_id=message.from_user.id,
            tutor_name=message.from_user.full_name,
            hours=data['hours'],
            tutor_rate=data['tutor_rate'],
            parent_name=data['parent_name'],
            student_name=data['student_name'],
            receipt_file_id=file_id,
            receipt_type=file_type,
            week_start_date=week_start,
            status='pending'
        )
        session.add(payment)
        session.commit()

        pid = payment.id

        await message.answer(
            f"Платёж #{pid} добавлен и отправлен на проверку!\n\n"
            f"Ребёнок: {data['student_name']}\n"
            f"Родитель: {data['parent_name']}\n"
            f"Часы: {data['hours']}\n"
            f"Ставка: {data['tutor_rate']} ₽",
            reply_markup=get_main_keyboard()
        )

        await state.clear()

        await notify_admins_about_new_payment(pid)

    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    finally:
        if session is not None:
            session.close()


async def notify_admins_about_new_payment(payment_id: int):
    session = None
    try:
        session = get_session()
        p = session.get(Payment, payment_id)
        if not p:
            return

        text = (
            f"Новый платёж #{p.id}\n\n"
            f"Репетитор: {p.tutor_name}\n"
            f"Ребёнок:  {p.student_name}\n"
            f"Родитель:      {p.parent_name}\n"
            f"Часы:      {p.hours}\n"
            f"Ставка:    {p.tutor_rate} ₽\n"
            f"Дата:      {p.date.strftime('%d.%m.%Y %H:%M')}"
        )

        markup = get_pending_actions_keyboard(p.id)

        for admin_id in ADMIN_IDS:
            try:
                if p.receipt_type == 'photo':
                    await bot.send_photo(admin_id, p.receipt_file_id, caption=text, reply_markup=markup)
                elif p.receipt_type == 'document':
                    await bot.send_document(admin_id, p.receipt_file_id, caption=text, reply_markup=markup)
                else:
                    await bot.send_message(admin_id, text, reply_markup=markup)
            except Exception as send_err:
                print(f"Не удалось отправить админу {admin_id}: {send_err}")

    except Exception as e:
        print(f"Ошибка при уведомлении админов: {e}")
    finally:
        if session is not None:
            session.close()


@dp.message(F.text == "Мои платежи")
async def show_my_payments(message: Message):
    session = None
    try:
        session = get_session()
        payments = session.query(Payment)\
                          .filter_by(tutor_id=message.from_user.id)\
                          .order_by(Payment.date.desc())\
                          .all()

        if not payments:
            await message.answer("Нет платежей")
            return

        lines = []
        for idx, p in enumerate(payments, 1):
            st = {"pending": "⏳", "approved": "✅"}.get(p.status, "❌")
            lines.append(
                f"#{idx} {st} {p.date.strftime('%d.%m.%y')}\n"
                f"  {p.student_name} • {p.hours} ч • {p.tutor_rate} ₽"
            )

        await message.answer("Ваши платежи:\n\n" + "\n\n".join(lines))

    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    finally:
        if session is not None:
            session.close()

@dp.message(F.text == "Ожидают проверки")
@dp.message(Command("pending"))
async def show_pending(message: Message):
    if not Config.is_admin(message.from_user.id):
        await message.answer("Нет доступа")
        return

    session = None
    try:
        session = get_session()
        pend = session.query(Payment).filter_by(status="pending").order_by(Payment.date.desc()).all()
        if not pend:
            await message.answer("Нет ожидающих")
            return

        await message.answer(f"Ожидают: {len(pend)}")

        for p in pend:
            txt = (
                f"#{p.id}   ⏳\n\n"
                f"Репетитор: {p.tutor_name}\n"
                f"Ребёнок:  {p.student_name}\n"
                f"Родитель:      {p.parent_name}\n"
                f"Часы:      {p.hours}\n"
                f"Ставка:    {p.tutor_rate} ₽"
            )
            await (bot.send_photo if p.receipt_type == "photo" else bot.send_document)(
                message.chat.id, p.receipt_file_id, caption=txt,
                reply_markup=get_pending_actions_keyboard(p.id)
            )
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    finally:
        if session is not None:
            session.close()


@dp.message(F.text == "Все платежи")
@dp.message(Command("all"))
async def show_all_payments(message: Message):
    if not Config.is_admin(message.from_user.id):
        await message.answer("Нет доступа")
        return

    session = None
    try:
        session = get_session()
        payments = session.query(Payment)\
                          .order_by(Payment.tutor_name, Payment.date.desc())\
                          .all()

        if not payments:
            await message.answer("Платежей нет")
            return

        from collections import defaultdict
        grouped = defaultdict(list)
        for p in payments:
            grouped[p.tutor_name].append(p)

        total_payments = len(payments)

        for tutor_name, tutor_payments in grouped.items():
            tutor_count = len(tutor_payments)
            lines = [f"<b>Репетитор: {tutor_name}</b>  ({tutor_count} платежей)\n"]

            total_hours = 0.0
            total_to_pay = 0.0

            for local_num, p in enumerate(tutor_payments, 1):
                if p.receipt_file_id:
                    caption = (
                        f"#{local_num} • {p.date.strftime('%d.%m.%y %H:%M')} • "
                        f"Р: {p.parent_name} / У: {p.student_name} • "
                        f" {p.tutor_rate:.0f} ₽"
                    )

                    markup = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="Удалить", callback_data=f"delete_{p.id}")
                    ]])

                    if p.receipt_type == "photo":
                        await bot.send_photo(
                            chat_id=message.chat.id,
                            photo=p.receipt_file_id,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup
                        )
                    elif p.receipt_type == "document":
                        await bot.send_document(
                            chat_id=message.chat.id,
                            document=p.receipt_file_id,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup
                        )

            for local_num, p in enumerate(tutor_payments, 1):
                st = "⏳" if p.status == "pending" else "✅" if p.status == "approved" else "❌"
                amount = p.hours * p.tutor_rate
                total_hours += p.hours
                total_to_pay += amount

                line = (
                    f"#{local_num} {st} • {p.date.strftime('%d.%m.%y %H:%M')} • "
                    f"{p.parent_name} / {p.student_name} • {p.hours:.2f} ч • "
                    f"{p.tutor_rate:.0f} ₽ \n"
                )
                lines.append(line)

            lines.append(f"\n<b>Итого: </b>{total_to_pay:,.0f} ₽ к выплате")
            text = "\n".join(lines)

            await message.answer(text, parse_mode="HTML")
            await message.answer("─" * 10)

    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        if session is not None:
            session.close()


@dp.message(F.text == "Отчеты за неделю")
@dp.message(Command("weekly"))
async def show_weekly_reports(message: Message):
    if not Config.is_admin(message.from_user.id):
        await message.answer("Нет доступа")
        return

    session = None
    try:
        session = get_session()
        week_start = get_week_start_date()
        week_end = get_week_end_date(week_start)

        tutor_payments = session.query(
            Payment.tutor_id,
            Payment.tutor_name,
            func.sum(Payment.hours * Payment.tutor_rate).label('total_payment')
        ).filter(
            Payment.status == 'approved',
            Payment.date >= datetime.datetime.combine(week_start, datetime.time.min),
            Payment.date <= datetime.datetime.combine(week_end, datetime.time.max)
        ).group_by(Payment.tutor_id, Payment.tutor_name).all()

        if not tutor_payments:
            await message.answer(f"За неделю {week_start:%d.%m.%Y} – {week_end:%d.%m.%Y} данных нет")
            return

        response = f"<b>📊 Отчёт за неделю {week_start:%d.%m.%Y} – {week_end:%d.%m.%Y}</b>\n\n"

        total_week = 0.0
        for tutor_id, tutor_name, total_payment in tutor_payments:
            response += f"Репетитор: {tutor_name}\nК выплате: {total_payment:,.2f} ₽\n\n"
            total_week += total_payment

        response += f"<b>Всего к выплате за неделю: {total_week:,.2f} ₽</b>\n\n"

        response += (
            "<b>💳 Реквизиты для выплат репетиторам</b>\n"
            "\n"
            "Дмитрий Юрьевич Б.     Т-Банк          79234141939\n"
            "Святослав Денисович К.  Сбербанк        79234086564\n"
            "Тимофей Бородин         Сбербанк        2202205387704015\n"
            "Елдудулов Максим А.     Сбербанк        79234361676\n"
            "Виктория Александровна С. Сбербанк      79613314053\n"
        )

        await message.answer(
            response,
            reply_markup=get_week_delete_keyboard(week_start.strftime("%Y-%m-%d")),
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        if session is not None:
            session.close()

@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(callback: CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    session = None
    try:
        payment_id = int(callback.data.split("_")[1])
        session = get_session()
        payment = session.get(Payment, payment_id)
        if not payment:
            await callback.answer("Платеж не найден")
            return

        payment.status = 'approved'
        session.commit()

        await bot.send_message(
            payment.tutor_id,
            f"✅ Ваш платёж подтверждён!\n\n"
            f"ID: #{payment.id}\n"
            f"Ребёнок: {payment.student_name}\n"
            f"Часы: {payment.hours}\n"
            f"Ставка: {payment.tutor_rate} руб\n"
            f"К выплате: {payment.tutor_rate * payment.hours:.2f} руб"
        )

        new_caption = (
            f"✅ Платёж подтверждён\n\n"
            f"ID: #{payment.id}\n"
            f"Репетитор: {payment.tutor_name}\n"
            f"Ребёнок: {payment.student_name}\n"
            f"Родитель: {payment.parent_name}\n"
            f"Часы: {payment.hours}\n"
            f"Ставка: {payment.tutor_rate} руб\n"
            f"Дата: {payment.date.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Подтвердил: {callback.from_user.full_name}\n"
            f"Время: {datetime.datetime.now().strftime('%H:%M')}"
        )

        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=get_approved_actions_keyboard(payment.id)
        )

        await callback.answer("✅ Платёж подтверждён")

        if payment.receipt_file_id:
            try:
                from yadisk import YaDisk
                y = YaDisk(token=Config.YANDEX_DISK_TOKEN)

                file_info = await bot.get_file(payment.receipt_file_id)
                file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

                date_part = payment.date.strftime("%d.%m.%Y")

                filename = f"{date_part}"
                if payment.receipt_type == "photo":
                    filename += ".jpg"
                else:
                    filename += ".pdf"

                month_folder = payment.date.strftime("%Y-%m")
                base_folder = "/Чеки_бот"
                target_folder = f"{base_folder}/{month_folder}"
                disk_path = f"{target_folder}/{filename}"

                for folder in [base_folder, target_folder]:
                    try:
                        y.mkdir(folder, exist_ok=True)
                    except Exception as mkdir_err:
                        print(f"Не удалось создать папку {folder}: {mkdir_err}")

                y.upload_url(file_url, disk_path, overwrite=True)

                print(f"Успешно загружен чек #{payment.id} → {disk_path}")

            except Exception as exp_err:
                print(f"Ошибка экспорта чека #{payment.id}: {str(exp_err)}")


    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}")
    finally:
        if session is not None:
            session.close()


@dp.callback_query(F.data.startswith("reject_"))
async def reject_and_delete(callback: CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    session = None
    try:
        pid = int(callback.data.split("_")[1])
        session = get_session()
        payment = session.get(Payment, pid)
        if not payment:
            await callback.answer("Платеж не найден", show_alert=True)
            return

        tutor_id = payment.tutor_id
        student_name = payment.student_name
        tutor_rate = payment.tutor_rate

        session.delete(payment)
        session.commit()

        await bot.send_message(
            tutor_id,
            f"❌ Ваш платёж отклонён и удалён\n\n"
            f"Ребёнок: {student_name}\n"
            f"Ставка: {tutor_rate} руб\n\n"
            "Добавьте платёж заново после исправления."
        )

        await callback.message.delete()
        await callback.answer("❌ Платёж отклонён и удалён")

    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)
    finally:
        if session is not None:
            session.close()


@dp.callback_query(F.data.startswith("delete_"))
async def delete_payment(callback: CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    session = None
    try:
        pid = int(callback.data.split("_")[1])
        session = get_session()
        payment = session.get(Payment, pid)
        if payment:
            session.delete(payment)
            session.commit()
            await callback.message.delete()
            await callback.answer(f"Платёж #{pid} удалён")
        else:
            await callback.answer("Платёж не найден", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)
    finally:
        if session is not None:
            session.close()


@dp.callback_query(F.data.startswith("weekdel_confirm_"))
async def start_delete_week(callback: CallbackQuery, state: FSMContext):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    week_str = callback.data.removeprefix("weekdel_confirm_")
    try:
        week_start = datetime.datetime.strptime(week_str, "%Y-%m-%d").date()
        week_end = week_start + timedelta(days=6)

        await state.set_state(AdminForm.waiting_for_delete_confirm)
        await state.update_data(week_start=week_start, action="weekdel_confirm_")

        await callback.message.answer(
            f"Вы уверены, что хотите удалить !!!ВСЕ!!! платежи\n"
            f"за неделю {week_start:%d.%m.%Y} – {week_end:%d.%m.%Y} ?\n\n"
            "Нажмите кнопку ниже или напишите «Да, удалить» для подтверждения",
            reply_markup=get_delete_confirm_keyboard()
        )
        await callback.answer()
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

@dp.message(AdminForm.waiting_for_delete_confirm)
async def process_delete_confirm(message: Message, state: FSMContext):
    text = message.text.strip().lower()

    if text in ["отмена", "cancel", "нет", "не"]:
        await message.answer("Удаление отменено.", reply_markup=get_admin_keyboard())
        await state.clear()
        return

    if text in ["да", "да удалить", "да, удалить", "yes"]:
        data = await state.get_data()
        session = None
        try:
            session = get_session()
            if data.get("action") == "weekdel_confirm_":
                ws = data["week_start"]
                we = ws + timedelta(days=6)

                count = session.query(Payment).filter(
                    Payment.date >= datetime.datetime.combine(ws, datetime.time.min),
                    Payment.date <= datetime.datetime.combine(we, datetime.time.max)
                ).delete(synchronize_session=False)

                session.commit()
                await message.answer(
                    f"Удалено {count} платежей за неделю.",
                    reply_markup=get_admin_keyboard()
                )
        except Exception as e:
            await message.answer(f"Ошибка удаления: {str(e)}")
        finally:
            if session is not None:
                session.close()
            await state.clear()
    else:
        await message.answer(
            "Пожалуйста, нажмите «Да, удалить» или «Отмена», или напишите «да» / «отмена».",
            reply_markup=get_delete_confirm_keyboard()
        )


@dp.message(Command("find"))
async def find_payment(message: Message):
    if not Config.is_admin(message.from_user.id):
        await message.answer("Нет доступа")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /find 123")
        return

    session = None
    try:
        pid = int(args[1])
        session = get_session()
        p = session.get(Payment, pid)
        if not p:
            await message.answer(f"Платёж #{pid} не найден")
            return

        st = "⏳" if p.status == "pending" else "✅" if p.status == "approved" else "❌"
        txt = (
            f"#{p.id}   {st}\n\n"
            f"Репетитор: {p.tutor_name}\n"
            f"Ребёнок:  {p.student_name}\n"
            f"Мама:      {p.parent_name}\n"
            f"Часы:      {p.hours}\n"
            f"Ставка:    {p.tutor_rate} ₽"
        )

        markup = get_pending_actions_keyboard(pid) if p.status == "pending" else \
                 get_approved_actions_keyboard(pid) if p.status == "approved" else None

        await (bot.send_photo if p.receipt_type == "photo" else bot.send_document)(
            message.chat.id, p.receipt_file_id, caption=txt, reply_markup=markup
        ) if p.receipt_type else await message.answer(txt, reply_markup=markup)
    except ValueError:
        await message.answer("ID — число")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    finally:
        if session is not None:
            session.close()

async def main():
    print("БОТ ДЛЯ РЕПЕТИТОРОВ ЗАПУЩЕН")

    import os
    render_url = os.getenv("RENDER_EXTERNAL_HOSTNAME")  
    if not render_url:
        raise ValueError("RENDER_EXTERNAL_HOSTNAME не найден. Запускается не на Render?")

    webhook_path = "/webhook"
    webhook_url = f"https://{render_url}{webhook_path}"

    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_webhook(url=webhook_url)

    print(f"Webhook установлен на: {webhook_url}")

    await dp.start_webhook(
        webhook_path=webhook_path,
        webhook_url=webhook_url,
        skip_updates=True,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    asyncio.run(main())