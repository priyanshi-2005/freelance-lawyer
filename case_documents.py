"""Session-local evidence, form review and PDF export shared by app frontends."""

from contextlib import closing
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path
import re
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from casework import money

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UPLOADS = 4
MAX_PAGES = 10
MAX_PAGE_TEXT = 8000
IMAGE_LIMIT = 20_000_000
SECRET = re.compile(r"(\b(?:UPI PIN|OTP|password)\s*(?:is|was|:|=)?\s*)\d{4,8}\b", re.I)
FIELD_LINE = re.compile(r"^\s*(?:\d+[.)]\s*)?(?P<label>[^:=_]{2,75}?)(?:\s*[:=]\s*(?P<value>.*)|\s+_{2,}\s*)$")
FIELD_WORD = re.compile(
    r"\b(?:name|email|address|phone|mobile|city|state|date|time|amount|reference|transaction|"
    r"complaint|incident|description|details|bank|branch|signature|contact|account|order|purpose|"
    r"relationship|occupation|period|identification|designation|number|reason)\b", re.I
)
PLAIN_FORM_LABEL = re.compile(
    r"^(?:full name|name of .{2,55}|applicant name|complainant name|"
    r"(?:transaction|complaint|incident) (?:id|reference|date|time|amount|description)|"
    r"date of .{2,40}|mobile number|phone number|email address|city|state|signature)$", re.I,
)
SENSITIVE_FIELD = re.compile(r"\b(?:PIN|OTP|password|CVV|Aadhaar|account number|card number)\b", re.I)
EVIDENCE_SIGNAL = re.compile(
    r"\b(?:received|approved|confirmed|requested|cancel\w*|refund\w*|denied|rejected|"
    r"deduct\w*|charged|paid|debited|due|deadline|vacate|appear|delivered|disput\w*)\b|₹",
    re.I,
)
CANCELLATION_RECEIPT = re.compile(
    r"\b(?:received (?:your |the )?(?:request|cancellation request)|"
    r"(?:request|cancellation request)(?:\s*:\s*|\s+)(?:has been |was )?received)\b", re.I,
)
MEMBERSHIP_ENDED = re.compile(
    r"\b(?:membership|subscription)\s+(?:(?:has|had)\s+(?:been\s+)?|(?:is|was)\s+)?"
    r"(?:cancell?ed|ended|terminated)\b|\bcancellation\s+(?:has been |is |was )?confirmed\b", re.I,
)
MEMBERSHIP_SCHEDULED = re.compile(
    r"\b(?:membership|subscription)\s+(?:will end|will be cancell?ed|ends on|is set to end)\b"
    r"|\b(?:membership|subscription) end date\s*:\s*\S", re.I,
)
MEMBERSHIP_ACTIVE = re.compile(
    r"\b(?:membership|subscription)\s+(?:is still active|(?:has|is|was) not (?:been )?(?:cancell?ed|ended))\b"
    r"|\bcancellation\s+(?:request\s+)?(?:is pending|has not been approved|is not confirmed)\b", re.I,
)
MEMBERSHIP_UNCERTAIN = re.compile(
    r"\b(?:if|whether|once|after|may|might|would|please confirm|can you|not|never)\b", re.I,
)
DOCUMENT_REFERENCE = re.compile(r"\b(?:attach\w*|upload\w*|letter|document|file|email|notice|pdf|screenshot)\b", re.I)
DOCUMENT_QUESTION = re.compile(
    r"\b(?:check|read|explain|summari[sz]e|what (?:does|did|is|was|do)|does (?:it|this|the)|"
    r"how much|when (?:does|do|is|was|did)|tell me (?:what|whether|if|how|when)|"
    r"is (?:this|it|that|the \w+) (?:right|correct|legal|valid|allowed|fair|ok|okay|genuine|real|a scam)|"
    r"can (?:they|he|she|i)\b|are they (?:allowed|able|right)|should i\b|is this)\b", re.I,
)
REFUND_QUESTION = re.compile(r"\b(?:refund\w*|return\w*|give (?:me )?back|pay (?:me )?back|get back|wapas)\b", re.I)
REFUND_AMOUNT = (
    r"(?<![\d,.])(?P<amount>(?:(?:₹|INR\b|Rs\.?)\s*)?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(?:\.\d{1,2})?)"
    r"(?!\w|[.,]\d|,,|/|\s+\d|\s+(?:k|lakhs?|crores?|thousand|days?|weeks?|months?|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b)"
)
DEPOSIT_REFUND_LINES = tuple(re.compile(pattern, re.I) for pattern in (
    rf"\b(?:net (?:amount |balance )?refund(?:able)?|(?:security )?deposit (?:refund|to be returned)|"
    rf"(?:amount|balance) to be (?:returned|refunded)|(?:final )?refund(?: amount| payable| due)?|refundable (?:balance|amount))\s*[:=]\s*{REFUND_AMOUNT}",
    rf"\b(?:(?:net |deposit )?refund (?:will be|is)|(?:amount|balance) (?:we|I) will (?:refund|return) is)\s+{REFUND_AMOUNT}",
    rf"(?:\b(?:will|shall|intend to|plan to|agreed to)\b|['’]ll)\s+(?:refund|return|give back|pay back)\s+"
    rf"(?:you\s+)?(?:(?:the (?:remaining )?balance|an? (?:amount|sum)) of\s+)?{REFUND_AMOUNT}",
    rf"{REFUND_AMOUNT}\s+(?:(?:security )?deposit\s+)?(?:will|shall)\s+be\s+(?:refunded|returned|paid back)\b",
    rf"\b(?:a |the )?(?:deposit )?refund of\s+{REFUND_AMOUNT}\s+(?:will|shall)\s+be\s+(?:paid|issued|sent|processed)\b",
))
CHAT_FIELDS = {
    "Full name": re.compile(r"\bmy (?:full )?name is (?P<value>[\w -]{2,65})(?=[.!?;,]|$)", re.I),
    "Transaction ID": re.compile(r"\b(?:transaction (?:ID|reference)|UTR)(?: is|:|=)\s*(?P<value>[A-Z0-9-]{5,40})\b", re.I),
    "Transaction date": re.compile(r"\btransaction date(?: was| is|:|=)\s*(?P<value>[^.!?;]{3,45})", re.I),
    "Email address": re.compile(r"\bmy email(?: address)? is (?P<value>[\w.+-]+@[\w.-]+\.[a-z]{2,})\b", re.I),
}


@dataclass
class Attachment:
    name: str
    media_type: str
    content: bytes
    purpose: str
    pages: list = field(default_factory=list)
    fields: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex)

    def link(self):
        return {"name": self.name, "url": f"/files/{self.id}"}

    def view(self):
        return {
            **self.link(),
            "purpose": self.purpose,
            "pages": [{"page": page, "method": method, "preview": text[:400]}
                      for page, method, text in self.pages],
        }


def cleaned(text):
    return SECRET.sub(r"\1[redacted]", text.strip())[:MAX_PAGE_TEXT]


@lru_cache(maxsize=1)
def ocr_engine():
    import onnxruntime
    from rapidocr import RapidOCR

    onnxruntime.disable_telemetry_events()
    return RapidOCR(params={
        "Global.log_level": "error",
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    })


def read_image(image):
    import numpy as np

    if image.width * image.height > IMAGE_LIMIT:
        raise ValueError("Choose a smaller photo or scan.")
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((1900, 1900))
    result = ocr_engine()(np.asarray(image)[:, :, ::-1].copy())
    if result.txts is None or result.scores is None:
        return ""
    return cleaned("\n".join(text for text, score in zip(result.txts, result.scores) if score >= 0.72))


def read_pdf(content, purpose):
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("Upload an unlocked copy of the PDF.")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"Upload a PDF with at most {MAX_PAGES} pages.")
    pages, fields = [], []
    scan_document = None
    try:
        for index, page in enumerate(reader.pages):
            text = cleaned(page.extract_text() or "")
            method = "PDF text"
            if len(re.sub(r"\s", "", text)) < 12:
                if scan_document is None:
                    from pypdfium2 import PdfDocument

                    scan_document = PdfDocument(content)
                with closing(scan_document[index]) as scan_page:
                    width, height = scan_page.get_size()
                    scale = min(2.5, 1800 / max(width, height, 1))
                    with closing(scan_page.render(scale=scale)) as bitmap:
                        text = read_image(bitmap.to_pil())
                method = "OCR"
            pages.append((index + 1, method, text))
        for name, item in (reader.get_fields() or {}).items():
            if item.get("/Kids") and not item.get("/FT"):
                continue
            label = cleaned(str(item.get("/TU") or name))
            if label:
                location = "PDF form field, marked required" if int(item.get("/Ff", 0)) & 2 else "PDF form field"
                fields.append((label, location))
    finally:
        if scan_document is not None:
            scan_document.close()
    return pages, fields


def add_attachment(name, content, purpose):
    name = Path(name.replace("\\", "/")).name
    if not name or len(name) > 180 or purpose not in ("evidence", "form"):
        raise ValueError("Choose an evidence file or a form with a valid name.")
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty file no larger than 5 MB.")
    try:
        if content.startswith(b"%PDF-"):
            pages, fields = read_pdf(content, purpose)
            media_type = "application/pdf"
        else:
            with Image.open(BytesIO(content), formats=("JPEG", "PNG")) as image:
                media_type = Image.MIME[image.format]
                pages = [(1, "OCR", read_image(image))]
            fields = []
    except (PdfReadError, UnidentifiedImageError, Image.DecompressionBombError, OSError, RuntimeError):
        raise ValueError("I couldn’t read that file. Try a clear PNG, JPG, or unlocked PDF.") from None
    if not fields:
        for page, method, text in pages:
            for line in text.splitlines():
                match = FIELD_LINE.match(line)
                if match and FIELD_WORD.search(match["label"]):
                    fields.append((match["label"].strip(), f"page {page}, {method}"))
                elif PLAIN_FORM_LABEL.fullmatch(line.strip()):
                    fields.append((line.strip(), f"page {page}, {method}"))
    return Attachment(name, media_type, content, purpose, pages, list(dict.fromkeys(fields))[:60])


def field_key(label):
    label = re.sub(r"[^a-z0-9 ]", " ", label.lower())
    label = re.sub(r"\b(?:required|optional|enter|please|your|the|of|on)\b", "", label)
    label = " ".join(label.split())
    groups = {
        "date incident": ("incident date", "date incident", "when it happened", "transaction date"),
        "reported loss": ("reported loss", "amount lost", "transaction amount", "amount debited"),
        "transaction reference": ("transaction id", "transaction reference", "utr", "utr number", "upi reference"),
        "case location": ("city or state", "city", "state", "place incident", "location incident"),
        "incident description": ("what happened", "what you reported", "incident description", "description incident"),
        "phone": ("mobile", "mobile number", "phone", "phone number", "contact number"),
        "name": ("name", "full name", "applicant name", "complainant name"),
    }
    return next((key for key, aliases in groups.items() if label in aliases), label)


def evidence_values(attachments):
    values = []
    for attachment in attachments:
        if attachment.purpose != "evidence":
            continue
        for page, method, text in attachment.pages:
            for line in text.splitlines():
                match = FIELD_LINE.match(line)
                if match and match["value"] and FIELD_WORD.search(match["label"]) and not SENSITIVE_FIELD.search(match["label"]):
                    source = f"{attachment.name}, page {page} ({method})"
                    values.append((field_key(match["label"]), cleaned(match["value"]), source))
    return values


def evidence_excerpts(attachment, case_description):
    case_terms = set(re.findall(r"\b[a-z]{5,}\b", case_description.lower()))
    case_terms.difference_update({"about", "after", "asked", "before", "could", "there", "their", "these", "would"})
    excerpts = {}
    for page, method, text in attachment.pages:
        for line in re.split(r"\n+|(?<=[.!?])\s+", text):
            line = line.strip()
            if not 8 <= len(line) <= 320 or SENSITIVE_FIELD.search(line):
                continue
            field = FIELD_LINE.match(line)
            if field and field["value"] and FIELD_WORD.search(field["label"]):
                continue
            matching = case_terms.intersection(re.findall(r"\b[a-z]{5,}\b", line.lower()))
            score = len(matching) + 2 * bool(EVIDENCE_SIGNAL.search(line))
            if score:
                excerpts.setdefault(line, (score, f"{attachment.name}, page {page} ({method})"))
    ranked = sorted(excerpts, key=lambda line: excerpts[line][0], reverse=True)
    return [(line, excerpts[line][1]) for line in ranked[:3]]


def membership_evidence(attachments):
    findings = {}
    for attachment in attachments:
        if attachment.purpose != "evidence":
            continue
        for page, method, text in attachment.pages:
            for line in re.split(r"\n+|(?<=[.!?])\s+", text):
                line = " ".join(line.split())
                if not 8 <= len(line) <= 320 or SENSITIVE_FIELD.search(line) or line.endswith("?"):
                    continue
                if MEMBERSHIP_ACTIVE.search(line):
                    status = "active"
                elif MEMBERSHIP_UNCERTAIN.search(line):
                    continue
                elif MEMBERSHIP_ENDED.search(line):
                    status = "ended"
                elif MEMBERSHIP_SCHEDULED.search(line):
                    status = "scheduled"
                elif CANCELLATION_RECEIPT.search(line) and (
                    re.search(r"\bcancel\w*\b", line, re.I)
                    or (re.fullmatch(r"(?:status:\s*)?request received[.!]?", line, re.I)
                        and re.search(r"\bcancellation request\b", text, re.I))
                ):
                    status = "received"
                else:
                    continue
                findings.setdefault(status, (line, f"{attachment.name}, page {page} ({method})"))
    return findings


def answer_evidence_question(message, attachments):
    refers_to_document = DOCUMENT_REFERENCE.search(message)
    about_deposit = re.search(r"\b(?:deposit|landlord|landlady|security)\b", message, re.I)
    # Strict gate: an explicit "how much will they refund" deposit question.
    strict_refund = bool(
        refers_to_document and about_deposit
        and re.search(r"\b(?:how much|what amount|amount they|kitn\w*)\b", message, re.I)
        and REFUND_QUESTION.search(message)
    )
    doc_question = bool(refers_to_document and DOCUMENT_QUESTION.search(message))
    if not strict_refund and not doc_question:
        return None
    evidence = [attachment for attachment in attachments if attachment.purpose == "evidence"]
    if not evidence:
        # Only offer to read a missing deposit letter on a clear deposit question;
        # otherwise let the notice/guided flow explain what the person described.
        if not strict_refund and not re.search(r"\b(?:attach\w*|upload\w*)\b", message, re.I):
            return None
        subject = "the deposit letter" if strict_refund else "the document"
        return f"I don’t see {subject} in this chat yet. Attach it and send it with your question."
    # Evidence is present. A deposit/landlord question goes to the structured answer.
    if about_deposit and (strict_refund or doc_question or message.rstrip().endswith("?")):
        return answer_deposit_refund(evidence)
    excerpts = [excerpt for attachment in evidence for excerpt in evidence_excerpts(attachment, message)]
    if not excerpts:
        return "I couldn’t find a passage that answers your question. You can share the relevant page or paste the wording you want me to check."
    sources = "\n\n".join(f"“{quote}” ({source})" for quote, source in excerpts[:3])
    return "Here’s wording from the attached evidence that may help.\n\n" + sources


def answer_deposit_refund(attachments):
    findings = {}
    for attachment in attachments:
        for page, method, text in attachment.pages:
            for line in re.split(r"\n+|(?<!\bRs\.)(?<=[.!?])\s+", text, flags=re.I):
                line = " ".join(line.split())
                if not 8 <= len(line) <= 320 or SENSITIVE_FIELD.search(line) or line.endswith("?"):
                    continue
                for pattern in DEPOSIT_REFUND_LINES:
                    for match in pattern.finditer(line):
                        if re.search(r"\b(?:not|never|no longer)\b", line[:match.start()], re.I):
                            continue
                        tail = line[match.end("amount"):].lstrip(" ,")
                        if re.match(r"(?:less\b|minus\b|before (?:deduct|subtract)\w*|as a deduction\b)", tail, re.I):
                            continue
                        raw = match["amount"].strip()
                        value = Decimal(re.sub(r"(?i)₹|INR|Rs\.?|,|\s", "", raw))
                        shown = money(value) if not raw[0].isdigit() else raw
                        source = f"{attachment.name}, page {page} ({method})"
                        findings.setdefault(value, (shown, line, source))
    if not findings:
        return ("I couldn’t find an amount clearly stated as the deposit refund. "
                "Please share the line that says what will be returned, or a clearer copy of that page.")
    excerpts = "\n\n".join(f"“{quote}” ({source})" for _, quote, source in list(findings.values())[:3])
    if len(findings) > 1:
        return "I found different amounts stated as the refund. Which of these lines is from the landlord’s latest letter?\n\n" + excerpts
    amount, quote, _ = next(iter(findings.values()))
    conditional = re.search(r"\b(?:if|unless|subject to|provided that|assuming|estimated|may)\b", quote, re.I)
    summary = (f"The document mentions a possible deposit refund of {amount}. Check the condition in its wording."
               if conditional else f"The attached wording puts the deposit refund at {amount}.")
    return f"{summary}\n\n{excerpts}"


def reported_fields(message):
    return {label: cleaned(match["value"]) for label, pattern in CHAT_FIELDS.items()
            if (match := pattern.search(message))}


def form_help(form, facts, attachments):
    if not form.fields:
        return (
            f"I attached {form.name}, but couldn’t reliably identify its fields. "
            "Paste a field label or upload a clearer copy and I’ll check what facts you already have for it."
        )
    available = evidence_values(attachments)
    for label, value in facts.items():
        if not isinstance(value, str) or SENSITIVE_FIELD.search(label):
            continue
        key = field_key(label)
        if key == "date incident" and not re.search(r"\d", value):
            continue
        available.append((key, value, "what you reported in chat"))
    lines = [f"Fields I found in {form.name}. Review the original and choose what to enter."]
    for label, location in form.fields:
        key = field_key(label)
        values = {(value, source) for kind, value, source in available if kind == key}
        if SENSITIVE_FIELD.search(label):
            detail = "Enter this yourself if required by the official form."
        elif not values:
            detail = "No matching detail yet."
        elif len({comparison_value(key, value) for value, _ in values}) == 1:
            value = sorted(values)[0][0]
            sources = "; ".join(sorted({source for _, source in values}))
            detail = f"{value} (from {sources}). Check it before using it."
        else:
            entries = "; ".join(f"{value} (from {source})" for value, source in sorted(values))
            detail = f"Different values found. Check the correct one: {entries}."
        lines.append(f"{label} ({location}) — {detail}")
    return "\n\n".join(lines)


def comparison_value(key, value):
    if key == "reported loss":
        try:
            return Decimal(re.sub(r"(?i)(?:₹|INR|Rs\.?|,|\s)", "", value))
        except InvalidOperation:
            pass
    return value.strip()


def make_pdf(title, text):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#1d2926")
    styles["Normal"].leading = 15
    document = SimpleDocTemplate(buffer, pagesize=A4, title=title, leftMargin=42, rightMargin=42)

    def display(value):
        return escape(value.replace("₹", "INR ").replace("—", "-").replace("–", "-"))

    story = [Paragraph(display(title), styles["Title"]),
             Paragraph("Draft for your review", styles["Italic"]), Spacer(1, 12)]
    for line in text.splitlines():
        if line.strip():
            story.append(Paragraph(display(line), styles["Normal"]))
        else:
            story.append(Spacer(1, 8))
    document.build(story)
    filename = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "case-draft"
    return Attachment(filename + ".pdf", "application/pdf", buffer.getvalue(), "draft")
