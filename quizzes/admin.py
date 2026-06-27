from django.contrib import admin

from .models import Question, Quiz


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ["question_no", "question_text", "options", "correct_answer"]
    ordering = ["question_no"]


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "book_name",
        "chapter",
        "topic",
        "num_questions",
        "status",
        "is_published",
        "created_at",
    ]
    list_filter = ["status", "is_published", "book_name"]
    search_fields = ["title", "chapter", "topic"]
    readonly_fields = ["status", "generation_error", "created_at", "updated_at"]
    inlines = [QuestionInline]
    actions = ["regenerate_quizzes"]

    @admin.action(description="Regenerate selected quizzes with AI")
    def regenerate_quizzes(self, request, queryset):
        from .tasks import generate_quiz_task

        for quiz in queryset:
            generate_quiz_task.delay(quiz.id)
        self.message_user(request, f"Queued {queryset.count()} quiz(zes) for regeneration.")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["quiz", "question_no", "question_text", "correct_answer"]
    list_filter = ["quiz"]
    search_fields = ["question_text", "topic", "chapter"]
    ordering = ["quiz", "question_no"]
