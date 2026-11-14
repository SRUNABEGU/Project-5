from django.urls import path
from rest_framework.routers import SimpleRouter

from habits.views import HabitViewSet, PublicHabitListView

app_name = "habits"

router = SimpleRouter()
router.register("habits", HabitViewSet, basename="habit")

urlpatterns = [
    path("habits/public/", PublicHabitListView.as_view(), name="habit-public"),
] + router.urls