from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User


class UserModelTestCase(APITestCase):
    def test_create_user(self):
        user = User.objects.create_user(email="Test@Example.com", password="StrongPass123")

        self.assertEqual(user.email, "Test@example.com")
        self.assertTrue(user.check_password("StrongPass123"))
        self.assertFalse(user.is_staff)
        self.assertEqual(str(user), user.email)

    def test_create_user_without_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="StrongPass123")

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email="admin@example.com", password="StrongPass123"
        )

        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class UserRegisterTestCase(APITestCase):
    def setUp(self):
        self.url = reverse("users:register")
        self.data = {
            "email": "new@example.com",
            "password": "StrongPass123",
            "tg_chat_id": "123456789",
        }

    def test_register(self):
        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", response.data)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.tg_chat_id, "123456789")
        self.assertNotEqual(user.password, "StrongPass123")
        self.assertTrue(user.check_password("StrongPass123"))

    def test_register_without_tg_chat_id(self):
        del self.data["tg_chat_id"]

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_register_duplicate_email(self):
        User.objects.create_user(email="new@example.com", password="StrongPass123")

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_weak_password(self):
        self.data["password"] = "123"

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.exists())

    def test_register_invalid_email(self):
        self.data["email"] = "не-email"

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserLoginTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="StrongPass123"
        )
        self.url = reverse("users:login")

    def test_login(self):
        response = self.client.post(
            self.url, {"email": "user@example.com", "password": "StrongPass123"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_wrong_password(self):
        response = self.client.post(
            self.url, {"email": "user@example.com", "password": "wrong"}
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token(self):
        tokens = self.client.post(
            self.url, {"email": "user@example.com", "password": "StrongPass123"}
        ).data

        response = self.client.post(
            reverse("users:token-refresh"), {"refresh": tokens["refresh"]}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_access_token_gives_access_to_api(self):
        tokens = self.client.post(
            self.url, {"email": "user@example.com", "password": "StrongPass123"}
        ).data

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = self.client.get(reverse("habits:habit-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
