from django.contrib import admin

from .models import Attempt, AttemptAnswer


class AttemptAnswerInline(admin.TabularInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ["question", "selected_option", "is_correct"]
    can_delete = False


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ["student", "quiz", "score", "total", "submitted_at"]
    list_filter = ["quiz"]
    search_fields = ["student__email", "quiz__title"]
    readonly_fields = ["student", "quiz", "score", "total", "submitted_at"]
    inlines = [AttemptAnswerInline]
