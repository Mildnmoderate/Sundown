from common.db import db
from common.llm import chat


def audit_summary(task_id, employee, all_ok):
    """Plain-English report for a reviewer, written from the event log. Never affects task state."""
    try:
        evs = list(db()["events"].find({"taskId": str(task_id)}).sort("ts", 1))
        log = "\n".join(f"{e['system']} | {e['state']} | {e['detail']}" for e in evs)[-3500:]
        text = chat(
            f"Offboarding of {employee}. Final outcome: "
            f"{'all access proven dead' if all_ok else 'NOT fully verified'}.\n"
            f"Event log:\n{log}\n\n"
            "Write a 3-sentence audit summary for a compliance reviewer: what was revoked, "
            "anything that lied, delayed or changed (and how the agent handled it), and the outcome. "
            "Use only facts in the log.",
            system="You write precise, factual audit summaries. No speculation.",
            max_tokens=220).strip()
        db()["tasks"].update_one({"_id": task_id}, {"$set": {"summary": text}})
        return text
    except Exception:
        return None