"""Case state, evidence rules and fixed legal text for the scoped prototype."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

SOURCE = {
    "label": "India Code · Indian Contract Act, 1872 · Section 37",
    "url": "https://www.indiacode.nic.in/bitstream/123456789/2187/2/A187209.pdf",
}
LEGAL_CONTEXT = (
    "Section 37 of the Indian Contract Act says parties to a contract generally have to "
    "perform or offer to perform their promises, subject to legal exceptions. "
    "Whether that applies to your situation depends on the agreement and the facts. "
    "A lawyer can assess your records and options if the client disputes the work or payment."
)
MONEY = r"(?:₹\s*|(?:Rs\.?|INR)\s*)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)(?![\d,]|\.\d)"
FEE_PATTERNS = (
    rf"(?:agreed(?:\s+(?:on|to pay|fee|price|amount|at|on a fee of))?|total fee(?:\s+was)?|fee(?:\s+(?:of|was|is))?|price(?:\s+(?:of|was|is))?|quoted)\s*[:=]?\s*{MONEY}",
    rf"(?:they|client|organizer|organiser)\s+(?:owed|promised)(?:\s+me)?\s+{MONEY}",
    rf"(?:designed|made|created|hired me to make)\b[^.!?]{{0,90}}?\bfor\s+(?=[₹\d]|rs\b|inr\b){MONEY}",
)
PAID_PATTERNS = (
    rf"(?:paid\s+me|they\s+paid|(?:i\s+)?(?:received|got)|paid\s+so\s+far)\s+(?:me\s+)?(?:only\s+)?{MONEY}",
    rf"{MONEY}\s+(?:received|paid so far)",
)
NO_PAYMENT = re.compile(
    r"\b(?:haven['’]?t (?:received|been paid)(?: anything)?|no payment|nothing(?: yet| so far)?|"
    r"not(?: been)? paid(?: anything)?|didn['’]?t pay(?: me)?(?: anything)?|paid (?:me )?nothing|"
    r"received (?:nothing|zero))\b", re.I
)
MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
DATE = (
    r"(?:last|next|this)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|week|month)"
    r"|(?:yesterday|today|tomorrow)"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH})(?:\s+\d{{4}})?"
    rf"|(?:{MONTH})\s+\d{{1,2}}(?:,?\s+\d{{4}})?"
)
WORK = re.compile(r"\b(?:posters?|flyers?|logos?|banners?|brochures?|illustrations?|graphics?|designs?)\b", re.I)
OUTSIDE = re.compile(r"\b(?:eviction|landlord|tenancy|salary|employer|arrest|divorce|consumer refund)\b", re.I)
LEGAL_REQUEST = re.compile(r"\b(?:law|section|statute|case law|guarantee\w*|court|legal rights)\b", re.I)
DISPUTE = re.compile(
    r"\b(?:disput\w*|incomplete|unfinished|not finished|wasn['’]?t finished|didn['’]?t finish|"
    r"never finish\w*|not delivered|reject\w*|den(?:y|ies|ied)\b.{0,45}\b(?:agreed|owe|fee|payment))\b",
    re.I,
)
RECORD = re.compile(r"\b(?:WhatsApp(?: chat)?|e-?mails?|invoices?|contracts?|screenshots?|"
                    r"bank statements?|receipts?|delivery logs?|written agreements?|messages?)\b", re.I)
RECORD_REFERENCE = re.compile(
    r"\b(?:the same|that) (?P<kind>chat|conversation|e-?mail|invoice|screenshot|messages?)\b", re.I
)
CLIENT_RESPONSE = re.compile(
    r"\b(?:they|client|organizer|organiser)\b"
    r"(?:\s+[^.!?]{0,90}?\s+and)?\s+"
    r"(?:said|replied|says|responded|(?:hasn['’]?t|haven['’]?t|didn['’]?t) (?:reply|replied|respond|responded))\b",
    re.I,
)
QUESTIONS = {
    "work": "What design work did you agree to do for the client?",
    "fee": "What was the agreed total fee in rupees?",
    "paid": "How much have you received in total so far? If you’ve received nothing, say so.",
    "due": "When did the client agree to pay you?",
    "delivery": "Did you send the finished work, and how did the client respond to it?",
    "terms": "Do you have any record showing the agreed fee or due date, or was it agreed verbally?",
    "client": "Has the client replied about the payment? If so, what reason did they give?",
}
LABELS = {
    "work": "Design work", "fee": "Agreed fee", "paid": "Received so far", "due": "Agreed payment date",
    "delivery": "Delivery or approval", "client": "Client response", "terms": "Agreement records",
    "delivered_on": "Delivery date", "approved_on": "Approval date", "revisions": "Agreed revisions",
}


def amount_from(patterns, message):
    for pattern in patterns:
        for match in re.finditer(pattern, message, re.I):
            before = re.split(r"[.!?;,]", message[:match.start()])[-1]
            if not re.search(r"\b(?:never|not|haven['’]?t|didn['’]?t)\s+(?:yet\s+)?$", before, re.I):
                return Decimal(match["amount"].replace(",", ""))
    return None


def money(value):
    return f"₹{value:,.2f}".removesuffix(".00")


def verified_quote(value, message, limit):
    if isinstance(value, str) and 1 <= len(value) <= limit:
        match = re.search(re.escape(value), message, re.I)
        if match:
            return match[0]
    return None


def record_kind(name):
    kind = name.lower().replace("-", "").rstrip("s")
    return "chat" if kind.startswith("whatsapp") or kind == "conversation" else kind


@dataclass
class CaseFile:
    facts: dict = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    asked: set = field(default_factory=set)
    last_question: str = ""
    disputed: bool = False

    @property
    def balance(self):
        fee, paid = self.facts.get("fee"), self.facts.get("paid")
        return fee - paid if fee is not None and paid is not None else None

    def view(self):
        values = {LABELS[key]: money(value) if isinstance(value, Decimal) else value
                  for key, value in self.facts.items()}
        if self.balance is not None:
            values["Outstanding balance"] = money(self.balance) if self.balance >= 0 else "Amounts need checking"
        if self.disputed:
            values["Dispute"] = "The client’s position needs review."
        return {
            "facts": values,
            "records": {label: sorted(items) for label, items in self.records.items()},
        }

    def update(self, message, extracted):
        facts = self.facts
        hint = self.last_question
        work = verified_quote(extracted.get("work"), message, 55)
        work_match = WORK.search(message)
        if work and WORK.search(work) and work_match:
            if len(work.split()) <= 5 and re.fullmatch(r"[\w -]+", work):
                facts.setdefault("work", work)
        elif work_match:
            facts.setdefault("work", work_match[0])
        if hint == "work" and work_match:
            facts["work"] = work if work and re.fullmatch(r"[\w -]{1,55}", work) else work_match[0]

        fee, paid = amount_from(FEE_PATTERNS, message), amount_from(PAID_PATTERNS, message)
        if fee is None and "fee" not in facts and not re.search(r"\b(?:balance|remaining|outstanding|still)\b", message, re.I):
            fee = amount_from((rf"{MONEY}\s*(?:was|is)\s+due",), message)
        short_amount = amount_from((rf"^\s*{MONEY}\s*(?:rupees|rs\.?|inr)?\s*[.!]?\s*$",), message)
        if hint == "fee" and fee is None:
            fee = short_amount
        if hint == "paid" and paid is None:
            paid = short_amount
        if paid is None and (
            re.search(r"\b(?:no payment|received nothing|paid nothing|haven['’]?t received anything)\b", message, re.I)
            or (hint == "paid" and NO_PAYMENT.search(message)
                and not re.search(r"\b(?:writing|record|proof)\b", message, re.I))
        ):
            paid = Decimal(0)
        if paid is not None and re.search(r"\b(?:another|additional|more)\b", message, re.I):
            facts.pop("paid", None)
            self.asked.discard("paid")
            paid = None
        if fee is not None:
            facts["fee"] = fee
        if paid is not None:
            facts["paid"] = paid

        date = re.search(rf"\b(?:due(?: date was)?|payment date(?: was)?|pay(?: me)?(?: by| on)?)\s+(?:on\s+)?(?P<date>{DATE})\b", message, re.I)
        if not date and hint == "due":
            date = re.search(rf"(?P<date>{DATE})\b", message, re.I)
        if date:
            facts["due"] = date["date"]
        elif "due" not in facts and (hint == "due" or re.search(r"\bdue\b", message, re.I)):
            model_date = verified_quote(extracted.get("due"), message, 40)
            if model_date and re.fullmatch(DATE, model_date, re.I):
                facts["due"] = model_date

        disputed = bool(DISPUTE.search(message)) and not re.search(r"\b(?:no dispute|never disputed)\b", message, re.I)
        if disputed:
            self.disputed = True
            facts["delivery"] = "Disputed by the client"
        elif not self.disputed and re.search(r"\b(?:approved|accepted|signed off)\b", message, re.I):
            if not re.search(r"\b(?:not|never|haven['’]?t|didn['’]?t)\b[^.!?]{0,25}\b(?:approved|accepted)\b", message, re.I):
                facts["delivery"] = "Approval reported"
        elif not self.disputed and (
            re.search(r"\b(?:sent|delivered|submitted|handed over)\b", message, re.I)
            and not re.search(r"\b(?:sent|submitted)\s+(?:(?:the|my|an?)\s+)?invoice\b", message, re.I)
            or (extracted.get("delivery") == "delivered" and re.search(r"\b(?:shared|uploaded)\b", message, re.I))
        ):
            facts.setdefault("delivery", "Delivery reported")

        for event, pattern in (
            ("delivered_on", r"(?:sent|delivered|submitted|handed over)"),
            ("approved_on", r"(?:approved|accepted|signed off)"),
        ):
            dated = re.search(rf"\b{pattern}\b[^.!?,]{{0,55}}?\s+on\s+(?P<date>{DATE})\b", message, re.I)
            if dated and not re.search(r"\b(?:not|never|invoice)\b", dated[0], re.I):
                facts[event] = dated["date"]
        revisions = verified_quote(extracted.get("revisions"), message, 120)
        if revisions and re.search(r"\b(?:agreed|included)\b", message, re.I):
            facts["revisions"] = revisions

        sentences = re.split(r"[!?\n]+|(?<=\.)\s+", message)
        client_response = next((sentence for sentence in reversed(sentences) if CLIENT_RESPONSE.search(sentence)), None)
        if hint == "client" or disputed or client_response:
            facts["client"] = (client_response or verified_quote(extracted.get("client"), message, 180) or message)[:180]
        if re.search(r"\b(?:verbal(?:ly)?|over (?:a|the) call|nothing in writing|no written)\b", message, re.I):
            facts["terms"] = "Verbal agreement or missing written record reported"
        previous_records = set()
        for sentence in sentences:
            if re.search(r"\b(?:no|don['’]?t have|do not have|lost)\b.{0,30}\b(?:WhatsApp|invoice|contract|messages?|record)\b", sentence, re.I) or re.search(
                r"\b(?:doesn['’]?t|don['’]?t|didn['’]?t|does not|do not|did not)\s+(?:show|contain|mention|confirm)\b",
                sentence, re.I,
            ):
                previous_records = set()
                continue
            references = list(RECORD_REFERENCE.finditer(sentence))
            records = {
                match[0] for match in RECORD.finditer(sentence)
                if not any(reference.start() <= match.start() < reference.end() for reference in references)
            }
            for reference in references:
                candidates = {name for name in previous_records if record_kind(name) == record_kind(reference["kind"])}
                if len(candidates) == 1:
                    records.update(candidates)
            previous_records = records
            if not records:
                continue
            delivery = re.search(r"\b(?:approved|accepted|delivered|sent|signed off)\b", sentence, re.I)
            terms = re.search(r"\b(?:fee|due date|agreed|amount|price|payment date)\b", sentence, re.I)
            if hint == "terms" and not delivery and "terms" not in facts:
                terms = True
            if terms:
                self.records.setdefault("Fee or due date", set()).update(records)
                facts["terms"] = "Record reported for fee or due date"
            if delivery:
                self.records.setdefault("Delivery or approval", set()).update(records)
            if not terms and not delivery:
                self.records.setdefault("Other records", set()).update(records)
        if hint == "terms" and re.fullmatch(r"(?:no|none|nothing)[.!]?", message, re.I):
            facts["terms"] = "No record reported"

    def explain(self):
        if not self.facts:
            return "Tell me a little about the design job and what happened with the payment."
        support = []
        approval_records = self.records.get("Delivery or approval")
        agreement_records = self.records.get("Fee or due date")
        shared_record = approval_records and len(approval_records) == 1 and approval_records == agreement_records
        if shared_record:
            support.append("The same record you described may help show what the client accepted and what you agreed about payment.")
        else:
            if approval_records:
                support.append("The delivery or approval record you described may help show what the client received or accepted.")
            if agreement_records:
                support.append("The agreement record you described may help show the fee, due date, or both.")
        if not agreement_records and "terms" in self.facts:
            support.append("Write down what was agreed and look for delivery messages, an invoice, or a later acknowledgment that could help clarify the terms.")
        if self.disputed:
            support.append("Keep the agreed revisions, delivered versions, and client objection separate. Ask a lawyer to review them before escalating.")
        elif self.balance is not None and self.balance > 0:
            support.append("You can review a formal payment demand that sets out the balance and asks for payment by a date you choose.")
        return " ".join(support) or "Start by checking whether you have messages or an invoice that support the agreed fee and payment date."

    def draft(self):
        balance = self.balance
        if self.disputed:
            return None, "A lawyer should review the disputed work or terms before you send a formal demand. You can use the case file to prepare."
        if balance is None or balance <= 0 or not all(self.facts.get(key) for key in ("work", "due", "delivery")):
            return None, "A draft needs the agreed work, delivery or approval, the agreed due date, and a positive outstanding balance. Fill those gaps in the chat first."
        date = self.facts["due"]
        exact = date.replace(",", "")
        exact = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", exact, flags=re.I)
        for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y",
                            "%d %b %Y", "%B %d %Y", "%b %d %Y"):
            try:
                exact = datetime.strptime(exact, date_format).date()
                break
            except ValueError:
                continue
        is_future = (
            exact >= datetime.now(ZoneInfo("Asia/Kolkata")).date()
            if not isinstance(exact, str)
            else re.match(r"(?:next|today|tomorrow)\b", date, re.I)
        )
        if is_future:
            return None, "The due date you gave appears to be in the future. A demand for overdue payment needs a past due date."
        if re.match(r"(?:last|this|next|today|yesterday|tomorrow)\b", date, re.I):
            date = f"[exact original due date — you said {date}]"
        draft = (
            "Subject: Formal request for outstanding design payment\n\n"
            "Dear [client name],\n\n"
            f"I am writing to request payment for the {self.facts['work']} work I completed for you. "
            f"The agreed fee was {money(self.facts['fee'])}. The payment was due on {date}, "
            f"and the outstanding balance is {money(balance)}.\n\n"
            f"Please pay {money(balance)} by [payment deadline you choose]. If you have already "
            "made the payment or believe a detail needs correcting, please reply with the details.\n\n"
            "Regards,\n[your name]"
        )
        return draft, "Review the facts and fill in the brackets before sending. You can copy the draft below."

    def respond(self, message, model):
        if OUTSIDE.search(message) and not WORK.search(message):
            return "I can help with freelance design payment disputes in India. For this issue, consider speaking to a lawyer who handles that area."
        if re.search(r"\b(?:guarantee\w*|cite\s+(?:a\s+)?(?:law|section))\b", message, re.I):
            return "I can’t verify a law that guarantees payment or a particular result. I can help organize your records and explain the limited legal context available here."
        extracted = model.extract(message)
        if (not self.facts and not WORK.search(message) and extracted.get("topic") == "unrelated"):
            return "I can help with freelance design payment disputes in India. For this issue, consider speaking to a lawyer who handles that area."
        if LEGAL_REQUEST.search(message) and not WORK.search(message) and not self.facts:
            return "Tell me what design work you agreed to do and what happened with the payment. I can explain the general contract rule once I know what you’re asking about."
        self.update(message, extracted)
        if self.disputed:
            reply = self.explain()
            if "dispute_detail" not in self.asked:
                self.asked.add("dispute_detail")
                return reply + " What revisions did you agree to, and which version did you deliver?"
            return reply
        if self.balance is not None and self.balance <= 0:
            if self.balance == 0:
                return "The amounts you gave show no balance outstanding. If any figure is different, tell me the corrected total fee or total received."
            return "The amount received is higher than the agreed fee you gave. What are the correct totals?"
        if LEGAL_REQUEST.search(message):
            return LEGAL_CONTEXT
        for key, question in QUESTIONS.items():
            if key not in self.facts and key not in self.asked:
                self.asked.add(key)
                self.last_question = key
                return question
        self.last_question = ""
        return self.explain()
