"""
AI MCQ generation pipeline (your original pipeline, kept intact).

The ONLY change from your uploaded file is that the hard-coded Windows paths in
BOOK_CONFIG are now built from the BOOK_DATA_DIR environment variable so the
same code runs on any server. Drop your two books' files under that directory
as described in README.md -> "Book data layout".

Called by quizzes/tasks.py::generate_quiz_task via create_mcq_for_topic().
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
import base64

# ====================== LOAD ENVIRONMENT ======================
load_dotenv()

OPEN_AI_API_KEY = os.getenv("OPENAI_API_KEY") or ""

client = OpenAI(api_key=OPEN_AI_API_KEY)


# ===================== CONFIGURATION ======================
GENERATION_MODEL = "gpt-5"
TEMPERATURE = 0.35
MAX_TOKENS = 400

# ===================== BOOK DATA DIRECTORY =====================
# Root folder that contains the volume1/ and volume2/ sub-folders.
# Configure it via the BOOK_DATA_DIR env var (see README).
BOOK_DATA_DIR = os.getenv(
    "BOOK_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "book_data"),
)

# ===================== BOOK CONFIG =====================
BOOK_CONFIG = {
    "volume1": {
        "toc_json": os.path.join(BOOK_DATA_DIR, "volume1", "content_offset.json"),
        "content_json": os.path.join(
            BOOK_DATA_DIR, "volume1", "volume1_final_metadata_fixed_images.json"
        ),
        "images_dir": os.path.join(BOOK_DATA_DIR, "volume1", "v1images"),
    },
    "volume2": {
        "toc_json": os.path.join(BOOK_DATA_DIR, "volume2", "content_offset.json"),
        "content_json": os.path.join(
            BOOK_DATA_DIR, "volume2", "merged_mapped_content_volume 2.json"
        ),
        "images_dir": os.path.join(BOOK_DATA_DIR, "volume2", "v2images"),
    },
}

# ====================== OUTPUT DIR (optional debug dumps) ======================
OUTPUT_DIR = os.path.join(BOOK_DATA_DIR, "generated_mcq")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ====================== PYDANTIC MODEL ======================
class MCQQuestion(BaseModel):
    question: str
    options: list[str]
    correct_answer: int


class MCQSolution(BaseModel):
    steps: str


class MCQOutput(BaseModel):
    question_no: int
    chapter: str
    topic: str
    question: str
    options: list[str]
    correct_answer: int
    steps: str


def get_book_config(book_name):
    if book_name not in BOOK_CONFIG:
        raise ValueError(f"Unknown book: {book_name}")
    return BOOK_CONFIG[book_name]


def load_toc(book_name):
    config = get_book_config(book_name)
    with open(config["toc_json"], "r", encoding="utf-8") as f:
        return json.load(f)


def load_content(book_name):
    config = get_book_config(book_name)
    with open(config["content_json"], "r", encoding="utf-8") as f:
        return json.load(f)


def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_topic_page_range(chapter_name, topic_name, toc_data):
    for chapter in toc_data:
        if chapter["chapter"].lower() != chapter_name.lower():
            continue

        topics = chapter["topics"]

        for i, topic in enumerate(topics):
            if topic["topic"].lower() != topic_name.lower():
                continue

            start_page = topic["page"]

            if i < len(topics) - 1:
                end_page = topics[i + 1]["page"] - 1
            else:
                end_page = 999999

            return start_page, end_page

    raise ValueError(f"Topic '{topic_name}' not found")


def extract_topic_content(book_name, chapter_name, topic_name):
    config = get_book_config(book_name)

    toc_data = load_toc(book_name)
    content_data = load_content(book_name)

    images_dir = config["images_dir"]

    start_page, end_page = get_topic_page_range(chapter_name, topic_name, toc_data)

    collected_text = []
    collected_images = []

    for item in content_data:
        page_idx = item.get("page_idx")
        if not (start_page <= page_idx <= end_page):
            continue

        if item["type"] == "text":
            text = item.get("text", "")
            if text:
                collected_text.append(text)

        elif item["type"] == "image":
            image_path = item.get("img_path")
            if image_path:
                filename = os.path.basename(image_path)
                full_path = os.path.join(images_dir, filename)
                if os.path.exists(full_path):
                    collected_images.append(full_path)

    return {"text": "\n".join(collected_text), "images": collected_images}


def generate_mcq(context_text, image_paths):
    content = []

    content.append(
        {
            "type": "input_text",
            "text": f"""
Generate ONE mathematics MCQ.

Use the provided text and any diagrams/images.

Context:

{context_text}

Requirements:
- 4 options
- only one correct answer
- correct_answer must be 1,2,3 or 4
""",
        }
    )

    for img_path in image_paths[:10]:
        if not os.path.exists(img_path):
            continue
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{image_to_base64(img_path)}",
            }
        )

    response = client.responses.parse(
        model=GENERATION_MODEL,
        input=[{"role": "user", "content": content}],
        text_format=MCQQuestion,
    )

    return response.output_parsed


def generate_solution(question, options, answer, context_text, image_paths):
    content = []

    content.append(
        {
            "type": "input_text",
            "text": f"""
Question:
{question}

Options:
{options}

Correct Answer:
{answer}

Context:
{context_text}

Provide a detailed step-by-step solution.
""",
        }
    )

    for img_path in image_paths[:10]:
        if not os.path.exists(img_path):
            continue
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{image_to_base64(img_path)}",
            }
        )

    response = client.responses.parse(
        model=GENERATION_MODEL,
        input=[{"role": "user", "content": content}],
        text_format=MCQSolution,
    )

    return response.output_parsed


def create_mcq_for_topic(book_name, chapter_name, topic_name, question_no):
    topic_data = extract_topic_content(book_name, chapter_name, topic_name)

    mcq = generate_mcq(topic_data["text"], topic_data["images"])

    solution = generate_solution(
        mcq.question,
        mcq.options,
        mcq.correct_answer,
        topic_data["text"],
        topic_data["images"],
    )

    result = MCQOutput(
        question_no=question_no,
        chapter=chapter_name,
        topic=topic_name,
        question=mcq.question,
        options=mcq.options,
        correct_answer=mcq.correct_answer,
        steps=solution.steps,
    )

    return result.model_dump()


def save_result(data, filename):
    output_path = os.path.join(OUTPUT_DIR, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Saved: {output_path}")


def run_pipeline(book_name, chapter_name, topic_name, question_count):
    all_questions = []

    for i in range(1, question_count + 1):
        print(f"Generating Question {i}/{question_count}")
        result = create_mcq_for_topic(
            book_name=book_name,
            chapter_name=chapter_name,
            topic_name=topic_name,
            question_no=i,
        )
        all_questions.append(result)

    filename = f"{book_name}_{chapter_name}_{topic_name}.json".replace(" ", "_")
    save_result(all_questions, filename)

    return all_questions


if __name__ == "__main__":
    # Simple manual test (requires book files + OPENAI_API_KEY).
    book_name = "volume2"
    chapter_name = "Relations, Functions and Graphs"
    topic_name = "Functions"
    question_count = 3
    run_pipeline(book_name, chapter_name, topic_name, question_count)
