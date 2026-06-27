# Quiz Platform (Django + DRF)

An AI-generated quiz taking platform with two roles (**admin** and **student**).

- **Admins** create quizzes by giving the AI a *book name, chapter, topic, and number of questions*. Generation runs in the background via **Celery**, and the resulting MCQs are saved to the database. Admins can edit questions/answers or delete them (via REST API **and** the Django admin).
- **Students** sign up, log in, see published quizzes, take them (**one attempt each**), get a result with step-by-step solutions, and view a **per-quiz leaderboard** plus their **past quizzes**.

## Tech stack

| Concern | Choice |
|---|---|
| Framework | Django 5 + Django REST Framework |
| Auth | JWT (SimpleJWT) |
| Database | PostgreSQL |
| Background tasks | Celery + Redis |
| Password reset | OTP via SMTP email |
| AI generation | `quizzes/ai/pipeline.py` (OpenAI) |
| API docs | drf-spectacular (`/api/docs/`) |

## Project layout

```
quiz_platform/
├── config/            # settings, urls, celery, wsgi/asgi
├── accounts/          # custom email user, JWT auth, OTP password reset
├── quizzes/           # Quiz + Question models, AI Celery task, admin/API editing
│   └── ai/pipeline.py # YOUR pipeline (paths made env-configurable)
├── attempts/          # student attempts, results, leaderboard
├── book_data/         # drop your two books' files here (see book_data/README.md)
├── manage.py
├── requirements.txt
├── docker-compose.yml # Postgres + Redis for local dev
└── .env.example
```

## Setup

```bash
# 1. Create & activate a virtualenv
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env        # then edit values (DB, Redis, SMTP, OPENAI_API_KEY)

# 4. Start Postgres + Redis (or run your own)
docker compose up -d

# 5. Migrate
python manage.py makemigrations
python manage.py migrate

# 6. Create an admin (role=admin, is_staff/superuser=True)
python manage.py createsuperuser

# 7. Run the API
python manage.py runserver

# 8. Run the Celery worker (separate terminal, venv activated)
celery -A config worker -l info
# On Windows use: celery -A config worker -l info --pool=solo
```

API docs: http://localhost:8000/api/docs/  •  Django admin: http://localhost:8000/admin/

## Book data

The AI pipeline reads each book's TOC/content/images from `BOOK_DATA_DIR`
(default `./book_data`). See **`book_data/README.md`** for the exact folder
structure for `volume1` and `volume2`. To add more books, extend `BOOK_CONFIG`
in `quizzes/ai/pipeline.py`.

## Roles

- **admin**: `role="admin"`. Created via `createsuperuser` or the Django admin
  (set role = Admin, is_staff = True). Admins get full quiz/question CRUD.
- **student**: created by public `POST /api/auth/signup/`. Read-only on quizzes;
  can submit one attempt per quiz.

## API reference

### Auth (`/api/auth/`)
| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/signup/` | `email, full_name, password` | Creates an **inactive** student and emails a verification OTP |
| POST | `/verify/` | `email, otp` | Verifies the OTP and **activates** the account |
| POST | `/verify/resend/` | `email` | Resends the signup OTP (if unverified) |
| POST | `/login/` | `email, password` | Returns `access`, `refresh`, `user`. **Blocked until verified** |
| POST | `/token/refresh/` | `refresh` | New access token |
| POST | `/password/forgot/` | `email` | Emails a 6-digit OTP |
| POST | `/password/reset/` | `email, otp, new_password` | Sets a new password |
| GET  | `/me/` | — | Current user |

**Signup -> verify -> login flow:**
1. `POST /api/auth/signup/` creates an inactive account and emails a 6-digit OTP.
2. `POST /api/auth/verify/` with that OTP activates the account.
3. `POST /api/auth/login/` now succeeds. Logging in before verifying returns
   "No active account found with the given credentials". Use `/verify/resend/`
   if the code expired (default 10 min).

### Quizzes (`/api/`)
| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/quizzes/` | admin | Create quiz → queues AI generation. Body: `title, description, book_name, chapter, topic, num_questions, is_published` |
| GET | `/quizzes/` | any | Admin sees all; students see published+ready |
| GET | `/quizzes/{id}/` | any | Admin: full (with answers). Student: take view |
| PATCH/PUT | `/quizzes/{id}/` | admin | Update quiz fields / publish |
| DELETE | `/quizzes/{id}/` | admin | Delete quiz |
| POST | `/quizzes/{id}/regenerate/` | admin | Re-run AI generation |
| GET | `/quizzes/{id}/take/` | any | Questions without answers/solutions |
| GET/POST | `/questions/` | admin | List/create questions (`?quiz={id}` filter) |
| GET/PATCH/PUT/DELETE | `/questions/{id}/` | admin | Edit answer/options or delete |

### Attempts (`/api/`)
| Method | Path | Notes |
|---|---|---|
| POST | `/quizzes/{id}/submit/` | Body: `{ "answers": [{"question": <id>, "selected_option": <1-based>}] }`. One attempt per student; returns graded result + solutions |
| GET | `/quizzes/{id}/result/` | Current student's detailed result |
| GET | `/quizzes/{id}/leaderboard/` | Ranked by score, then earliest submission |
| GET | `/me/attempts/` | Current student's past quizzes + scores |

## Quiz generation flow

1. Admin `POST /api/quizzes/` with `book_name`, `chapter`, `topic`, `num_questions`.
2. The quiz is saved with `status=pending`; `generate_quiz_task` is queued.
3. The Celery worker calls `create_mcq_for_topic(...)` once per question and
   stores each as a `Question` (`question_text`, `options`, `correct_answer`
   as a 1-based index, `steps`). `status` moves `generating → ready` (or
   `failed` with `generation_error`).
4. Set `is_published=true` so students can see and take it.

## Notes

- `correct_answer` is a **1-based** option index, matching your pipeline's JSON.
- Students never receive `correct_answer`/`steps` until after they submit.
- If `EMAIL_HOST_USER` is empty, emails (including OTPs) print to the console
  so you can develop without real SMTP.
