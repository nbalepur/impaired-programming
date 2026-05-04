"""Label each user prompt into its appropriate cluster."""

import json
from pathlib import Path

from dotenv import load_dotenv
from litellm import completion
import tqdm

load_dotenv()

TARGET_PROJECT_ID = "initial"  # label either "initial" or "extension" tasks
TARGET_GENERATED_MODE = "agent"  # label either "agent" or "chatbot" prompts

PROMPT_TEMPLATE_PATH = f"llm_judge/prompts/label_{TARGET_GENERATED_MODE}_prompts.txt"
AI_TRACE_PATH = "data/ai_trace.json"
OUTPUT_PATH = f"llm_judge/results/clusters/label_{TARGET_GENERATED_MODE}_prompts.jsonl"
MODEL = "gemini/gemini-3-flash-preview"

# Qualitative Categories
ALLOWED_LABELS_AGENT = {
    "copy",
    "rephrased",
    "technical",
    "exploratory",
    "debugging",
    "other",
}
ALLOWED_LABELS_CHATBOT = {
    "syntax_help",
    "design_help",
    "snippet",
    "debugging",
    "clarification",
    "jailbreaking",
    "urgency",
    "other",
}
ALLOWED_LABELS = (
    ALLOWED_LABELS_AGENT
    if TARGET_GENERATED_MODE == "agent"
    else ALLOWED_LABELS_CHATBOT
)

response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "prompt_label",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cluster_title": {
                    "type": "string",
                    "enum": sorted(ALLOWED_LABELS),
                },
                "explanation": {"type": "string"},
            },
            "required": ["cluster_title", "explanation"],
        },
    },
}

with open(PROMPT_TEMPLATE_PATH, encoding="utf-8") as _f:
    prompt_template = _f.read()

with open(AI_TRACE_PATH, encoding="utf-8") as _f:
    ai_trace_rows = json.load(_f)

filtered_rows = []
for row in ai_trace_rows:
    if not isinstance(row, dict):
        continue
    if not str(row.get("query", "")).strip():
        continue
    if row.get("project_id") != TARGET_PROJECT_ID:
        continue

    generated_code = row.get("generated_code")
    if not isinstance(generated_code, dict):
        continue
    if generated_code.get("mode") != TARGET_GENERATED_MODE:
        continue
    filtered_rows.append(row)


def parse_response(raw_response):
    message = raw_response.choices[0].message
    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        candidate = dict(parsed)
    else:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
            content = "\n".join(text_parts).strip()
        candidate = json.loads(str(content))

    if not isinstance(candidate, dict):
        return None, None

    label = str(candidate.get("cluster_title", "")).strip().lower()
    explanation = str(candidate.get("explanation", "")).strip()
    if label not in ALLOWED_LABELS or not explanation:
        return None, None
    return label, explanation


def generate_label(prompt_text: str, num_tries: int = 3):
    user_prompt = prompt_template.replace("{prompt}", prompt_text)
    for attempt in range(1, num_tries + 1):
        try:
            out = completion(
                model=MODEL,
                messages=[{"role": "user", "content": user_prompt}],
                response_format=response_format,
            )
            label, explanation = parse_response(out)
            if label is not None:
                return label, explanation
        except Exception as e:
            print(f"Attempt {attempt}/{num_tries} failed: {e}")
    return None, None


out_path = Path(OUTPUT_PATH)
out_path.parent.mkdir(parents=True, exist_ok=True)

total_written = 0
with out_path.open("w", encoding="utf-8") as f:
    for idx, row in enumerate(tqdm.tqdm(filtered_rows, desc="label_prompts progress"), start=1):
        prompt_text = str(row["query"]).strip().replace("\r\n", "\n")
        user_id = int(row["user_id"])
        label, explanation = generate_label(prompt_text)

        if label is None:
            print(f"Skipping row {idx}/{len(filtered_rows)}: no valid label after retries.")
            continue

        output_row = {
            "user_id": user_id,
            "prompt": prompt_text,
            "label": label,
            "explanation": explanation,
        }
        f.write(json.dumps(output_row, ensure_ascii=True) + "\n")
        f.flush()
        total_written += 1