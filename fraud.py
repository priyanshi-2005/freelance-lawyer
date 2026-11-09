"""Verified first steps for suspected financial cyber fraud in India."""

from dataclasses import dataclass, field
import re

BANK_SOURCE = {
    "label": "Reserve Bank of India · Report a fraudulent transaction to your bank",
    "url": "https://www.rbi.org.in/commonman/english/Scripts/SMSLimitedliability.aspx",
}
CYBER_SOURCE = {
    "label": "Government of India · National Cyber Crime Reporting Portal",
    "url": "https://cybercrime.gov.in/",
}
OPTIONS = (
    {"id": "bank", "label": "Prepare the bank dispute"},
    {"id": "cyber", "label": "Prepare the cybercrime report"},
    {"id": "police", "label": "Prepare for a police visit"},
)
DIGITAL_PAYMENT = re.compile(r"\b(?:UPI|bank|wallet|debit card|credit card|payment app|QR(?: code)?)\b", re.I)
FRAUD = re.compile(r"\b(?:scam(?:med|mer)?|fraud(?:ulent)?|impersonat\w*|phishing|unauthori[sz]ed transaction)\b", re.I)
LOSS = re.compile(
    r"\b(?:went out|was (?:debited|transferred)|money (?:left|went out|was taken|is gone|was gone)|"
    r"debited from|charged me|gone from (?:my )?(?:account|bank)|deducted|disappeared|"
    r"(?:taken|withdrawn) from (?:my )?(?:account|bank))\b", re.I,
)
DECEPTION = re.compile(r"\b(?:QR(?: code)?|UPI PIN|OTP|refund)\b", re.I)
# Giving away a one-time code / PIN after unsolicited contact is the classic phishing step.
CODE_SHARED = re.compile(
    r"\b(?:shared|gave|told|sent|entered|typed|read out|verif(?:y|ied))\b[^.!?]{0,40}"
    r"\b(?:otp|pin|cvv|password|code|verification)\b", re.I,
)
# A transaction the person did not make / to a party they do not recognise.
UNAUTHORIZED = re.compile(
    r"\b(?:unauthori[sz]ed|never (?:approved|authori[sz]ed|made|did)|"
    r"didn['’]?t (?:approve|authori[sz]e|make|do)|did not (?:approve|authori[sz]e|make)|"
    r"without my (?:consent|permission|knowledge)|don['’]?t recogni[sz]e|"
    r"(?:number|account|person)\s+i\s+don['’]?t know)\b", re.I,
)
# Unsolicited-contact scam cues (a call/message/link asking you to verify or pay).
SCAM_CONTACT = re.compile(
    r"\b(?:got a call|received a call|call saying|someone called|fake (?:call|app|link|message|website)|"
    r"asked me to (?:verify|install|download|pay|scan)|verify on (?:an |the )?app|verification code)\b", re.I,
)
RECORD = re.compile(
    r"\b(?:call logs?|transaction (?:ID|reference)|bank statement|transaction alert|screenshots?|"
    r"bank complaint reference|cybercrime acknowledgement|messages?|emails?)\b", re.I,
)
AMOUNT = re.compile(r"(?:₹\s*|\bINR\s*|\bRs\.?\s*)(?P<amount>\d[\d,]*(?:\.\d{1,2})?)", re.I)
TIME = re.compile(r"\b(?:this morning|this afternoon|today|yesterday|last night|\d{4}-\d{2}-\d{2})\b", re.I)
CREDENTIAL = re.compile(r"(\b(?:UPI PIN|OTP|password)\s*(?:is|:|=)?\s*)\d{4,8}\b", re.I)
BANK_FILED = re.compile(r"\b(?:filed|submitted|raised)\b[^.!?]{0,35}\b(?:dispute|bank complaint)\b", re.I)
CYBER_FILED = re.compile(r"\b(?:called 1930|reported (?:it )?(?:on|to) (?:the )?(?:cybercrime portal|1930))\b", re.I)
DRAFT_REQUEST = re.compile(r"\b(?:draft|write|wording|what (?:do|should) I put)\b", re.I)


def channel_in(message):
    """Which official channel the person named, if any, so a direct draft request
    ('write a complaint to the bank') can go straight to that draft."""
    if re.search(r"\b(?:cyber\s?crime|1930|portal)\b", message, re.I):
        return "cyber"
    if re.search(r"\b(?:police|\bfir\b|station|thana)\b", message, re.I):
        return "police"
    if re.search(r"\bbank\b", message, re.I):
        return "bank"
    return ""


def is_financial_fraud(message):
    payment = DIGITAL_PAYMENT.search(message) or re.search(
        r"\b(?:account|my money|rupees|transaction)\b", message, re.I
    )
    if not payment:
        return False
    # Clear fraud signals: named fraud, an unauthorised/unknown debit, or a shared
    # one-time credential after contact.
    if FRAUD.search(message) or UNAUTHORIZED.search(message) or CODE_SHARED.search(message):
        return True
    # Money left the account together with a deception or scam-contact cue.
    if LOSS.search(message) and (DECEPTION.search(message) or SCAM_CONTACT.search(message)):
        return True
    return False


@dataclass
class FraudCase:
    facts: dict = field(default_factory=dict)
    records: set = field(default_factory=set)
    selected: str = ""

    def options(self):
        labels = {}
        if "Bank dispute" in self.facts:
            labels["bank"] = "Follow up on my bank dispute"
        if "Cybercrime report" in self.facts:
            labels["cyber"] = "Follow up on my cybercrime report"
        return [{**option, "label": labels.get(option["id"], option["label"])} for option in OPTIONS]

    def respond(self, message):
        initial = not self.facts
        safe = CREDENTIAL.sub(r"\1[redacted]", message)
        for sentence in re.split(r"(?<=[.!?])\s+", safe):
            if DECEPTION.search(sentence) and re.search(r"\b(?:called|told|asked|scan|enter|put in)\b", sentence, re.I):
                label = "What the caller asked" if re.search(r"\b(?:QR|UPI PIN|OTP)\b", sentence, re.I) else "How the contact started"
                self.facts.setdefault(label, sentence)
            if LOSS.search(sentence):
                self.facts["What happened to the money"] = sentence
                amount = AMOUNT.search(sentence)
                time = TIME.search(sentence)
                if amount:
                    self.facts["Reported loss"] = f"₹{amount['amount']}"
                if time:
                    self.facts["When it happened"] = time[0]
            if re.search(r"\bbank\b[^.!?]{0,45}\b(?:told|said|advised)\b", sentence, re.I):
                self.facts["What the bank said"] = sentence
            if UNAUTHORIZED.search(sentence):
                self.facts.setdefault("Unauthorised transaction", sentence)
        self.records.update(match[0].lower() for match in RECORD.finditer(safe))
        if BANK_FILED.search(safe) and not re.search(r"\b(?:not|haven['’]?t|didn['’]?t)\b", safe, re.I):
            self.facts["Bank dispute"] = "User says they submitted it"
        if CYBER_FILED.search(safe) and not re.search(r"\b(?:not|haven['’]?t|didn['’]?t)\b", safe, re.I):
            self.facts["Cybercrime report"] = "User says they contacted the reporting channel"
        self.facts.setdefault("Issue", "Suspected financial cyber fraud")

        if not initial and self.selected:
            return self.after_choice(safe)

        if not initial:
            # If the person directly asks to write/draft and names a channel,
            # prepare that draft now instead of asking them to pick again.
            if DRAFT_REQUEST.search(safe):
                channel = channel_in(safe)
                if channel:
                    self.selected = channel
                    return self.after_choice(safe)
            return {
                "reply": "I’ve added any newly reported details to the case file. Choose which step you want help preparing.",
                "choices": OPTIONS,
            }
        bank_step = (
            "Use the dispute option in your bank’s official app, as the bank advised, and save the complaint reference."
            if "What the bank said" in self.facts and re.search(r"\bapp\b", self.facts["What the bank said"], re.I)
            else "Notify your bank immediately through its official app or fraud number. Ask for a complaint reference."
        )
        if "Bank dispute" in self.facts:
            bank_step = "Keep the acknowledgement from the bank dispute you already submitted."
        cyber_step = (
            "Keep the acknowledgement from the cybercrime channel you already contacted."
            if "Cybercrime report" in self.facts else
            "Call 1930 or use the National Cyber Crime Reporting Portal right away. You can do this while the bank dispute is being handled."
        )
        evidence = ", ".join(sorted(self.records)) if self.records else "transaction confirmations, messages, and call records"
        return {
            "reply": (
                "This sounds like suspected financial cyber fraud. If this happened in India, take the first two steps right away.\n\n"
                f"1. {bank_step}\n"
                f"2. {cyber_step}\n"
                f"3. Keep these records if available: {evidence}. Leave out PINs, OTPs, and passwords.\n\n"
                "Which step would you like help preparing?"
            ),
            "sources": [BANK_SOURCE, CYBER_SOURCE],
            "choices": OPTIONS,
        }

    def choose(self, choice):
        self.selected = choice
        if choice == "bank":
            question = (
                "Did the bank give you a complaint reference or say what it needs next?"
                if "Bank dispute" in self.facts else
                "Have you submitted the dispute in the bank’s official app, or would you like help wording it first?"
            )
            return {"reply": question}
        if choice == "police":
            return {"reply": (
                "If you plan to speak to police in person, bring the transaction record, call log, "
                "and any complaint acknowledgement. Would you like a written account to bring with you?"
            )}
        question = (
            "Did the cybercrime channel give you an acknowledgement or ask for any further information?"
            if "Cybercrime report" in self.facts else
            "Have you already called 1930 or started a report on the portal? If a form asks for a field you’re unsure about, tell me its label."
        )
        return {"reply": question}

    def after_choice(self, message):
        if DRAFT_REQUEST.search(message) or (self.selected == "police" and re.fullmatch(r"yes[.!]?", message, re.I)):
            title, recipient = {
                "bank": ("Draft bank fraud dispute", "Bank fraud team"),
                "cyber": ("Draft cybercrime report", "Cybercrime reporting team"),
                "police": ("Draft police complaint", "[police station or cybercrime unit]"),
            }[self.selected]
            draft, _ = self.draft()
            return {
                "reply": "Here is a draft to review and copy into the official channel. Check the transaction details against your bank record before submitting.",
                "draft": f"To: {recipient}\n\nI am reporting a suspected financial cyber fraud.\n\n"
                         + draft + "\n\nTransaction reference: [enter from your bank record]\n"
                         "Complaint contact details: [enter in the official form if required]",
                "draft_title": title,
            }
        if self.selected == "bank":
            return {"reply": (
                "For the bank dispute, describe how the caller contacted you, what they asked you to do, "
                "and the transaction amount and time you can verify. Use the transaction reference from "
                "your bank record and save the complaint acknowledgement. If the bank asks for a specific "
                "field, tell me its label and I can help match it to the facts you’ve shared."
            )}
        if self.selected == "police":
            return {"reply": "Keep the original evidence and the complaint references. Ask me to draft a written account if you want something to bring to the station."}
        return {"reply": (
            "For the cybercrime report, describe the caller’s instructions, when the money left, "
            "and what records you have. Use the amount and reference from your bank record. "
            "If the portal asks for a specific field, tell me its label and I can help match it to your case."
        )}

    def view(self):
        return {
            "facts": self.facts,
            "records": {"Suspected financial fraud": sorted(self.records)} if self.records else {},
        }

    def draft(self):
        lines = [f"{label}: {value}" for label, value in self.facts.items()]
        if self.records:
            lines.append("Reported evidence: " + ", ".join(sorted(self.records)))
        return "\n".join(lines), "Review these reported details before sharing them."
