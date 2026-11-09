"""Choose practical preparation steps without inventing a legal route."""

import re

CASE_PDF = {"id": "case_pdf", "label": "Download case file as PDF"}
TITLES = {
    "reply": "Draft reply",
    "notice": "Draft notice for lawyer review",
    "complaint": "Draft complaint for review",
    "application": "Draft application for review",
}


ISSUE_ACTIONS = {
    "payment": (("reply", "Write to my client about payment"),
                ("notice", "Draft a payment notice for lawyer review")),
    "notice": (("lawyer", "Get the notice reviewed by a lawyer"),
               ("reply", "Ask the sender to clarify the notice")),
    "deposit": (("reply", "Ask my landlord about the deposit"),
                ("notice", "Draft a deposit notice for lawyer review")),
    "housing": (("reply", "Write to my landlord"),
                ("lawyer", "Prepare for a tenancy lawyer consultation")),
    "signing": (("lawyer", "Get the document reviewed before signing"),
                ("reply", "Ask the sender to explain or correct the wording")),
    "pay": (("reply", "Write to payroll about the missing pay"),
            ("lawyer", "Get help reviewing the pay dispute")),
    "work": (("reply", "Ask my employer for a written explanation"),
             ("lawyer", "Prepare to discuss the work issue with a lawyer")),
    "refund": (("reply", "Write a refund request to the business"),
               ("complaint", "Prepare a complaint about the refund")),
    "membership": (("reply", "Write to the membership accounts team"),
                   ("complaint", "Prepare a complaint about the charge")),
    "repair": (("reply", "Write to the repair shop"),
               ("complaint", "Prepare a complaint about the repair")),
    "loan": (("reply", "Ask my friend to repay the money"),
             ("lawyer", "Get help reviewing the loan records")),
    "consumer": (("reply", "Write to the business about the purchase"),
                 ("complaint", "Prepare a complaint about the purchase")),
    "photo_ad": (("reply", "Write to the advertiser about my photo"),
                 ("complaint", "Prepare a report about the ad")),
    "photo_ad_hinglish": (("reply", "Advertiser ko photo ke baare mein message likho"),
                          ("complaint", "Ad report karne ke liye message taiyaar karo")),
    "property": (("lawyer", "Get the property papers reviewed"),
                 ("reply", "Ask for the papers behind the transfer")),
    "family": (("lawyer", "Prepare to speak with a family lawyer"),
               ("reply", "Write a message about the family issue")),
    "police": (("complaint", "Prepare what to tell the police"),
               ("lawyer", "Review the incident with a lawyer")),
    "other": (("reply", "Draft a message about the issue"),
              ("lawyer", "Organize the key details for a lawyer")),
}


def ordered_actions(topic, story, *, has_notice=False, payment=False, review_first=False, has_form=False, kind=""):
    issue = kind or topic
    if payment:
        issue = "payment"
    elif has_notice:
        issue = "notice"
    elif re.search(r"\b(?:property records|transferred to|inheritance)\b", story, re.I) and re.search(
        r"\b(?:will|house|inheritance)\b", story, re.I
    ):
        issue = "property"
    elif review_first:
        issue = "signing"
    elif topic == "housing" and re.search(r"\bdeposit\b", story, re.I):
        issue = "deposit"
    elif topic == "work" and re.search(r"\b(?:salary|wages|missing pay|unpaid|payroll|paid me)\b", story, re.I):
        issue = "pay"
    elif topic == "consumer" and re.search(r"\brefund\b", story, re.I):
        issue = "refund"
    elif topic == "photo_ad" and re.search(r"\b(?:mujhe|meri|maine|kya bolun)\b", story, re.I):
        issue = "photo_ad_hinglish"
    choices = [{"id": key, "label": label} for key, label in ISSUE_ACTIONS[issue]]
    if has_form:
        choices.append({"id": "application", "label": "Match my details to the uploaded form"})
    return choices


def action_prompt(choice, facts, has_form):
    goal = facts.get("What you want to happen")
    if choice == "application":
        if has_form:
            return ""
        return "Upload the application using Form, or tell me the application name and who receives it. I can use details you’ve already shared to help you prepare it."
    if choice == "reply":
        return (
            "Who is receiving the reply? You can use a role such as landlord or employer."
            if goal else "Who is receiving the reply, and what do you want them to do?"
        )
    if choice == "notice":
        return (
            "Who should receive the notice? I’ll mark it as a draft for a lawyer to review."
            if goal else "Who should receive the notice, and what are you asking them to do? A lawyer should review the draft."
        )
    return "Who should receive the complaint? If they sent a form or notice, attach it and I’ll help you match the fields."


def draft_for(choice, case, user_answer="", evidence=(), *, recipient="", goal=""):
    facts = case["facts"]
    goal = goal or facts.get("What you want to happen")
    lines = [f"To: {recipient or '[confirm the recipient]'}"]
    if goal:
        lines.extend(("", "What I’m asking for", goal))
    lines.extend(("", "Reported details"))
    for label, value in facts.items():
        if label not in ("What you want to happen", "Issue") and value:
            lines.append(f"{label}: {value}")
    if user_answer:
        lines.extend(("", "Details you added for this draft", user_answer))
    records = [name for names in case["records"].values() for name in names]
    evidence = list(evidence)
    if records or evidence:
        lines.extend(("", "Records to check before sharing"))
        lines.extend(f"- {record}" for record in records)
        lines.extend(f"- {name}" for name in evidence)
    if not goal:
        lines.extend(("", "Requested response: [state what you want the recipient to do]"))
    lines.extend(("", "[your name]"))
    return TITLES[choice], "\n".join(lines)
