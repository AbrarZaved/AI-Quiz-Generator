import logging
import re

from celery import shared_task

from .models import Question, Quiz

logger = logging.getLogger(__name__)

# Matches a leading bullet/number marker like "- ", "* ", "• ", "1) ", "2. ".
_STEP_MARKER = re.compile(r"^(?:[-*•]|\d+[.)])\s+")


def parse_steps(steps):
    """Normalize the pipeline's `steps` value into a clean list of strings.

    The AI returns steps as a single block of text with newlines and bullet/
    number markers. We split it into one list item per line and strip the
    leading marker so the API returns a tidy array instead of a messy string.
    """
    if isinstance(steps, list):
        return [str(s).strip() for s in steps if str(s).strip()]
    if not steps:
        return []
    items = []
    for line in str(steps).splitlines():
        text = line.strip()
        if not text:
            continue
        items.append(_STEP_MARKER.sub("", text))
    return items

@shared_task(bind=True)
def generate_quiz_task(self, quiz_id):
    """Background task: generate MCQs for a quiz using the AI pipeline.

    Calls quizzes.ai.pipeline.create_mcq_for_topic once per question,
    storing each result as a Question row. Quiz.status reflects progress.
    """
    try:
        quiz = Quiz.objects.get(pk=quiz_id)
    except Quiz.DoesNotExist:
        logger.warning("generate_quiz_task: quiz %s no longer exists", quiz_id)
        return

    quiz.status = Quiz.Status.GENERATING
    quiz.generation_error = ""
    quiz.task_id = (self.request.id or "") if self.request else ""
    quiz.save(update_fields=["status", "generation_error", "task_id"])

    try:
        # Imported lazily so the worker only needs OpenAI/book files at run time.
        from .ai.pipeline import create_mcq_for_topic

        # Regenerate cleanly: drop any previously generated questions.
        quiz.questions.all().delete()

        for i in range(1, quiz.num_questions + 1):
            data = create_mcq_for_topic(
                book_name=quiz.book_name,
                chapter_name=quiz.chapter,
                topic_name=quiz.topic,
                question_no=i,
            )
            Question.objects.create(
                quiz=quiz,
                question_no=data.get("question_no", i),
                question_text=data["question"],
                options=data["options"],
                correct_answer=data["correct_answer"],
                steps=parse_steps(data.get("steps")),
                chapter=data.get("chapter", quiz.chapter),
                topic=data.get("topic", quiz.topic),
            )

        quiz.status = Quiz.Status.READY
        quiz.save(update_fields=["status"])
        logger.info("Quiz %s generated %s questions", quiz_id, quiz.num_questions)

    except Exception as exc:  # noqa: BLE001 - we record the error on the quiz
        logger.exception("Quiz %s generation failed", quiz_id)
        quiz.status = Quiz.Status.FAILED
        quiz.generation_error = str(exc)
        quiz.save(update_fields=["status", "generation_error"])
        raise
