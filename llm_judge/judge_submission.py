"""Use an LLM judge to determine whether a user submission passed different rubric criteria"""

import litellm
litellm.drop_params=True
import tqdm
import json

from dotenv import load_dotenv
load_dotenv()

# specify directories
USER_CODE_PATH = "data/user_code.json"
PROMPTS_DIR = "llm_judge/prompts/"
RESULTS_DIR = "llm_judge/results/judge_submission"

MODELS = ['gemini/gemini-3.1-pro-preview']

with open(USER_CODE_PATH, encoding="utf-8") as _f:
    user_records = json.load(_f)

for MODEL in MODELS:

    task1_rules = [
        "The first symbol placed in a new game is A (the game starts with Player A's turn). If there is no turn placing logic, this rule is automatically violated.",
        "Turns alternate between Player A and Player B. If there is no turn placing logic, this rule is automatically violated.",
        "Each player places exactly two symbols per turn before the turn switches. If there is no turn placing logic, this rule is automatically violated.",
        "Clicking an empty square places the correct symbol (A or B) based on whose turn it is. If there is no turn placing logic, this rule is automatically violated.",
        "Players cannot place a symbol on a square that already contains a symbol. If there is no turn placing logic, this rule is automatically violated.",
        "After a game ends, no additional symbols can be placed. If there is no win detection logic or no end game states can be reached, this rule is automatically violated.",
        "The game correctly detects horizontal five-in-a-row win conditions. If there is no win detection logic, this rule is automatically violated.",
        "The game correctly detects vertical five-in-a-row win conditions. If there is no win detection logic, this rule is automatically violated.",
        "The game has no other win conditions (e.g., diagonal wins). If there is no win detection logic, this rule is automatically violated.",
        "If the board fills with no winner, the game ends in a tie. If there is no win detection logic, this rule is automatically violated.",
        "A status element visually appears on the page prefixed by “Status:”. Minor variations of 'Status' are fine and should NOT be considered violations.",
        "The status element correctly displays whose turn it is. If there is no turn changing logic, this rule is automatically violated.",
        "The status element correctly displays the game outcome (Player A wins, Player B wins, or Tie Game). If there is no game detection logic, this rule is automatically violated. ",
        "The entire web page is centered horizontally. If it is also centered vertically, it is NOT considered a violation.",
        "Horizontal centering of the page is implemented by modifying the CSS file. If the page is not centered horizontally, this rule is automatically violated."
    ]

    task2_rules = [
        "The placed “A” symbols have a red color. If there is no turn placing logic, this rule is automatically violated.",
        "The placed “B” symbols have a blue color. If there is no turn placing logic, this rule is automatically violated.",
        "The symbol colors are defined in the CSS file rather than set directly in JavaScript. If there is no turn placing logic, this rule is automatically violated.",
        "Player A wins the game if they place the A symbol on all four corners of the board. If there is no win detection logic, this rule is automatically violated.",
        "Player B wins the game if they place the B symbol on all four corners of the board. If there is no win detection logic, this rule is automatically violated.",
        "Players can still win using the win conditions from the original submisison. In the first task, the user attempted to implement win-checking by looking for horizontal and vertical symbols in a row, which may or may not be implemented correctly. This rule's passing or failure should not depend on the horizontal or vertical detection logic. Instead, you must ensure that any win detection logic that was not related to the four corners is still preserved. If there is no win detection logic, this rule is automatically violated.",
        "A 'Reset Game' button appears visually below the board",
        "Clicking the reset button clears the board of symbols and colors. If either the colors or symbols are not reset properly, this rule is automatically violated. Both conditions must be met for the rule to be passed",
        "Clicking the reset button resets the game so it is Player A's turn. If there is no reset button, this rule is automatically violated.",
        "Clicking the reset button resets the display of the status element. If there is no reset button, this rule is automatically violated.",
        "The reset button does not refresh the page. If there is no reset button, this rule is automatically violated.",
        "After reset, the game accepts moves and turn progression. If there is no reset button, this rule is automatically violated."
    ]

    from pydantic import BaseModel
    class JudgeResponse(BaseModel):
        result: str
        explanation: str


    with open(PROMPTS_DIR / 'prompt_task1.txt', 'r', encoding='utf-8') as f:
        prompt_task1 = f.read()

    with open(PROMPTS_DIR / 'prompt_task2.txt', 'r', encoding='utf-8') as f:
        prompt_task2 = f.read()

    def parse_response(response):
        try:
            response = response.choices[0].message.content
            if '{' in response:
                response = response[response.index('{'):response.rindex('}') + 1]
            response_json = json.loads(response)
            if set(response_json.keys()) == {'result', 'explanation'}:
                if type(response_json['result']) == str and type(response_json['explanation']) == str and response_json['result'].lower().strip() in {'passed', 'violated'} and response_json['explanation']:
                    return response_json['result'].lower().strip() == 'passed', response_json['explanation']
            return None, None

        except Exception as e:
            print('Parsing Error:', e)
            return None, None
            
    def generate(prompt: str, num_tries=3):
        for _ in range(num_tries):
            out = litellm.completion(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                reasoning_effort="medium",
                response_format=JudgeResponse
            )
            pred, expl = parse_response(out)
            if pred != None:
                return pred, expl
        return None, None
        
    
    all_pred = []
    all_explanation = []
    all_task = []
    all_user_type = []
    all_user_id = []

    # Judge the initial task
    for row in tqdm.tqdm(user_records, desc="initial_code progress"):
        user_id = row["user_id"]
        user_mode = row["experiment_group"]
        code = row["initial_code"]
        for rule in task1_rules:
            curr_prompt = prompt_task1.format(code=code, rule=rule)
            pred, expl = generate(curr_prompt)
            all_pred.append(pred)
            all_explanation.append(expl)
        all_task.extend(['initial_code' for _ in task1_rules])
        all_user_type.extend([user_mode for _ in task1_rules])
        all_user_id.extend([user_id for _ in task1_rules])

    # Judge the extension task
    for row in tqdm.tqdm(user_records, desc="extension_code progress"):
        user_id = row["user_id"]
        user_mode = row["experiment_group"]
        code = row["extension_code"]
        for rule in task2_rules:
            curr_prompt = prompt_task2.format(code=code, rule=rule)
            pred, expl = generate(curr_prompt)
            all_pred.append(pred)
            all_explanation.append(expl)
        all_task.extend(['extension_code' for _ in task1_rules])
        all_user_type.extend([user_mode for _ in task1_rules])
        all_user_id.extend([user_id for _ in task1_rules])

    out_path = RESULTS_DIR / f"{MODEL}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Save file
    with open(out_path, 'w', encoding='utf-8') as f:
        for pred, expl, task, user_type, user_id in zip(
            all_pred, all_explanation, all_task, all_user_type, all_user_id
        ):
            line = {
                "prediction": pred,
                "explanation": expl,
                "task": task,
                "user_type": user_type,
                "user_id": user_id
            }
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
