from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

import requests
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from habits.models import Habit
from habits.services import send_telegram_message
from habits.tasks import build_message, send_habit_reminders
from users.models import User


def make_habit(user, **kwargs):
    """Создаёт привычку напрямую в БД (без валидаторов API)."""
    data = {
        "user": user,
        "place": "дом",
        "time": time(8, 0),
        "action": "делать зарядку",
        "duration": 60,
    }
    data.update(kwargs)
    return Habit.objects.create(**data)


class HabitBaseTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="StrongPass123", tg_chat_id="111"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", password="StrongPass123", tg_chat_id="222"
        )
        self.client.force_authenticate(self.user)

    @staticmethod
    def payload(**kwargs):
        data = {
            "place": "дом",
            "time": "08:00:00",
            "action": "делать зарядку",
            "periodicity": 1,
            "reward": "чашка кофе",
            "duration": 60,
        }
        data.update(kwargs)
        return {key: value for key, value in data.items() if value is not None}


class HabitCrudTestCase(HabitBaseTestCase):
    def test_create_habit(self):
        response = self.client.post(reverse("habits:habit-list"), self.payload())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Habit.objects.count(), 1)
        self.assertEqual(Habit.objects.get().user, self.user)

    def test_create_habit_ignores_foreign_user(self):
        response = self.client.post(
            reverse("habits:habit-list"), self.payload(user=self.other_user.pk)
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"], self.user.pk)

    def test_create_habit_with_related_pleasant_habit(self):
        pleasant = make_habit(self.user, is_pleasant=True, action="принять ванну")

        response = self.client.post(
            reverse("habits:habit-list"),
            self.payload(reward=None, related_habit=pleasant.pk),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["related_habit"], pleasant.pk)

    def test_create_pleasant_habit(self):
        response = self.client.post(
            reverse("habits:habit-list"),
            self.payload(is_pleasant=True, reward=None),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Habit.objects.get().is_pleasant)

    def test_retrieve_own_habit(self):
        habit = make_habit(self.user)

        response = self.client.get(reverse("habits:habit-detail", args=[habit.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["action"], habit.action)

    def test_update_own_habit(self):
        habit = make_habit(self.user)

        response = self.client.patch(
            reverse("habits:habit-detail", args=[habit.pk]), {"place": "парк"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        habit.refresh_from_db()
        self.assertEqual(habit.place, "парк")

    def test_delete_own_habit(self):
        habit = make_habit(self.user)

        response = self.client.delete(reverse("habits:habit-detail", args=[habit.pk]))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Habit.objects.filter(pk=habit.pk).exists())

    def test_habit_str(self):
        habit = make_habit(self.user)

        self.assertIn("делать зарядку", str(habit))
        self.assertIn("дом", str(habit))


class HabitValidationTestCase(HabitBaseTestCase):
    def post(self, **kwargs):
        return self.client.post(reverse("habits:habit-list"), self.payload(**kwargs))

    def test_reward_and_related_habit_together(self):
        pleasant = make_habit(self.user, is_pleasant=True)

        response = self.post(reward="кофе", related_habit=pleasant.pk)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_related_habit_must_be_pleasant(self):
        useful = make_habit(self.user, reward="кофе")

        response = self.post(reward=None, related_habit=useful.pk)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pleasant_habit_cannot_have_reward(self):
        response = self.post(is_pleasant=True, reward="кофе")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pleasant_habit_cannot_have_related_habit(self):
        pleasant = make_habit(self.user, is_pleasant=True)

        response = self.post(is_pleasant=True, reward=None, related_habit=pleasant.pk)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duration_more_than_120_seconds(self):
        response = self.post(duration=121)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("duration", response.data)

    def test_duration_120_seconds_is_allowed(self):
        response = self.post(duration=120)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_periodicity_more_than_7_days(self):
        response = self.post(periodicity=8)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("periodicity", response.data)

    def test_periodicity_less_than_1_day(self):
        response = self.post(periodicity=0)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_periodicity_7_days_is_allowed(self):
        response = self.post(periodicity=7)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cannot_link_foreign_habit(self):
        foreign = make_habit(self.other_user, is_pleasant=True)

        response = self.post(reward=None, related_habit=foreign.pk)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_habit_cannot_be_related_to_itself(self):
        habit = make_habit(self.user, is_pleasant=True)

        response = self.client.patch(
            reverse("habits:habit-detail", args=[habit.pk]),
            {"related_habit": habit.pk},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_partial_update_uses_existing_values(self):
        pleasant = make_habit(self.user, is_pleasant=True)

        response = self.client.patch(
            reverse("habits:habit-detail", args=[pleasant.pk]), {"reward": "кофе"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class HabitPermissionsTestCase(HabitBaseTestCase):
    def test_unauthenticated_user_has_no_access(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("habits:habit-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_contains_only_own_habits(self):
        own = make_habit(self.user)
        make_habit(self.other_user)

        response = self.client.get(reverse("habits:habit-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], own.pk)

    def test_cannot_retrieve_foreign_habit(self):
        foreign = make_habit(self.other_user, is_public=True)

        response = self.client.get(reverse("habits:habit-detail", args=[foreign.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_update_foreign_habit(self):
        foreign = make_habit(self.other_user)

        response = self.client.patch(
            reverse("habits:habit-detail", args=[foreign.pk]), {"place": "парк"}
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        foreign.refresh_from_db()
        self.assertEqual(foreign.place, "дом")

    def test_cannot_delete_foreign_habit(self):
        foreign = make_habit(self.other_user)

        response = self.client.delete(reverse("habits:habit-detail", args=[foreign.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Habit.objects.filter(pk=foreign.pk).exists())


class HabitPaginationTestCase(HabitBaseTestCase):
    def test_five_habits_per_page(self):
        for _ in range(7):
            make_habit(self.user)

        first_page = self.client.get(reverse("habits:habit-list"))
        second_page = self.client.get(reverse("habits:habit-list"), {"page": 2})

        self.assertEqual(first_page.data["count"], 7)
        self.assertEqual(len(first_page.data["results"]), 5)
        self.assertIsNotNone(first_page.data["next"])
        self.assertEqual(len(second_page.data["results"]), 2)
        self.assertIsNone(second_page.data["next"])


class PublicHabitTestCase(HabitBaseTestCase):
    def test_public_list_contains_only_public_habits(self):
        public = make_habit(self.other_user, is_public=True)
        make_habit(self.other_user, is_public=False)

        response = self.client.get(reverse("habits:habit-public"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], public.pk)

    def test_public_list_is_paginated(self):
        for _ in range(6):
            make_habit(self.other_user, is_public=True)

        response = self.client.get(reverse("habits:habit-public"))

        self.assertEqual(len(response.data["results"]), 5)

    def test_public_list_is_read_only(self):
        response = self.client.post(reverse("habits:habit-public"), self.payload())

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_public_list_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("habits:habit-public"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TelegramServiceTestCase(APITestCase):
    @patch("habits.services.requests.post")
    def test_send_message_success(self, mock_post):
        mock_post.return_value = MagicMock()

        result = send_telegram_message("123", "Привет")

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["data"]["chat_id"], "123")

    @patch("habits.services.requests.post")
    def test_send_message_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException("ошибка сети")

        result = send_telegram_message("123", "Привет")

        self.assertFalse(result)


class ReminderTaskTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="StrongPass123", tg_chat_id="111"
        )
        self.now = timezone.make_aware(datetime(2026, 1, 15, 8, 0))
        self.today = self.now.date()

    def run_task(self, send_result=True):
        with patch("habits.tasks.timezone.localtime", return_value=self.now), patch(
            "habits.tasks.send_telegram_message", return_value=send_result
        ) as mock_send:
            send_habit_reminders()
        return mock_send

    def test_reminder_is_sent(self):
        habit = make_habit(self.user, reward="кофе")

        mock_send = self.run_task()

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.args[0], "111")
        habit.refresh_from_db()
        self.assertEqual(habit.last_reminded, self.today)

    def test_reminder_not_sent_at_other_time(self):
        make_habit(self.user, time=time(9, 30))

        self.assertFalse(self.run_task().called)

    def test_pleasant_habit_is_not_reminded(self):
        make_habit(self.user, is_pleasant=True)

        self.assertFalse(self.run_task().called)

    def test_user_without_chat_id_is_skipped(self):
        self.user.tg_chat_id = None
        self.user.save()
        make_habit(self.user)

        self.assertFalse(self.run_task().called)

    def test_user_with_empty_chat_id_is_skipped(self):
        self.user.tg_chat_id = ""
        self.user.save()
        make_habit(self.user)

        self.assertFalse(self.run_task().called)

    def test_periodicity_is_respected(self):
        make_habit(
            self.user,
            periodicity=3,
            last_reminded=self.today - timedelta(days=1),
        )

        self.assertFalse(self.run_task().called)

    def test_reminder_sent_when_periodicity_passed(self):
        make_habit(
            self.user,
            periodicity=3,
            last_reminded=self.today - timedelta(days=3),
        )

        self.assertTrue(self.run_task().called)

    def test_last_reminded_not_updated_if_sending_failed(self):
        habit = make_habit(self.user)

        self.run_task(send_result=False)

        habit.refresh_from_db()
        self.assertIsNone(habit.last_reminded)

    def test_build_message_with_reward(self):
        habit = make_habit(self.user, reward="кофе")

        message = build_message(habit)

        self.assertIn("делать зарядку", message)
        self.assertIn("08:00", message)
        self.assertIn("дом", message)
        self.assertIn("кофе", message)

    def test_build_message_with_related_habit(self):
        pleasant = make_habit(self.user, is_pleasant=True, action="принять ванну")
        habit = make_habit(self.user, related_habit=pleasant)

        message = build_message(habit)

        self.assertIn("принять ванну", message)
