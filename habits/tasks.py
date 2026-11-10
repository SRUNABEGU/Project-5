from celery import shared_task
from django.utils import timezone

from habits.models import Habit
from habits.services import send_telegram_message


def build_message(habit):
    text = f"Напоминание: я буду {habit.action} в {habit.time:%H:%M} в {habit.place}."
    if habit.related_habit:
        text += f"\nПосле этого: {habit.related_habit.action}."
    elif habit.reward:
        text += f"\nНаграда: {habit.reward}."
    return text


@shared_task
def send_habit_reminders():
    now = timezone.localtime()
    today = now.date()

    habits = (
        Habit.objects.filter(
            is_pleasant=False,
            time__hour=now.hour,
            time__minute=now.minute,
            user__tg_chat_id__isnull=False,
        )
        .exclude(user__tg_chat_id="")
        .select_related("user", "related_habit")
    )

    for habit in habits:
        if habit.last_reminded and (today - habit.last_reminded).days < habit.periodicity:
            continue
        if send_telegram_message(habit.user.tg_chat_id, build_message(habit)):
            habit.last_reminded = today
            habit.save(update_fields=["last_reminded"])