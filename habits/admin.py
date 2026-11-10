from django.contrib import admin

from habits.models import Habit


@admin.register(Habit)
class HabitAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "user", "time", "place", "is_pleasant", "is_public")
    list_filter = ("is_pleasant", "is_public")
    search_fields = ("action", "place")