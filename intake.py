"""General legal intake and routing for one case per local chat."""

from dataclasses import dataclass, field
import re

from casework import CaseFile, DATE, DISPUTE, LEGAL_CONTEXT, MONTH, SOURCE, WORK, money, verified_quote
from case_documents import (
    CANCELLATION_RECEIPT, MAX_UPLOADS, add_attachment, answer_evidence_question, evidence_excerpts, evidence_values,
    form_help, make_pdf, membership_evidence, reported_fields,
)
from draft_context import (
    DraftContext, MEMBERSHIP, OUTGOING_NOTICE, PDF_REQUEST, REPAIR_DEDUCTION, REPAIR_REFUND,
    REPLY_REQUEST, case_kind, strip_legal_claims,
)
from fraud import FraudCase, OPTIONS as FRAUD_OPTIONS, is_financial_fraud
from guided import CASE_PDF, action_prompt, draft_for, ordered_actions

WELCOME = (
    "Tell me what happened and what you need help with. It could be a rental, work, purchase, "
    "family, or other legal issue in India. Leave out names, exact addresses, and personal IDs."
)
LEGAL_AID = {
    "label": "National Legal Services Authority · Legal aid",
    "url": "https://nalsa.gov.in/legal-aid/",
}
EMERGENCY = {
    "label": "Government of India · Emergency Response Support System",
    "url": "https://112.gov.in/",
}
LEGAL_AID_REPLY = (
    "If your issue is in India, the National Legal Services Authority explains who can apply for "
    "free legal aid and how to apply. A lawyer can review how the law applies to your situation."
)
DANGER = re.compile(
    r"\b(?:in immediate danger|in danger right now|attacking (?:me|us) (?:right )?now|"
    r"threatening to (?:kill|hurt|attack) (?:me|us)|(?:has|holding) a (?:knife|gun)|"
    r"being attacked|breaking (?:in|into my home) (?:right )?now)\b", re.I,
)
DESIGN_PAYMENT = re.compile(
    r"\b(?:freelanc\w*|pay\w*|paid|fee|agreed|due|owe[ds]?|invoice)\b|₹", re.I,
)
NOTICE = re.compile(r"\b(?:notice|summons|hearing|court date|order to vacate)\b", re.I)
WHEN = rf"(?:{DATE}|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|within \d+ (?:days?|weeks?))"
DEADLINE = re.compile(
    rf"\b(?:respond|reply|appear|attend|leave|vacate|deadline|hearing|court date)"
    rf"\b[^.!?]{{0,25}}?\s+(?:(?:by|on|is)\s+)?(?P<date>{WHEN})\b", re.I,
)
DEADLINE_ANSWER = re.compile(rf"(?:it says )?(?:by |on )?(?P<date>{WHEN})[.!]?", re.I)
TIMELINE = re.compile(
    rf"\b(?:{WHEN}|(?:for|over) (?:\d+|one|two|three|four|five|six|several|a few) "
    rf"(?:days?|weeks?|months?|years?)|since (?:{MONTH}))\b", re.I,
)
RECORD = re.compile(
    r"\b(?:eviction notice|legal notice|court order|notice|summons|lease|rental agreement|"
    r"rent receipt|email|messages?|WhatsApp|pay\s?slips?|offer letter|termination letter|invoice|"
    r"receipts?|order confirmation|screenshots?|FIR|police report|contract)\b", re.I,
)
NO_RECORD = re.compile(r"\b(?:no documents?|no proof|nothing in writing|don['’]?t have any (?:records?|documents?))\b", re.I)
# Generic communication nouns that are usually the OBJECT of a draft request
# ("write a message", "send an email") rather than proof the person already holds.
GENERIC_COMMS = {"message", "messages", "msg", "text", "reply", "email"}
NO_DEADLINE = re.compile(r"\b(?:no (?:date|deadline)|doesn['’]?t (?:give|list|mention|show) (?:a|any) (?:date|deadline))\b", re.I)
PLACE = re.compile(
    r"\b(?:in|from) (?P<place>[A-Z][a-z]+(?: [A-Z][a-z]+){0,2})(?=[,.!?]|\s+[a-z]|$)"
)
GOAL = re.compile(
    r"\b(?:I want|I need help to|I’m trying to|I'm trying to)\b[^.!?]{2,115}"
    r"|\bmujhe\b[^.!?]{0,90}\b(?:hatwa?na|hatana|hatawana|remove karwana)\b[^.!?]{0,15}",
    re.I,
)
PERSONAL_PHOTO = re.compile(
    r"\b(?:(?:my|meri|mera|mere) (?:photo|picture|image|face)|(?:photo|picture|image) of me)\b", re.I,
)
AD = re.compile(r"\b(?:ads?|advert(?:isement)?s?|sponsored (?:post|video)|promotion)\b", re.I)
REMOVAL = re.compile(
    r"\b(?:remov\w*|tak(?:e|en)\b[^.!?]{0,45}\bdown|hatwa?na|hatana|hatawana)\b", re.I,
)
KEEP_PHOTO = re.compile(r"\b(?:don['’]?t|do not|no need to)\b[^.!?]{0,45}\b(?:remov\w*|take\b[^.!?]{0,30}\bdown)\b", re.I)
HINGLISH = re.compile(r"\b(?:mujhe|meri|maine|kya bolun|hatwana)\b", re.I)
FOLLOW_UP_PATTERNS = {
    "no_reply": re.compile(
        r"\b(?:no (?:reply|response)|"
        r"(?:don['’]?t|doesn['’]?t|didn['’]?t|won['’]?t|haven['’]?t|hasn['’]?t|never)"
        r"\s+(?:reply|replied|respond|responded|get back|got back)|"
        r"ignor(?:e|es|ed|ing) (?:my|the|it|me)|"
        r"(?:reply|respond|jawab)(?: back)? (?:na|nahi|nahin) (?:ka?re(?:in)?|de(?:in)?))\b",
        re.I,
    ),
    "report": re.compile(r"\b(?:report (?:it|this|the ad)|report kaise)\b", re.I),
    "shorten": re.compile(r"\b(?:shorter|shorten|make it short|chhota kar)\b", re.I),
    "permission": re.compile(r"\b(?:said|says|bole|bola)\b[^.!?]{0,60}\bpermission\b", re.I),
}
ACKNOWLEDGMENT = re.compile(r"(?:thanks|thank you|okay|ok|theek hai)[.! ]*", re.I)
REPEAT_REQUEST = re.compile(r"\b(?:repeat|show (?:me )?the (?:reply|message|draft) again)\b", re.I)
DRAFT_REVISION = re.compile(
    r"\b(?:wait|actually|correction|correct|it was|amount was|returned|paid back|repaid|"
    r"shorter|longer|friendly|friendlier|formal|casual|normal|polite|softer|firmer|"
    r"change|rewrite|revise|edit|instead|add|remove|leave out|include|mention)\b",
    re.I,
)
FOLLOW_UP_SENT = re.compile(r"\b(?:already (?:sent|followed up)|followed up (?:once|twice)|follow-up bhej diya)\b", re.I)
UNVERIFIED_REQUEST = re.compile(r"\b(?:guarantee\w*|which section|cite (?:a |the )?(?:law|section)|what law)\b", re.I)
# A person pushing back on a legal citation we declined to confirm ("are you sure
# there's no such section?", "but the reel had a lawyer", "10x penalty").
INSIST_UNVERIFIED = re.compile(
    r"\b(?:(?:such|that|this|any|the)\s+section|section\s+\d|which section|cite\b|"
    r"(?:reel|video|lawyer|post|influencer|instagram|insta|youtube|news)\s+"
    r"(?:said|says|told|had|claim\w*|mentioned)|\d+\s*x\b|penalty)\b", re.I,
)
MESSAGE_REQUEST = re.compile(
    r"\b(?:draft|write|compose|make|create|prepare|give me|send me)\b[^.!?]{0,100}"
    r"\b(?:message|msg|text|email|reply|note|letter|refund request|payment request|pay inquiry)\b"
    r"|\bwrite something (?:I can|to) send\b"
    r"|\b(?:help me|how (?:do|should|can) i) (?:reply|respond)\b", re.I,
)
DOCUMENT_CHECK = re.compile(r"\b(?:what should i check before i sign|asked (?:me )?to sign|told me to sign|before (?:i|you) sign)\b", re.I)
PAPER_REQUEST = re.compile(r"\bwhat (?:papers|documents) should i (?:ask|request|see)\b", re.I)
PROPERTY_TRANSFER = re.compile(r"\b(?:property records|transferred to|no objection|inheritance)\b", re.I)
NOTICE_EXPLANATION = re.compile(r"\b(?:explain|understand|what does .{0,60} mean)\b", re.I)
NOTICE_REQUEST = re.compile(
    r"(?:\b(?:the notice|it) (?:says I (?:must|have to|need to)|(?:asks|requires) me to)"
    r"|^(?:please|you must|you are (?:required|asked) to)) "
    r"(?P<request>(?:leave|vacate|respond|reply|appear|attend|pay)\b[^.!?]{0,120})",
    re.I,
)
FORMAL_REQUEST = re.compile(
    r"\b(?:draft|write|prepare)\b[^.!?]{0,65}\b(?:legal notice|court filing|court reply|formal reply)\b",
    re.I,
)
GUIDED_REQUEST = re.compile(
    r"(?:^|\b(?:please|can you|help me)\s+)\s*(?:draft|write|prepare|download)\b"
    r"[^.!?]{0,35}\b(?P<document>legal notice|complaint|application|case file)\b", re.I,
)
MEMBERSHIP_QUESTION = re.compile(
    r"\b(?:actually ended|has (?:it|my membership) ended|did (?:it|my membership) end|"
    r"(?:membership|subscription) (?:actually |still )?(?:end(?:ed)?|active|cancelled|canceled)|"
    r"still active|band (?:ho gay[ai]|hui|hai)|what does (?:this|the) (?:email|mail) mean)\b", re.I,
)
FORM_REVIEW = re.compile(r"\b(?:fill (?:this|it|(?:in |out )?the form)|fill (?:in|out)|what (?:fields|can i fill|should i fill)|which fields)\b", re.I)
TOPICS = {
    "photo_ad": ("Personal photo used in an ad", None),
    "housing": ("Housing or tenancy", r"landlord|tenant|rent|evict\w*|lease|security deposit"),
    "work": ("Employment or pay", r"employer|employee|employment|boss|manager|payroll|salary|wages|"
             r"unpaid|job|offer letter|fired|dismissed|termination letter|workplace"),
    "consumer": ("Purchase or refund", r"refund|purchase|bought|ordered|order confirmation|seller|shop|"
                 r"shopkeeper|merchant|delivery|warranty|replacement|defective|faulty product"),
    "loan": ("Personal loan or repayment", None),
    "family": ("Family matter", r"divorce|custody|spouse|child support|inheritance|maintenance"),
    "police": ("Police or safety", r"police|arrest\w*|fir|stalking|threaten\w*|assault\w*"),
    "other": ("Other legal issue", None),
}
LABELS = {
    "place": "City or state", "timeline": "When it happened", "deadline": "Reported response date",
    "record": "Reported documents or evidence", "goal": "What you want to happen",
    "notice_request": "What the notice asks for",
}
QUESTIONS = {
    "deadline": "Does the notice give a date to respond, attend, or leave? If so, what does it say?",
    "record": "What messages, documents, or other proof do you have?",
    "goal": "What would you like to happen next?",
}
RECORD_QUESTIONS = {
    "housing": "Do you have a rental agreement, notice, or messages from the landlord?",
    "work": "What records do you have, such as a payslip, contract, or message from your employer?",
    "consumer": "Do you have an order confirmation, receipt, or a message from the seller?",
    "family": "Is there a notice, agreement, or court document related to this?",
    "police": "Have you received a written notice or a copy of a police report?",
}
GREETING = re.compile(r"(?:hi|hello|hey|good (?:morning|evening)|i need legal help|help)[.! ]*", re.I)
OPTIONS_REQUEST = re.compile(
    r"\b(?:what (?:are my options|(?:can|could|should) i do(?: next| now)?)|"
    r"show (?:me )?(?:(?:my|the) )?options|kya options(?: hain)?|kya kar sakte hain)\b",
    re.I,
)
ADD_EVIDENCE_REQUEST = re.compile(
    r"\b(?:add|attach|include|save)\b[^.!?]{0,65}\b(?:case|file|proof|evidence|document)\b"
    r"|\b(?:case|file|proof|evidence|document)\b[^.!?]{0,65}\b(?:add|attach|include|save)\b",
    re.I,
)
EVIDENCE_QUESTION = re.compile(
    r"\?|\b(?:what|why|how|when|where|can you|could you|should i|do i|"
    r"kya|kaise|kitna|kitni|kab|ab kya|batao|bata do|samjhao)\b",
    re.I,
)
VAGUE_OPENER = re.compile(r"(?:(?:i have|i need help with) (?:a )?(?:legal )?(?:problem|issue)|what should i do)[.!? ]*", re.I)

MESSAGE_DRAFTS = {
    "housing": (
        "Message to landlord",
        "Hello, I’m following up on my security deposit for [address or tenancy reference]. "
        "Please confirm how much you intend to return and when. If you plan to deduct anything, "
        "please send an itemized breakdown and copies of the bills or other records you are relying on. Thank you.",
    ),
    "consumer": (
        "Refund request",
        "Hello, I’m writing about [item or order reference]. [Briefly describe what went wrong]. "
        "I’d like a refund. Please confirm how I can request it and when I can expect a response. Thank you.",
    ),
    "work": (
        "Pay inquiry",
        "Hello, I’m writing about my pay for [pay period]. [Briefly describe what is missing]. "
        "Could you confirm the status of the payment and when I can expect an update? Thank you.",
    ),
    "notice": (
        "Request to clarify a notice",
        "Hello, I received your notice dated [date on the notice]. Could you clarify "
        "[the part you’re unsure about] and confirm the date you are asking me to respond by? Thank you.",
    ),
}

NO_REPLY_STEPS = {
    "consumer": (
        "Send a short written follow-up with the order reference, your original request date, "
        "and the outcome you’re asking for. If you bought through a marketplace, check whether "
        "its order page offers a support or dispute option."
    ),
    "work": (
        "Forward your earlier message to payroll or HR with the pay period and amount you believe "
        "is missing. Ask who is handling it and when you can expect an update. Save the sent messages."
    ),
}


def topic_for(message, suggested):
    kind = case_kind(message)
    if kind:
        return {"deposit": "housing", "membership": "consumer", "repair": "consumer", "loan": "loan"}[kind]
    if PERSONAL_PHOTO.search(message) and AD.search(message):
        return "photo_ad"
    for topic, (_, pattern) in TOPICS.items():
        if pattern and re.search(rf"\b(?:{pattern})\b", message, re.I):
            return topic
    # The small model labels almost everything "consumer", so only trust its
    # suggestion for a specific topic it rarely over-predicts; otherwise treat the
    # issue as "other" and handle it generically rather than forcing a refund flow.
    trusted = {"housing", "work", "family", "police"}
    return suggested if isinstance(suggested, str) and suggested in trusted else "other"


@dataclass
class GeneralIntake:
    topic: str = "other"
    facts: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    asked: set = field(default_factory=set)
    waiting_for: str = ""
    has_notice: bool = False
    wants_message: bool = False

    def respond(self, message, extracted, *, collect_only=False):
        self.reports.append(message)
        proposed_events = extracted.get("events")
        if isinstance(proposed_events, list):
            for event in proposed_events[:4]:
                quote = verified_quote(event, message, 280)
                if quote and quote not in self.events:
                    self.events.append(quote)
        if self.topic == "other":
            self.topic = topic_for(message, extracted.get("topic"))
        outgoing_notice = bool(OUTGOING_NOTICE.search(message))
        self.has_notice = self.has_notice or bool(NOTICE.search(message) and not outgoing_notice)
        self.wants_message = self.wants_message or bool(MESSAGE_REQUEST.search(message))

        deadline = DEADLINE.search(message)
        if deadline is None and self.waiting_for == "deadline":
            deadline = DEADLINE_ANSWER.fullmatch(message)
        location = PLACE.search(message)
        date = TIMELINE.search(message[:deadline.start()] if deadline else message)
        records = dict.fromkeys(match[0] for match in RECORD.finditer(message))
        drafting_this_turn = bool(MESSAGE_REQUEST.search(message))
        if drafting_this_turn:
            # Don't log the draft request's own noun ("write a message") as the
            # person's evidence; it would overwrite proof they already reported.
            records = {name: value for name, value in records.items()
                       if name.lower() not in GENERIC_COMMS}
        if outgoing_notice and not self.has_notice:
            records = {name: None for name in records if not NOTICE.search(name)}
        goal = GOAL.search(message)
        notice_request = NOTICE_REQUEST.search(message) if self.has_notice else None
        if notice_request:
            self.facts["notice_request"] = notice_request["request"]
        candidates = {
            "place": location["place"] if location else None,
            "timeline": date[0] if date else None,
            "deadline": deadline["date"] if deadline else None,
            "record": ", ".join(records) if records else None,
            "goal": goal[0] if goal else None,
        }
        if self.has_notice and NO_DEADLINE.search(message):
            candidates["deadline"] = "No date reported on the notice"
        if NO_RECORD.search(message):
            candidates["record"] = "No record reported"
        for key, candidate in candidates.items():
            value = candidate or verified_quote(extracted.get(key), message, 150)
            if key == "record" and not candidate and drafting_this_turn:
                # On a pure draft request, keep the evidence already reported
                # instead of letting the model re-extract the request's own noun.
                continue
            if key == "record" and value and not candidate and outgoing_notice and not self.has_notice and NOTICE.search(value):
                continue
            if key == "place" and value and value.lower() in ("india", "bharat"):
                continue
            # The small model often returns an object noun ("gate", "car") as a place.
            # Accept a model-suggested place only if it follows a locational preposition.
            if key == "place" and value and not candidate and not re.search(
                rf"\b(?:in|at|from|near)\s+{re.escape(value)}\b", message, re.I
            ):
                continue
            # Reject a vague one-word goal the model guessed ("options", "help").
            if key == "goal" and value and not candidate and value.strip().lower() in (
                "options", "help", "money", "it", "that", "this", "something",
                "anything", "advice", "the money", "my money",
            ):
                continue
            if key in ("deadline", "timeline") and value and value != candidates[key]:
                if not re.search(rf"\b(?:{WHEN})\b", value, re.I):
                    continue
                if key == "deadline" and not self.has_notice:
                    continue
            if value:
                self.facts[key] = value

        new_request = bool(MESSAGE_REQUEST.search(message) or GUIDED_REQUEST.search(message)
                            or OUTGOING_NOTICE.search(message))
        if self.waiting_for and not message.endswith("?") and not new_request:
            if self.waiting_for == "deadline" and re.fullmatch(r"(?:no|none|no date)[.!]?", message, re.I):
                self.facts.setdefault("deadline", "No date reported on the notice")
            elif self.waiting_for in ("record", "goal") and len(message) <= 100:
                self.facts.setdefault(self.waiting_for, message)

        self.waiting_for = ""
        if collect_only:
            return {"reply": ""}
        if UNVERIFIED_REQUEST.search(message):
            return {"reply": (
                "The details you’ve shared can help identify what needs checking. I can’t verify the legal rule "
                "or whether it applies from the sources available here. A lawyer can check the original documents "
                "and any deadline. Use the legal aid link below if you need help finding one."
            )}
        if FORMAL_REQUEST.search(message):
            self.wants_message = False
            return {"reply": "Ask a lawyer to review the requirements and timing for a formal legal notice or filing. I can help you prepare the facts or draft a short message asking for clarification."}
        intent = next((name for name, pattern in FOLLOW_UP_PATTERNS.items() if pattern.search(message)), None)
        suggested = extracted.get("intent")
        if intent is None and len(self.reports) > 1 and isinstance(suggested, str) and suggested in FOLLOW_UP_PATTERNS:
            intent = suggested
        if self.topic == "photo_ad":
            return {"reply": self.photo_ad_reply(intent)}
        if PAPER_REQUEST.search(message) and PROPERTY_TRANSFER.search(message):
            return {"reply": (
                "Ask for a complete copy of what they want you to sign, including any pages or attachments "
                "referred to. Ask for a copy of the will they mentioned and the papers that explain the "
                "proposed transfer. If the wording says you have no objection, ask a property lawyer to review "
                "the full document before deciding whether to sign. You can attach the page for help reading it."
            )}
        if DOCUMENT_CHECK.search(message):
            return {"reply": (
                "Compare what the document says you received, agreed to, or are giving up with your own records. "
                "If a statement is wrong or unclear, ask for a corrected copy or a written explanation. "
                "If you’re unsure what signing would do, ask a lawyer to review the full document. "
                "You can attach it and point to the line that concerns you."
            )}
        if self.has_notice and "deadline" not in self.facts and "deadline" not in self.asked:
            return self.ask("deadline")
        if intent == "no_reply" and self.has_notice:
            return {"reply": "Keep a copy of what you sent. If the notice gives a response date, speak to a lawyer about what to do by that date while you wait for a reply."}
        if intent == "no_reply" and self.topic in NO_REPLY_STEPS:
            return {"reply": NO_REPLY_STEPS[self.topic]}
        if self.wants_message:
            self.wants_message = False
            kind = "notice" if self.has_notice else self.topic
            if kind in MESSAGE_DRAFTS and (kind != "housing" or re.search(r"\bdeposit\b", " ".join(self.reports), re.I)):
                title, draft = MESSAGE_DRAFTS[kind]
                reply = "Here’s a short draft. Fill in the brackets and check the details before sending."
                if kind == "notice":
                    reply += " If the notice sets a deadline or comes from a court, have a lawyer review it promptly."
                return {"reply": reply, "draft": draft, "draft_title": title}
            return {"reply": "Who are you trying to write to, and what do you want them to do? For a formal filing, ask a lawyer to review it."}
        if self.has_notice:
            if "notice_request" in self.facts and (notice_request or NOTICE_EXPLANATION.search(message)):
                return {"reply": (
                    f"The wording you shared asks you to {self.facts['notice_request']}. "
                    "A lawyer can help check what effect the notice has and whether the stated deadline applies."
                )}
            return {"reply": (
                "Keep a copy of the notice and any date it gives. A lawyer can help you check "
                "whether you need to act soon. If you want help reading it, paste the part that says "
                "what you’re being asked to do, with personal details removed."
            )}
        if self.topic == "consumer":
            return {"reply": (
                "If you want the seller to reconsider, you can put the problem and the outcome "
                "you want in writing. Include the order reference or receipt if you have it. "
                "You can ask me to draft a refund request."
            )}
        if self.topic == "work" and re.search(
            r"\b(?:pay|paid|paycheck|payroll|payment|salary|wages|unpaid)\b", " ".join(self.reports), re.I
        ):
            return {"reply": (
                "If you’re trying to get missing pay, ask your employer to confirm the amount and "
                "when it will be paid. Keep any payslip or messages about it. You can ask me to draft a pay inquiry."
            )}
        if "goal" not in self.facts and "goal" not in self.asked:
            return self.ask("goal")
        if "record" not in self.facts and "record" not in self.asked:
            return self.ask("record")
        return {"reply": "Use Legal resources to find help in India. A lawyer can review your options based on the facts you’ve shared."}

    def photo_ad_reply(self, intent):
        self.wants_message = False
        story = " ".join(self.reports)
        hinglish = HINGLISH.search(story)
        if intent == "no_reply":
            previous_no_reply = len(self.reports) > 1 and FOLLOW_UP_PATTERNS["no_reply"].search(self.reports[-2])
            if previous_no_reply or FOLLOW_UP_SENT.search(self.reports[-1]):
                if hinglish:
                    return "Agar follow-up ke baad bhi ad live hai, aur report ka option dikh raha hai, toh ad report karo. Ad ka link, screenshots aur DMs sambhal ke rakho. Agar report submit ho jaaye, uska confirmation bhi save karo."
                return "If you’ve already followed up and the ad is still live, use the platform’s report option if available. Keep the ad link, screenshots, messages, and any confirmation you receive."
            if hinglish:
                return (
                    "Agar reply na aaye aur ad abhi bhi live ho, ek short follow-up bhejo. "
                    "Pehle DM ki date aur ad ka link add kar do.\n\n"
                    "“Hi, mere [date] ke message par ek follow-up. "
                    "Please meri photo is ad [link] se hata dijiye aur confirm kar dijiye.”\n\n"
                    "Agar phir bhi jawab na aaye, ad par report ka option ho toh use karo. "
                    "Ad ka link, screenshot aur DMs sambhal kar rakho."
                )
            return (
                "If they don’t reply and the ad is still up, send one short follow-up with the date "
                "of your first message and the ad link. Ask them to confirm when the photo is removed. "
                "If it stays up, use the platform’s report option if it has one. Keep screenshots of the ad and your messages."
            )
        if intent == "report":
            if hinglish:
                return "Ad par report ka option dekho. Report mein likho ki ad mein aapki photo hai aur aapko is use par kyun objection hai. Ad ka link aur report confirmation ka screenshot save kar lo."
            return (
                "Open the ad and look for a report option. Explain that it shows your photo and describe "
                "why you’re objecting to this use. Save the ad link and a screenshot of any report confirmation."
            )
        if intent == "shorten":
            if not REMOVAL.search(story):
                return "“Could you please share what permission you’re relying on for this specific ad?”"
            if hinglish:
                return "“Please meri photo is ad se hata dijiye. Agar aap permission ka zikr kar rahe hain, toh share kijiye ki woh is ad ke liye kya allow karti hai.”"
            return "“Please remove my photo from this ad. If you’re relying on permission, please show what it covers for this ad.”"
        if intent == "permission" and len(self.reports) > 1:
            if hinglish:
                return "Unse permission ki copy maango aur pucho ki woh fest page ke liye thi ya isi paid ad ke liye. Agar woh copy share karte hain, toh usmein allowed use dekh sakte ho."
            return "Ask for a copy of the permission and check whether it mentions this particular paid ad. Save what they send so you can refer to the exact wording."
        if KEEP_PHOTO.search(self.reports[-1]) or not REMOVAL.search(story):
            return (
                "Ask the advertiser what permission it relied on for this specific ad. "
                "If you want the photo removed, you can ask for that in the same message. "
                "Save a screenshot of the ad and their reply."
            )
        if hinglish:
            permission = "college ki permission" if re.search(r"\bcollege\b", story, re.I) else "kisi aur ki permission"
            context = "Mujhe bataya gaya tha ki photo fest page par jayegi. " if re.search(r"\bfest page\b", story, re.I) else ""
            return (
                "Aap unko yeh reply bhej sakte ho.\n\n"
                f"“{context}Please meri photo is ad se hata dijiye. Agar aap {permission} ki baat kar rahe hain, "
                "toh please share kijiye ki usmein is paid ad ke liye kya allow kiya gaya tha. "
                "Photo hataane ke baad please confirm kar dijiye.”\n\n"
                "Ad ka screenshot aur unke DMs save kar lo."
            )
        return (
            "You can reply in writing.\n\n"
            "“Please remove my photo from this ad and confirm once it’s down. If you’re relying on someone’s "
            "permission to use it, please share what that permission says about this specific ad.”\n\n"
            "Save a screenshot of the ad and the replies."
        )

    def ask(self, key):
        self.asked.add(key)
        self.waiting_for = key
        question = RECORD_QUESTIONS.get(self.topic, QUESTIONS[key]) if key == "record" else QUESTIONS[key]
        return {"reply": question}

    def view(self):
        facts = {"Issue": TOPICS[self.topic][0]} if self.reports else {}
        if self.events:
            facts["Reported events"] = "\n".join(f"• {event}" for event in self.events)
        if self.reports:
            facts["What you reported"] = self.reports[0]
        facts.update({LABELS[key]: value for key, value in self.facts.items()})
        return {"facts": facts, "records": {}}

    def draft(self):
        if not self.reports:
            return None, "Describe what happened first. I can then prepare a case summary."
        details = self.view()["facts"]
        summary = ["Case summary for legal review", "", f"Issue: {details['Issue']}", "", "What I reported"]
        summary.extend(f"- {report}" for report in self.reports)
        for key in LABELS.values():
            if key in details:
                summary.append(f"{key}: {details[key]}")
        summary.append("\nQuestions for a lawyer\nWhat options do I have, and is there a deadline I should know about?")
        return "\n".join(summary), "Review the summary below and correct anything before sharing it."


@dataclass
class Conversation:
    intake: GeneralIntake = field(default_factory=GeneralIntake)
    payment: CaseFile | None = None
    fraud: FraudCase | None = None
    recent_turns: list = field(default_factory=list)
    uploads: list = field(default_factory=list)
    downloads: dict = field(default_factory=dict)
    pending_action: str = ""
    offered_actions: set = field(default_factory=set)
    form_facts: dict = field(default_factory=dict)
    draft_context: DraftContext = field(default_factory=DraftContext)
    awaiting_membership_evidence: bool = False

    def respond(self, message, model, *, attachment=None):
        if DANGER.search(message):
            return {
                "reply": "If you are in immediate danger in India, call 112 now if it is safe to do so.",
                "source": EMERGENCY,
            }
        outgoing_notice = bool(OUTGOING_NOTICE.search(message))
        reply_request = bool(REPLY_REQUEST.search(message))
        safe, omitted_claim = strip_legal_claims(message)
        message = safe
        options_request = OPTIONS_REQUEST.search(message)
        evidence_only = bool(
            attachment is not None and attachment.purpose == "evidence"
            and not EVIDENCE_QUESTION.search(message)
            and not (outgoing_notice or reply_request or GUIDED_REQUEST.search(message) or options_request)
        )
        has_issue = self.payment is not None or self.fraud is not None or bool(self.intake.reports)
        if GREETING.fullmatch(message) or (not has_issue and (
            ACKNOWLEDGMENT.fullmatch(message) or VAGUE_OPENER.fullmatch(message)
            or OPTIONS_REQUEST.fullmatch(message.rstrip("?.! "))
        )):
            return {"reply": WELCOME}
        if has_issue and ACKNOWLEDGMENT.fullmatch(message):
            return {"reply": "You’re welcome."}
        if has_issue and OPTIONS_REQUEST.fullmatch(message.rstrip("?.! ")):
            self.pending_action = ""
            return {"reply": "Here are a few options for what you described.", "choices": self.offer_actions()}
        if not message:
            return {"reply": "I can’t verify that legal claim. I’ll leave it out. Tell me what happened and what you need help preparing."}
        self.form_facts.update(reported_fields(message))
        if self.fraud is None and is_financial_fraud(message):
            self.fraud = FraudCase()
            self.pending_action = ""
            self.offered_actions.clear()
        if self.fraud is not None:
            response = self.fraud.respond(message)
            if attachment is not None and attachment.purpose == "evidence" and (ADD_EVIDENCE_REQUEST.search(message) or evidence_only):
                self.draft_context.update(message, {})
                response = self.describe_upload(attachment)
                self.recent_turns.append({"user": message[:1200], "assistant": response["reply"]})
                self.recent_turns = self.recent_turns[-6:]
                return response
            if self.pending_action:
                return self.finish_action(message)
            if not has_issue or not self.offered_actions or options_request:
                response["choices"] = self.offer_actions()
                if not has_issue or not self.fraud.records:
                    response["reply"] += "\n\nYou can name any other proof you have or attach it."
            else:
                response.pop("choices", None)
            return response
        membership_question = bool(
            not outgoing_notice and not reply_request and MEMBERSHIP_QUESTION.search(message)
            and (self.draft_context.kind == "membership" or MEMBERSHIP.search(message))
        )
        repair_followup = bool(
            self.draft_context.kind == "repair" and self.draft_context.last_action == "reply"
            and (REPAIR_DEDUCTION.search(message) or REPAIR_REFUND.search(message))
        )
        form_review = None
        evidence_reply = None
        if not (membership_question or outgoing_notice or reply_request or repair_followup or GUIDED_REQUEST.search(message)):
            if self.pending_action == "application" or FORM_REVIEW.search(message):
                form_review = next(
                    (item for item in reversed(([attachment] if attachment else []) + self.uploads) if item.fields),
                    None,
                )
                if form_review is None and (attachment is not None or self.uploads):
                    form_review = attachment or self.uploads[-1]
            if form_review is None:
                evidence_reply = answer_evidence_question(message, [attachment] if attachment is not None else self.uploads)
        if self.payment is None and not self.intake.reports and WORK.search(message) and (
            DESIGN_PAYMENT.search(message) or DISPUTE.search(message)
        ) and topic_for(message, None) == "other":
            self.payment = CaseFile()
        if self.payment is not None:
            response = {"reply": self.payment.respond(message, model)}
            extracted = {}
            if response["reply"] == LEGAL_CONTEXT:
                response["source"] = SOURCE
        else:
            if membership_question or evidence_reply is not None:
                extracted = {}
            else:
                extracted = model.intake(message, tuple(self.recent_turns)) if self.recent_turns else model.intake(message)
            collect_only = bool(self.pending_action or outgoing_notice or reply_request or omitted_claim
                                or membership_question or repair_followup or form_review is not None or evidence_reply is not None)
            response = self.intake.respond(message, extracted, collect_only=collect_only)
        self.draft_context.update(message, extracted)
        if attachment is not None and attachment.purpose == "evidence" and self.draft_context.kind == "membership":
            status = membership_evidence([attachment])
            if "received" in status:
                self.draft_context.cancellation_received = True
            if "ended" in status:
                self.draft_context.cancellation_confirmed = True
        updating_draft = self.draft_context.last_action == "reply" and (
            repair_followup or PDF_REQUEST.search(message)
            or DRAFT_REVISION.search(message)
            or (self.draft_context.kind == "loan" and re.search(
                r"\d\s*k?\s+(?:nahi|nahin|wapas|likh)|wapas\s+(?:kar|de)\b|\blikh\s*(?:na|do|de|dena|dijiye)\b", message, re.I))
        )
        if (INSIST_UNVERIFIED.search(message) and not omitted_claim
                and not (reply_request or outgoing_notice or updating_draft or membership_question)
                and attachment is None and evidence_reply is None and form_review is None):
            response = {"reply": (
                "I still can’t confirm any such section or penalty from the sources I can check here, "
                "so I won’t cite it — even if a reel or an influencer attributes it to a lawyer. "
                "A practising lawyer can confirm the exact rule and any deadline. I can still help you "
                "organise the facts and draft a clear, polite message or notice about your issue."
            )}
        elif membership_question:
            response = self.answer_membership_status([attachment] if attachment is not None and attachment.purpose == "evidence" else None)
        elif form_review is not None:
            if self.pending_action == "application":
                self.pending_action = ""
            response = {"reply": form_help(form_review, self.view()["facts"], self.uploads)}
        elif evidence_reply is not None:
            response = {"reply": evidence_reply}
        elif attachment is not None and attachment.purpose == "evidence" and (ADD_EVIDENCE_REQUEST.search(message) or evidence_only):
            response = self.describe_upload(attachment)
        elif outgoing_notice or (omitted_claim and self.pending_action == "notice"):
            response = self.prepare_draft("notice", model=model)
        elif reply_request and self.intake.topic != "photo_ad":
            response = self.prepare_draft("reply", model=model)
        elif self.pending_action:
            response = self.finish_action(message, model)
        elif updating_draft:
            response = self.prepare_draft("reply", model=model)
        elif self.draft_context.last_action == "reply" and FOLLOW_UP_PATTERNS["no_reply"].search(message):
            response = {"reply": self.draft_context.no_reply_step(message)}
        else:
            request = GUIDED_REQUEST.search(message)
            if request:
                key = {"legal notice": "notice", "case file": "case_pdf"}.get(
                    request["document"].lower(), request["document"].lower()
                )
                self.offered_actions.add(key)
                response = self.choose(key)
            elif self.draft_context.kind == "deposit" and self.draft_context.hinglish:
                response = {"reply": self.draft_context.deposit_help()}
            elif self.draft_context.kind == "membership" and not self.draft_context.last_action:
                if self.draft_context.cancellation_received and not self.draft_context.cancellation_confirmed:
                    response = {"reply": "The email shows your cancellation request was received. It leaves the cancellation and membership end date unconfirmed. You can ask the accounts team to confirm the date in writing and query the charge."}
        if omitted_claim:
            warning = "I can’t verify that legal claim from the sources available here, so I’ll leave the citation and any unverified claim for extra repayment out."
            response["reply"] = f"{warning}\n\n{response['reply']}" if response["reply"] else warning
        direct = bool(outgoing_notice or reply_request or updating_draft or omitted_claim or membership_question
                      or (attachment is not None and (ADD_EVIDENCE_REQUEST.search(message) or evidence_only))
                      or form_review is not None or evidence_reply is not None)
        if not has_issue and not direct:
            view = self.view()
            if not view["records"] and not view["facts"].get("Reported documents or evidence") and not self.uploads:
                response["reply"] += "\n\nYou can name the proof you have or attach it."
        if (not has_issue or options_request) and not direct and not self.pending_action and not response.get("draft"):
            response["choices"] = self.offer_actions()
        repeated = any(response["reply"] == turn["assistant"] for turn in self.recent_turns)
        if repeated and not response.get("draft") and not response.get("choices") and not REPEAT_REQUEST.search(message):
            response["reply"] = (
                "Is there a new development, or a specific part of the previous answer you want to go into?"
            )
        self.recent_turns.append({"user": message[:1200], "assistant": response["reply"]})
        self.recent_turns = self.recent_turns[-6:]
        return response

    def offer_actions(self):
        has_form = any(item.fields for item in self.uploads)
        if self.fraud is not None:
            choices = self.fraud.options()
            if has_form:
                choices.append({"id": "application", "label": "Match my transaction details to the uploaded form"})
        else:
            story = " ".join(self.intake.reports)
            choices = ordered_actions(
                self.intake.topic, story, has_notice=self.intake.has_notice,
                payment=self.payment is not None, review_first=bool(DOCUMENT_CHECK.search(story)),
                has_form=has_form, kind=self.draft_context.kind,
            )
        self.offered_actions.update(choice["id"] for choice in choices)
        return choices

    def view(self):
        if self.fraud is not None:
            view = self.fraud.view()
        elif self.payment is not None:
            view = self.payment.view()
        else:
            view = self.intake.view()
        view["facts"] = {**view["facts"], **self.form_facts}
        context = self.draft_context
        if context.kind == "loan" and context.amount is not None:
            for label in ("What you reported", "Reported events", "When it happened"):
                view["facts"].pop(label, None)
            view["facts"]["Reported amount lent"] = money(context.amount)
            if context.loan_when:
                view["facts"]["When it happened"] = context.loan_when
            if context.repaid is not None and not context.repayment_unclear:
                view["facts"]["Reported amount repaid"] = money(context.repaid)
                if context.balance() >= 0:
                    view["facts"]["Reported outstanding balance"] = money(context.balance())
        if context.kind == "deposit" and context.amount is not None:
            view["facts"]["Reported deposit"] = money(context.amount)
            if context.moved_out:
                view["facts"]["Reported move-out date"] = context.moved_out
            if context.reason:
                view["facts"]["Reported deduction reason"] = context.reason
        if context.kind == "membership":
            view["facts"]["Cancellation status"] = (
                "User reports cancellation was confirmed" if context.cancellation_confirmed
                else "Request received; end date unconfirmed"
                if context.cancellation_received else "End date unconfirmed"
            )
        if context.recipient:
            view["facts"]["Recipient"] = context.recipient
        if context.goal:
            view["facts"]["What you want to happen"] = context.goal
        if self.uploads:
            evidence_details = []
            description = " ".join(str(value) for value in view["facts"].values())
            for upload in self.uploads:
                evidence_details.extend(
                    f"{key}: {value} ({source})"
                    for key, value, source in evidence_values([upload])[:8]
                )
                evidence_details.extend(
                    f"“{quote}” ({source})"
                    for quote, source in evidence_excerpts(upload, description)[:3]
                )
            if evidence_details:
                view["records"]["Extracted from uploaded files; check against originals"] = evidence_details
        view["attachments"] = [upload.view() for upload in self.uploads]
        return view

    def draft(self):
        if self.draft_context.kind == "loan":
            return self.case_text(), "Review these reported details before sharing the case file."
        return (self.fraud or self.payment or self.intake).draft()

    def choose(self, choice):
        if self.fraud is not None and any(option["id"] == choice for option in FRAUD_OPTIONS):
            self.pending_action = ""
            return self.fraud.choose(choice)
        if choice == "case_pdf" and (self.view()["facts"] or self.uploads):
            return {"reply": "Review these reported details before sharing the case file.",
                    "draft": self.case_text(), "draft_title": "Case file"}
        if choice not in self.offered_actions:
            return {"reply": "That option is unavailable for the current case. Review the options shown for this case."}
        self.pending_action = ""
        if choice == "lawyer":
            return {
                **self.legal_resources(),
                "choices": [CASE_PDF],
            }
        if choice in ("reply", "notice"):
            return self.prepare_draft(choice, pdf=True)
        form = next((item for item in reversed(self.uploads) if item.fields), None)
        prompt = action_prompt(choice, self.view()["facts"], form is not None)
        if not prompt and form is not None:
            return {"reply": form_help(form, self.view()["facts"], self.uploads)}
        self.pending_action = choice
        return {"reply": prompt}

    def finish_action(self, message, model=None):
        choice = self.pending_action
        if choice in ("reply", "notice"):
            return self.prepare_draft(choice, pdf=self.draft_context.request_pdf, model=model)
        self.pending_action = ""
        title, draft = draft_for(choice, self.view(), message, (upload.name for upload in self.uploads))
        return {
            "reply": "Here’s a PDF draft for your review. Check the details and fill in any brackets before sharing it.",
            "draft": draft,
            "draft_title": title,
        }

    def prepare_draft(self, choice, *, pdf=False, model=None):
        context = self.draft_context
        context.last_action = choice
        context.request_pdf = context.request_pdf or (pdf and context.kind != "loan")
        self.pending_action = choice
        if choice == "reply" and not context.goal:
            story = " ".join(self.intake.reports)
            if self.intake.topic == "work" and re.search(
                r"\b(?:unpaid|missing pay|haven['’]?t paid|not paid|owe (?:me|us)|withheld|salary|wages)\b",
                story, re.I,
            ):
                context.goal = "confirm when my outstanding pay will be paid"
            elif self.intake.topic == "consumer" and re.search(r"\brefund\b", story, re.I):
                context.goal = "review my refund request and confirm the next step in writing"
        if choice == "reply" and not context.recipient:
            # Pick up an obvious counterparty the person already named, so we don't
            # ask "who is this for?" when it is clear from the story.
            party = re.search(
                r"\b(neighbou?r|landlord|landlady|employer|boss|manager|hr|shopkeeper|"
                r"seller|builder|contractor|society|association|company|bank|friend|"
                r"colleague|tenant|agent|broker|plumber|electrician|mechanic)\b",
                " ".join(self.intake.reports), re.I,
            )
            if party:
                word = party.group(1).lower()
                context.recipient = ("the " if word in ("company", "bank", "society", "association", "hr") else "my ") + word
        if choice == "notice" and context.kind == "deposit":
            question = context.notice_missing()
            if question:
                return {"reply": "I can help draft a notice asking for your deposit back. " + question}
        if choice == "reply" and context.kind == "loan":
            if context.repayment_unclear:
                return {"reply": "How much has your friend repaid in total? I’ll use that to check what is still outstanding."}
            if context.balance() is None:
                return {"reply": "Kitne paise diye the?" if context.hinglish else "How much did you lend?"}
            if context.balance() < 0:
                return {"reply": "The repayments you gave are higher than the original amount. Could you check the two amounts before I draft the message?"}
            if context.balance() == 0:
                self.pending_action = ""
                return {"reply": "The amounts you gave add up to full repayment. If there’s another amount outstanding, tell me what it is."}
            text = context.loan_message()
            self.pending_action = ""
            if context.request_pdf:
                return {"reply": text, "draft": text, "draft_title": "Repayment message"}
            return {"reply": text}
        facts = self.view()["facts"]
        if not context.recipient or not context.goal:
            if context.recipient:
                prompt = f"What would you like {context.recipient} to do?"
            elif context.goal:
                prompt = "Who should receive the message?" if choice == "reply" else "Who should receive the notice?"
            else:
                prompt = action_prompt(choice, facts, False)
            return {"reply": prompt}
        self.pending_action = ""
        if choice == "notice" and context.kind == "deposit":
            draft = context.deposit_notice()
            return {"reply": "Here’s a draft notice for a lawyer to review.",
                    "draft": draft, "draft_title": "Draft notice for lawyer review"}
        if choice == "reply" and context.kind == "membership":
            draft = context.membership_message()
            if context.request_pdf:
                return {"reply": draft, "draft": draft, "draft_title": "Draft reply"}
            return {"reply": draft}
        if choice == "reply" and context.kind == "repair":
            draft = context.repair_message()
            if context.request_pdf:
                return {"reply": draft, "draft": draft, "draft_title": "Draft reply"}
            return {"reply": draft}
        title, draft = draft_for(
            choice, self.view(), evidence=(upload.name for upload in self.uploads),
            recipient=context.recipient, goal=context.goal,
        )
        if choice == "reply" and not context.request_pdf:
            draft = context.compose_message(facts, self.recent_turns, model)
            return {"reply": draft}
        return {"reply": "Here’s the PDF draft for your review.", "draft": draft, "draft_title": title}

    def case_text(self):
        view = self.view()
        lines = [f"{label}: {value}" for label, value in view["facts"].items()]
        for label, records in view["records"].items():
            lines.append(f"{label}: {', '.join(records)}")
        if not lines and self.uploads:
            return "No case details were entered in chat. See the attachment list below."
        return "\n".join(lines)

    def answer_membership_status(self, attachments=None):
        context = self.draft_context
        attachments = self.uploads if attachments is None else attachments
        findings = membership_evidence(attachments)
        self.awaiting_membership_evidence = not any(key in findings for key in ("ended", "scheduled", "active"))
        if not findings and not any(item.purpose == "evidence" for item in attachments):
            if context.cancellation_received:
                return {"reply": "Aapne bataya email mein ‘request received’ likha hai. Matlab gym ko request mil gayi. Membership kab band hui, yeh us line se pata nahi chalta." if context.hinglish else
                        "From the wording you shared, the gym received the request. That line leaves the membership end date unconfirmed."}
            return {"reply": "Is chat mein mujhe email abhi dikh nahi rahi. Neeche Evidence select karke Choose file se email ya screenshot lagao, phir Send dabao. Main dekh kar bataungi ki gym ne kya confirm kiya hai." if context.hinglish else
                    "I don’t see the email in this chat yet. Choose the email or a screenshot under Evidence and press Send. I’ll check what it confirms."}
        if "active" in findings and "ended" in findings:
            keys = ("active", "ended")
            hindi = "Dono records mein alag baat likhi hai. Gym se membership ki abhi ki status aur end date likh kar maango."
            english = "The records give different statuses. Ask the provider to confirm the current status and end date in writing."
        elif "ended" in findings:
            keys = ("ended",)
            hindi = "Email mein membership band hone ki confirmation hai. Agar end date alag se di hai, usse check karo ki membership kis din band hui."
            english = "The email confirms the membership was cancelled. Check the effective date in the email to see when it ended."
        elif "scheduled" in findings:
            keys = ("scheduled",)
            hindi = "Email mein likha hai ki membership kab band honi hai. Neeche di date dekho aur use charge ki date se milao."
            english = "The email gives a planned membership end date. Compare the date below with the date of the charge."
        elif "active" in findings:
            keys = ("active",)
            hindi = "Email ke mutabik, jab yeh bheji gayi tab cancellation poori nahi hui thi. Gym se abhi ki status aur end date likh kar maango."
            english = "The email indicates that cancellation had not gone through when it was sent. Ask the provider for the current status and end date in writing."
        elif "received" in findings:
            keys = ("received",)
            hindi = "Is email se bas itna pata chalta hai ki gym ko cancellation ki request mil gayi. Membership band hui ya kis din band hui, yeh confirm nahi hai. Gym se end date likh kar maango."
            english = "The email acknowledges the cancellation request. It leaves the cancellation and end date unconfirmed. Ask for the end date in writing."
        else:
            keys = ()
            hindi = "Jo file lagi hai, usme membership band hone ki saaf confirmation nahi mili. Email ka woh hissa bhej do jahan cancellation ya end date likhi ho."
            english = "I couldn’t find a clear cancellation confirmation in the attached evidence. Share the part of the email that mentions cancellation or the end date."
        lines = [hindi if context.hinglish else english]
        lines.extend(f"“{quote}” ({source})" for quote, source in (findings[key] for key in keys))
        return {"reply": "\n\n".join(lines)}

    def attach(self, name, content, purpose):
        if len(self.uploads) >= MAX_UPLOADS:
            raise ValueError(f"This case can hold up to {MAX_UPLOADS} uploaded files.")
        attachment = add_attachment(name, content, purpose)
        self.uploads.append(attachment)
        return attachment

    def upload(self, name, content, purpose):
        return self.describe_upload(self.attach(name, content, purpose))

    def describe_upload(self, attachment):
        if attachment.purpose == "form":
            if self.pending_action == "application":
                self.pending_action = ""
            return {"reply": form_help(attachment, self.view()["facts"], self.uploads)}
        if self.awaiting_membership_evidence:
            return self.answer_membership_status()
        found = [(key, value, source) for key, value, source in evidence_values([attachment])]
        facts = self.view()["facts"]
        excerpts = evidence_excerpts(attachment, " ".join(facts.get(key, "") for key in ("Issue", "What you reported")))
        if not found and not excerpts:
            readable = any(text for _, _, text in attachment.pages)
            if self.draft_context.hinglish:
                detail = ("File ka padha hua text case file mein hai. Isse payment confirm karne se pehle original se milana hoga."
                          if readable else "Is file ka text saaf nahi padh paayi. Aap bata sakte hain ki isme kya likha hai, ya clearer copy laga sakte hain.")
                return {"reply": f"Maine {attachment.name} ko case file mein Evidence ke roop mein add kar diya hai. {detail}"}
            detail = ("The case file shows the extracted text. Check it against the original before treating it as proof of payment."
                      if readable else "I couldn’t read clear text. You can tell me what the file shows or upload a clearer copy.")
            return {"reply": f"I attached {attachment.name} to the case as evidence. {detail}"}
        if self.draft_context.hinglish:
            lines = [f"Maine {attachment.name} ko case file mein Evidence ke roop mein add kar diya hai. Neeche padhi hui baat original se mila lijiye."]
            lines.extend(f"• {key}: {value} ({source})" for key, value, source in found[:5])
            lines.extend(f"• “{quote}” ({source})" for quote, source in excerpts)
            return {"reply": "\n\n".join(lines)}
        lines = [f"I attached {attachment.name} to the case as evidence. Check these details against the original."]
        lines.extend(f"• {key}: {value} ({source})" for key, value, source in found[:5])
        lines.extend(f"• “{quote}” ({source})" for quote, source in excerpts)
        if any(CANCELLATION_RECEIPT.search(quote) and re.search(r"\bcancel\w*\b", quote, re.I)
               for quote, _ in excerpts):
            lines.append("That wording acknowledges a cancellation request. Look for a separate confirmation or an effective end date.")
        if self.fraud is not None:
            lines.append("Use the transaction details you verify in your bank dispute or cybercrime report. Check any difference between the document and what you remember before submitting.")
        else:
            lines.append("These details can help you prepare the reply, complaint, or application you choose.")
        return {"reply": "\n\n".join(lines)}

    def build_pdf(self, title, draft):
        if self.uploads:
            draft += "\n\nAttachments in the case file\n" + "\n".join(
                f"- {upload.name} ({upload.purpose})" for upload in self.uploads
            )
        return make_pdf(title, draft)

    def save_pdf(self, title, draft):
        document = self.build_pdf(title, draft)
        if len(self.downloads) >= 8:
            del self.downloads[next(iter(self.downloads))]
        self.downloads[document.id] = document
        return document.link()

    def find_attachment(self, file_id):
        return self.downloads.get(file_id) or next((item for item in self.uploads if item.id == file_id), None)

    def legal_resources(self):
        return {
            "reply": "Bring the key dates, the original documents, and any replies you received. If this is in India, NALSA explains who can apply for free legal aid and how to apply.",
            "source": LEGAL_AID,
        }

    def legal(self):
        if self.payment is not None:
            return {"reply": LEGAL_CONTEXT, "source": SOURCE}
        return {"reply": LEGAL_AID_REPLY, "source": LEGAL_AID}
