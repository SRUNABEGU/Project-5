from rest_framework.serializers import ValidationError


class HabitValidator:
    requires_context = True

    def __call__(self, attrs, serializer):
        instance = serializer.instance

        def get(field):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field, None) if instance else None

        is_pleasant = get("is_pleasant")
        related = get("related_habit")
        reward = get("reward")

        if related and reward:
            raise ValidationError(
                "Нельзя указывать одновременно связанную привычку и вознаграждение."
            )
        if related and not related.is_pleasant:
            raise ValidationError(
                "В связанные привычки можно выбрать только приятную привычку."
            )
        if is_pleasant and (related or reward):
            raise ValidationError(
                "У приятной привычки не может быть вознаграждения или связанной привычки."
            )
        if related and instance and related.pk == instance.pk:
            raise ValidationError("Привычка не может быть связана сама с собой.")

        request = serializer.context.get("request")
        if related and request and related.user != request.user:
            raise ValidationError("Можно связать только свою привычку.")