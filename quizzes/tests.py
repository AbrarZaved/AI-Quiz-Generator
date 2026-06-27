from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Question, Quiz

User = get_user_model()


class QuizFlowTests(APITestCase):
    """Smoke tests for the core student flow (no AI / Celery needed)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            full_name="Admin",
            password="adminpass123",
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.student = User.objects.create_user(
            email="student@example.com",
            full_name="Student",
            password="studentpass123",
        )
        self.quiz = Quiz.objects.create(
            title="Sample",
            book_name="volume1",
            chapter="Sets 1",
            topic="Finite and Infinite Sets",
            num_questions=1,
            status=Quiz.Status.READY,
            is_published=True,
            created_by=self.admin,
        )
        self.question = Question.objects.create(
            quiz=self.quiz,
            question_no=1,
            question_text="Solve for x: 3(x - 2) = 2x + 5",
            options=["11", "-11", "1", "0"],
            correct_answer=1,
            steps="x = 11",
        )

    def _login(self, email, password):
        res = self.client.post(
            "/api/auth/login/", {"email": email, "password": password}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        return res.data["access"]

    def test_student_take_hides_answers(self):
        token = self._login("student@example.com", "studentpass123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res = self.client.get(f"/api/quizzes/{self.quiz.id}/take/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        q = res.data["questions"][0]
        self.assertNotIn("correct_answer", q)
        self.assertNotIn("steps", q)

    def test_submit_and_single_attempt(self):
        token = self._login("student@example.com", "studentpass123")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        payload = {"answers": [{"question": self.question.id, "selected_option": 1}]}
        res = self.client.post(
            f"/api/quizzes/{self.quiz.id}/submit/", payload, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["score"], 1)
        self.assertEqual(res.data["total"], 1)

        # Second submission is rejected (one attempt per student).
        res2 = self.client.post(
            f"/api/quizzes/{self.quiz.id}/submit/", payload, format="json"
        )
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
