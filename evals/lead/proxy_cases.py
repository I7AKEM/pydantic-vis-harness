"""Build deterministic train and dev examples for the lead decision proxy."""

import hashlib
import json
import random

import dspy

from evals.designer.agent.corpus_tools.select import CORPUS, read_manifest
from evals.lead.run import corpus_cases

PICTURE_CHANGES = (
    "Make the bars dark blue.",
    "Change the title to 'Overview'.",
    "Use a horizontal bar chart.",
    "اجعل الألوان زرقاء داكنة.",
)
DATA_CHANGES = (
    "Only the top five.",
    "Exclude the largest category.",
    "Show 2024 only.",
    "اعرض أكبر خمس فئات فقط.",
)
WAITING_QUESTIONS = ("Which column holds the amount?", "What counts as wealthy?")
CONTINUE_MESSAGES = ("Continue.", "Go on.")
# A report or an overview of the numbers is a draw of the data's main breakdown, not a description of the file.
REPORT_REQUESTS = ("Write a report about this data.", "Give me an overview of the numbers.",
                   "اكتب تقرير عن هذه البيانات.", "أعطني نظرة عامة على الأرقام.")


def _ids(source_id: str) -> tuple[str, str, str]:
    digest = hashlib.md5(source_id.encode()).hexdigest()
    return f"ds_{digest}", f"rq_{digest}", f"art_{digest}"


def _columns(row: dict) -> list[str] | None:
    path = CORPUS / row["csv_path"]
    try:
        with path.open(encoding="utf-8-sig") as source:
            header = source.readline()
            first_row = source.readline()
    except (OSError, UnicodeError):
        return None
    columns = [part.strip().strip('"') for part in header.rstrip("\r\n").split(",")]
    row_count = (row.get("fingerprint") or {}).get("parsed_row_count", 0)
    if len(columns) < 2 or not first_row or row_count < 2:
        return None
    return columns


def _example(name: str, message: str, state: dict, tool, *, question_as_written=None,
             redo_analysis=None, answer_expected=None, must_not_ask=False) -> dspy.Example:
    return dspy.Example(
        name=name,
        message=message,
        state=json.dumps(state, ensure_ascii=False),
        tool=tool,
        question_as_written=question_as_written,
        redo_analysis=redo_analysis,
        answer_expected=answer_expected,
        must_not_ask=must_not_ask,
    ).with_inputs("message", "state")


def _examples(row: dict, columns: list[str], index: int) -> list[dspy.Example]:
    source_id = row["dataset_id"]
    dataset_id, request_id, artifact_id = _ids(source_id)
    filename = (CORPUS / row["csv_path"]).name
    occurrences = row["occurrences"]
    question = occurrences[0]["question"]
    upload = f"\n\nAttached CSV: [{filename}](/datasets/{dataset_id}/profile)"
    dataset = {"dataset_id": dataset_id, "filename": filename, "columns": columns}

    def state(*, waiting=None, last_artifact=None):
        return {"datasets": [dataset], "waiting": waiting, "last_artifact": last_artifact}

    artifact = {"artifact_id": artifact_id, "question": question}
    waiting_question = WAITING_QUESTIONS[index % len(WAITING_QUESTIONS)]
    waiting = {"request_id": request_id, "question": waiting_question}
    answer = (f"Use the {columns[-1]} column." if index % 2 == 0 else "Income above 50000.")
    picture_change = PICTURE_CHANGES[index % len(PICTURE_CHANGES)]
    data_change = DATA_CHANGES[index % len(DATA_CHANGES)]
    continue_message = CONTINUE_MESSAGES[index % len(CONTINUE_MESSAGES)]
    report_request = REPORT_REQUESTS[index % len(REPORT_REQUESTS)]
    second_question = (occurrences[1]["question"] if len(occurrences) > 1
                       else f"How many rows are there per {columns[0]}?")
    prefix = source_id

    return [
        _example(f"{prefix}-question", question + upload, state(), ["draw", "answer_question"],
                 question_as_written=question, must_not_ask=True),
        _example(f"{prefix}-upload", upload.strip(), state(), "profile_csv"),
        _example(f"{prefix}-numbers", "Numbers only, no chart: " + question, state(),
                 "answer_question", question_as_written=[question, "Numbers only, no chart: " + question]),
        _example(f"{prefix}-picture-revise", picture_change, state(last_artifact=artifact), "revise",
                 redo_analysis=False),
        _example(f"{prefix}-data-revise", data_change, state(last_artifact=artifact), "revise",
                 redo_analysis=True),
        _example(f"{prefix}-answer", answer, state(waiting=waiting), "resume", answer_expected=True),
        _example(f"{prefix}-waiting-continue", continue_message, state(waiting=waiting), "resume",
                 answer_expected=False),
        _example(f"{prefix}-finished-continue", "Continue.", state(last_artifact=artifact), "none"),
        _example(f"{prefix}-find-artifact", "What did we make so far?", state(last_artifact=artifact),
                 "find_artifact"),
        _example(f"{prefix}-find-dataset", "Chart sales.csv by month.", state(), "find_dataset"),
        _example(f"{prefix}-new-question", second_question, state(last_artifact=artifact), "draw",
                 question_as_written=second_question),
        _example(f"{prefix}-report", report_request + upload, state(), ["draw", "answer_question"],
                 question_as_written=report_request, must_not_ask=True),
    ]


def build(seed: int = 7) -> tuple[list[dspy.Example], list[dspy.Example]]:
    """Return 360 train and 120 dev examples, twelve per source dataset."""
    heldout = {case["name"].removeprefix("corpus-") for case in corpus_cases()}
    eligible = []
    for row in read_manifest(CORPUS / "manifest.jsonl"):
        if row["dataset_id"] in heldout or not row.get("occurrences"):
            continue
        columns = _columns(row)
        if columns is not None:
            eligible.append((row, columns))

    rng = random.Random(seed)
    selected = rng.sample(eligible, 40)
    train_rows, dev_rows = selected[:30], selected[30:]
    train = [example for index, (row, columns) in enumerate(train_rows)
             for example in _examples(row, columns, index)]
    dev = [example for index, (row, columns) in enumerate(dev_rows, len(train_rows))
           for example in _examples(row, columns, index)]
    rng.shuffle(train)
    rng.shuffle(dev)
    return train, dev
