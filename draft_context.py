"""Track reported drafting details and separate them from unverified legal claims."""

from dataclasses import dataclass
from decimal import Decimal
import re

from casework import money, verified_quote

AMOUNT = r"(?:₹\s*|(?:Rs\.?|INR)\s*)?\d[\d,]*(?:\.\d{1,2})?(?:\s*k\b)?"
DEPOSIT = re.compile(r"\b(?:landlord|landlady|tenant|rental|rent|flat|tenancy)\b", re.I)
MEMBERSHIP = re.compile(r"\b(?:gym|membership|subscription)\b", re.I)
LOAN = re.compile(
    r"\b(?:friend ko|dost ko|lent|loaned|personal loan|"
    r"(?:friend|dost|someone|he|she|they)\s+borrowed\b|borrowed\b[^.!?]{0,45}\bfrom me)\b",
    re.I,
)
REPAIR = re.compile(r"\b(?:repair(?:s|ed|ing)?|fix(?:ed|ing)?)\b", re.I)
REPAIR_ITEM = re.compile(r"\b(?P<value>phone|mobile|laptop|tablet|washing machine|fridge|scooter|bike|car)\b", re.I)
REPAIR_ISSUE = re.compile(r"\b(?P<value>charging|battery|screen|display|speaker|camera|leak(?:ing)?)\b", re.I)
REPAIR_REFUND = re.compile(
    r"\b(?:refund maang\w*|(?:ask(?:ing)? (?:them )?for|request(?:ing)?|want) (?:a |my |the |full )?refund)\b", re.I,
)
REPAIR_DEDUCTION = re.compile(
    r"\b(?:kis (?:baat|cheez) (?:ke liye|ke|ka)|why\b[^.!?]{0,60}\b(?:deduct\w*|withhold\w*|keep\w*|hold\w* back)|"
    r"(?:explain|ask about) (?:the |any )?deduction)\b", re.I,
)
REFUND_GOAL = "refund the repair payment"
DEDUCTION_GOAL = "explain the deduction from the repair payment"
HINGLISH = re.compile(r"\b(?:yaar|bhai|maine|mujhe|wapas|hatwana|likh de|ab kya|in (?:simple )?hindi|hindi mein?|simple hindi|kaat gaye|bana (?:do|de|dijiye)|cash mein?|kya bolu|nahi diya)\b", re.I)
ENGLISH_REQUEST = re.compile(r"\b(?:in|use|write|reply|message|msg|text|short|simple)\s+english\b|\benglish\s+(?:message|msg|reply|text|please|pls|mein|me)\b", re.I)
HINDI_REQUEST = re.compile(r"\b(?:in|use|write|reply|message|msg|text|simple)\s+hindi\b|\b(?:hindi|hinglish)\s+(?:message|msg|reply|text|please|pls|mein|me)\b", re.I)
REPLY_REQUEST = re.compile(
    r"\b(?:draft|write|compose|word|put together|make|create|prepare|give me|send me)\b"
    r"[^.!?]{0,100}\b(?:message|msg|email|reply|text|note|letter|something i can send)\b"
    r"|\b(?:whatsapp\s+)?(?:msg|message|text|reply)\s+(?:likh\b|bana\s+(?:do|de|dijiye)\b)|\blikh (?:do|de)\b", re.I
)
OUTGOING_NOTICE = re.compile(
    r"\b(?:draft|write|prepare|put|include|send)\b[^.!?]{0,90}\b(?:a |the )?(?:legal )?notice\b", re.I
)
PDF_REQUEST = re.compile(r"\b(?:as a pdf|in pdf|pdf (?:version|draft)|download (?:it|the draft) as pdf)\b", re.I)
LEGAL_CLAIM = re.compile(
    r"\b(?:section|article|rule)\s+\d+[a-z0-9()/-]*\b"
    r"|\bunder (?:the )?[^.!?]{2,70}\bAct(?:\s+\d{4})?\b"
    r"|\b(?:pay|owe|return)\b[^.!?]{0,35}\b(?:double|twice)\b"
    r"|\b(?:double repayment|entitled to (?:double|twice)|the law says|legally required to)\b",
    re.I,
)
CLAIM_ATTRIBUTION = re.compile(r"\b(?:i (?:saw|heard|read)|saw a reel|a reel says|someone said|according to)\b", re.I)
REASON_UNKNOWN = re.compile(r"\b(?:no reason|didn['’]?t give (?:me )?a reason|hasn['’]?t given (?:me )?a reason|i don['’]?t know why|reason nahi)\b", re.I)
RECIPIENT = re.compile(
    r"\b(?:send (?:it|this) to|address (?:it|this) to|write to|"
    r"(?:draft|write|compose)\b[^.!?]{0,40}\b(?:message|msg|email|reply|text) to)\s+"
    r"(?P<value>[^.!?;]{2,75}?)(?=\s+(?:asking|requesting|to ask)\b|[.!?;]|$)",
    re.I,
)
ROLE = re.compile(r"^(?:to )?(?:my |the )?(?:landlord|landlady|friend|dost|neighbou?r|employer|payroll|seller|gym accounts team|accounts team)[.! ]*$", re.I)
GOAL = re.compile(
    r"\b(?:i want (?:them|him|her|you) to|i want to ask (?:them|him|her) to|"
    r"(?:ask|asking) (?:them|him|her) to|please ask (?:them|him|her) to) "
    r"(?P<value>[^.!?;]{3,180})", re.I,
)
VAGUE_GOAL = re.compile(
    r"(?:help with\s+)?(?:the\s+full\s+amount|the\s+amount|the\s+full\s+deposit|"
    r"my\s+money|the\s+money|it(?:\s+back)?|the\s+rest|everything)\.?", re.I,
)
DATE_HINT = r"(?:\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}(?:\s+\d{4})?|[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|last month|yesterday|today|(?:\d+|one|two|three|four|five|six) months? ago|\d{4}-\d{2}-\d{2})"
SHORT = re.compile(r"\b(?:keep it short|short pls|short please|casual|normal rakhna|short rakh)\b", re.I)


def strip_legal_claims(message):
    kept = []
    omitted = False
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", message):
        claim = LEGAL_CLAIM.search(sentence)
        if not claim:
            kept.append(sentence)
            continue
        omitted = True
        attribution = CLAIM_ATTRIBUTION.search(sentence[:claim.start()])
        if attribution:
            prefix = sentence[:attribution.start()].rstrip(" ,;")
            if prefix:
                kept.append(prefix)
    return " ".join(kept).strip(), omitted


def case_kind(message):
    if DEPOSIT.search(message) and re.search(r"\bdeposit\b", message, re.I):
        return "deposit"
    if MEMBERSHIP.search(message) and re.search(r"\b(?:cancell?ed|cancell?ation|charged|charge|took|refund|ended|still active|band|kaat gaye)\b", message, re.I):
        return "membership"
    if LOAN.search(message) and re.search(rf"{AMOUNT}|\b(?:lent|borrowed|repay|wapas)\b", message, re.I):
        return "loan"
    if REPAIR.search(message) and (REPAIR_ITEM.search(message) or re.search(r"\b(?:repair shop|repair wal[ae]|repair service)\b", message, re.I)):
        return "repair"
    return ""


def amount_from(raw):
    raw = re.sub(r"(?i)(?:₹|Rs\.?|INR|,|\s)", "", raw)
    return Decimal(raw[:-1]) * 1000 if raw.lower().endswith("k") else Decimal(raw)


def extract(pattern, message):
    match = re.search(pattern, message, re.I)
    return match.group("value").strip() if match else ""


@dataclass
class DraftContext:
    kind: str = ""
    recipient: str = ""
    goal: str = ""
    amount: Decimal | None = None
    repaid: Decimal | None = None
    deduction: Decimal | None = None
    moved_out: str = ""
    reason: str = ""
    charge_when: str = ""
    cancel_when: str = ""
    cancellation_received: bool = False
    cancellation_confirmed: bool = False
    loan_when: str = ""
    whatsapp: bool = False
    screenshot: bool = False
    hinglish: bool = False
    short: bool = False
    request_pdf: bool = False
    last_action: str = ""
    repayment_unclear: bool = False
    repair_item: str = ""
    repair_issue: str = ""
    repair_payment_method: str = ""
    repair_unresolved: bool = False
    repair_no_bill: bool = False
    repair_marked_done: bool = False
    repair_refund_offer: Decimal | None = None
    repair_deduction: Decimal | None = None

    def update(self, message, extracted):
        self.kind = self.kind or case_kind(message)
        if ENGLISH_REQUEST.search(message):
            self.hinglish = False
        elif HINDI_REQUEST.search(message) or HINGLISH.search(message):
            self.hinglish = True
        elif re.search(r"\b(?:kya|mujhe|mera|meri|nahi|nahin|hai|hain|ko|likh|bolo|bata|chahiye|wala|wale|waise|dusra|aaya)\b", message, re.I):
            self.hinglish = True
        else:
            self.hinglish = False
        self.whatsapp = self.whatsapp or bool(re.search(r"\bWhatsApp\b", message, re.I))
        self.screenshot = self.screenshot or bool(re.search(r"\bscreenshots?\b", message, re.I))
        self.short = self.short or bool(SHORT.search(message))
        self.request_pdf = self.request_pdf or bool(PDF_REQUEST.search(message))
        recipient = RECIPIENT.search(message)
        if recipient:
            self.recipient = recipient["value"].strip()
        elif ROLE.fullmatch(message.split(".", 1)[0].strip()):
            self.recipient = message.split(".", 1)[0].strip().removeprefix("to ")
        elif not self.recipient:
            proposed = verified_quote(extracted.get("draft_recipient"), message, 75)
            if proposed and re.search(r"\b(?:to|recipient)\s+" + re.escape(proposed) + r"\b", message, re.I):
                self.recipient = proposed
        goal = GOAL.search(message)
        if goal:
            self.goal = goal["value"].strip()
        elif REPLY_REQUEST.search(message):
            requested = extract(r"\b(?:asking for|requesting)\s+(?P<value>[^.!?;]{3,120})", message)
            if requested:
                self.goal = "help with " + requested
        elif not self.goal and re.search(r"\b(?:I want|please ask|wapas maang)\b", message, re.I):
            self.goal = verified_quote(extracted.get("goal"), message, 180) or ""
        if self.kind == "deposit":
            self.update_deposit(message)
        elif self.kind == "membership":
            self.update_membership(message)
        elif self.kind == "loan":
            self.update_loan(message)
        elif self.kind == "repair":
            self.update_repair(message)

    def update_deposit(self, message):
        self.recipient = self.recipient or "my landlord"
        # A clearly vague ask ("the full amount", "it back") should become the
        # concrete deposit request; keep a specific goal the person already gave.
        if not self.goal or VAGUE_GOAL.fullmatch(self.goal.strip()):
            self.goal = "return my full security deposit, or explain any deduction in writing"
        for pattern in (rf"(?P<value>{AMOUNT})\s+(?:security )?deposit\b",
                        rf"\bdeposit\s+(?:was|of|is)\s+(?P<value>{AMOUNT})"):
            amount = extract(pattern, message)
            if amount:
                self.amount = amount_from(amount)
                break
        if self.amount is None and self.last_action == "notice":
            amount = extract(rf"^\s*(?:it was |the amount was )?(?P<value>{AMOUNT})(?=[.!?,]|$)", message)
            if amount:
                self.amount = amount_from(amount)
        moved = extract(rf"\b(?:moved out|vacated|left the flat)\s+(?:on\s+)?(?P<value>{DATE_HINT})", message)
        moved = moved or extract(r"\bflat chh?oda\s+(?P<value>\d+ months?)\s+ho gaye\b", message)
        if moved:
            self.moved_out = moved + " ago" if "ho gaye" in message.lower() and re.fullmatch(r"\d+ months?", moved) else moved
        deduction = extract(rf"\bpainting(?:\s+ka|\s+cost(?:s| of)?|\s+deduction of)?\s+(?P<value>{AMOUNT})", message)
        if deduction:
            self.deduction = amount_from(deduction)
            self.reason = "painting was mentioned as a deduction"
        elif REASON_UNKNOWN.search(message):
            self.reason = "no reason was given"
        else:
            reason = extract(r"\b(?:reason was|said (?:it was )?for|said (?:it was )?because)\s+(?P<value>[^.!?;]{3,100})", message)
            if reason:
                self.reason = reason

    def update_membership(self, message):
        self.recipient = self.recipient or (
            "Gym Accounts Team" if re.search(r"\bgym\b", message, re.I) and re.search(r"\baccounts\b", message, re.I) else ""
        )
        charge = extract(rf"\b(?:took|charged|debited)\s+(?:me\s+)?(?P<value>{AMOUNT})", message)
        charge = charge or extract(rf"(?P<value>{AMOUNT})\s+(?:charge|was charged|was debited)\b", message)
        charge = charge or extract(rf"(?P<value>{AMOUNT})\s+(?:kaat|kat)\s+(?:gaye|liye|gaya)\b", message)
        if charge:
            self.amount = amount_from(charge)
            self.charge_when = extract(r"\b(?P<value>yesterday|today|this morning)\b", message) or self.charge_when
        cancelled = extract(rf"\b(?:cancell?ed|requested cancellation(?: of)?)\b[^.!?]{{0,45}}?\s+(?P<value>{DATE_HINT})\b", message)
        self.cancel_when = cancelled or self.cancel_when
        self.cancellation_received = self.cancellation_received or bool(re.search(r"\brequest received\b", message, re.I))
        if re.search(r"\b(?:confirmed (?:my )?cancellation|cancellation (?:is|was) confirmed|membership end date (?:is|was))\b", message, re.I):
            self.cancellation_confirmed = True
        if REPLY_REQUEST.search(message) and not self.goal and re.search(r"\b(?:cancell?ation|cancell?ed|membership)\b", message, re.I):
            self.goal = "confirm in writing whether my membership has been cancelled and its effective date"

    def update_loan(self, message):
        self.recipient = self.recipient or "my friend"
        self.goal = self.goal or "ask for the remaining money back"
        correction = extract(rf"{AMOUNT}\s+(?:nahi|nahin|not)[, ]+?(?P<value>{AMOUNT})\b", message)
        if not correction:
            correction = extract(rf"\b(?:actual amount was|it was|correct amount is)\s+(?P<value>{AMOUNT})(?=\s|[.!?,]|$)", message)
        original = extract(rf"\b(?:friend ko|dost ko|(?:lent|loaned|gave)(?: my friend| them| him| her)?|"
                           rf"(?:friend|dost|someone|he|she|they)\s+borrowed)\s+(?P<value>{AMOUNT})(?=\s|[.!?,]|$)", message)
        if correction or original:
            self.amount = amount_from(correction or original)
        when = extract(r"\b(?:in\s+(?P<value>january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec))\b", message)
        when = when or extract(r"\b(?P<value>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(?:me|mein)\b", message)
        if when:
            self.loan_when = when.capitalize()
        paid = extract(rf"(?P<value>{AMOUNT})\s+(?:wapas\s+(?:kar\s+|de\s+)?(?:diye|diya|kiya|kiye|di)|laut(?:a|aye|a diye|a diya)|paid back|repaid)\b", message)
        paid = paid or extract(rf"\b(?:paid back|repaid|returned)\s+(?:another |additional |a total of )?(?P<value>{AMOUNT})(?=\s|[.!?,]|$)", message)
        if paid and not re.search(r"\b(?:if|agar)\b", message, re.I):
            if re.search(r"\b(?:another|additional|aur bhi)\b", message, re.I):
                self.repayment_unclear = self.repaid is None or self.repayment_unclear
                if not self.repayment_unclear:
                    self.repaid += amount_from(paid)
            else:
                self.repaid = amount_from(paid)
                self.repayment_unclear = False
        elif re.search(r"\b(?:paid back|repaid|returned)\s+nothing\b|\b(?:hasn['’]?t|never) paid (?:me )?back\b", message, re.I):
            self.repaid = Decimal(0)
            self.repayment_unclear = False
        # A direct "write X" / "X likhna" instruction gives the exact figure to
        # request, so treat it as the remaining amount (the person did the math).
        final = extract(rf"(?P<value>{AMOUNT})\s+likh\s*(?:na|do|de|dena|dijiye)?\b", message)
        final = final or extract(rf"\b(?:write|put|make it)\s+(?P<value>{AMOUNT})\b", message)
        if final:
            self.amount = amount_from(final)
            self.repaid = None
            self.repayment_unclear = False

    def update_repair(self, message):
        self.recipient = self.recipient or "the repair shop"
        self.goal = self.goal or "recheck the repair"
        if not ENGLISH_REQUEST.search(message):
            self.hinglish = self.hinglish or bool(re.search(r"\b(?:likh do|refund maang\w*|abhi bhi|pehle puchna)\b", message, re.I))
        if item := REPAIR_ITEM.search(message):
            self.repair_item = item["value"]
        if issue := REPAIR_ISSUE.search(message):
            self.repair_issue = issue["value"]
        payment = re.search(
            rf"\b(?:paid|charged|took)(?: me| them)?\s+(?P<after>{AMOUNT})(?![\w,])"
            rf"|(?P<before>{AMOUNT})(?![\w,])\s+(?:cash\s+)?(?:liye|diye|paid|charged)\b",
            message, re.I,
        )
        if payment:
            self.amount = amount_from(payment["after"] or payment["before"])
            payment_sentence = next((part for part in re.split(r"(?<=[.!?])\s+", message) if payment[0] in part), "")
            method = re.search(r"\b(?:cash|UPI|card)\b", payment_sentence, re.I)
            if method:
                self.repair_payment_method = method[0].lower()
        if re.search(r"\b(?:same problem|same issue|still (?:broken|faulty|not working|won['’]?t charge|leak\w*)|"
                     r"abhi bhi leak\w*|problem (?:abhi bhi|wapas))\b", message, re.I):
            self.repair_unresolved = True
        if re.search(r"\b(?:(?:bill|receipt|invoice) nahi (?:diya|mila)|no (?:bill|receipt|invoice)|didn['’]?t (?:give|get) (?:me )?(?:a |the )?(?:bill|receipt|invoice))\b", message, re.I):
            self.repair_no_bill = True
        if re.search(r"\bwhatsapp\b[^.!?]{0,50}\b(?:done|fixed|completed?)\b", message, re.I) and not re.search(
            r"\b(?:not|never) (?:done|fixed|completed?)\b", message, re.I,
        ):
            self.repair_marked_done = True
        offered = extract(rf"\b(?:offered (?:to (?:refund|return) )?|(?:said (?:he|she|they)(?:['’]ll| will) )"
                          rf"(?:refund|return) )(?P<value>{AMOUNT})(?![\w,])", message)
        offered = offered or extract(rf"(?P<value>{AMOUNT})\s+(?:refund|return|wapas)\s+(?:kar dega|kar denge|dega|denge)\b", message)
        if offered:
            self.repair_refund_offer = amount_from(offered)
        if REPAIR_DEDUCTION.search(message):
            self.goal = DEDUCTION_GOAL
            deduction = extract(rf"\b(?:baaki|remaining|deduction of)\s+(?P<value>{AMOUNT})(?![\w,])", message)
            if deduction:
                self.repair_deduction = amount_from(deduction)
        elif REPAIR_REFUND.search(message):
            self.goal = REFUND_GOAL

    def repair_message(self):
        item = f"{self.repair_item.lower()} repair" if self.repair_item else "repair"
        issue = self.repair_issue.lower()
        amount = money(self.amount) if self.amount is not None else ""
        method = self.repair_payment_method
        if self.goal == DEDUCTION_GOAL:
            return self.repair_deduction_message()
        if self.hinglish:
            paid = f"{amount}{' ' + method + ' mein' if method else ''} diye the"
            opening = f"Hi, maine {item} ke liye {paid}." if amount else f"Hi, {item} ke baare mein baat karni thi."
            status = ""
            if self.repair_marked_done:
                status = " Aapne WhatsApp pe kaha tha ki repair ho gaya."
            if self.repair_unresolved:
                if issue.startswith("leak") and self.repair_item.lower() == "washing machine":
                    status += " Machine abhi bhi leak kar rahi hai."
                else:
                    status += f" {issue.capitalize()} ki problem abhi bhi hai." if issue else " Wahi problem abhi bhi hai."
            receipt = " Bill bhi bhej dijiye." if self.repair_no_bill else ""
            ask = (f"Kya aap {amount + ' ka ' if amount else ''}refund kar sakte hain?"
                   if self.goal == REFUND_GOAL else "Please ek baar phir check karke bata dijiye.")
            return f"{opening}{status} {ask}{receipt}"
        opening = f"Hi, I paid {amount}{' by ' + method if method else ''} for the {item}." if amount else f"Hi, I’m following up on the {item}."
        status = " You said on WhatsApp that the repair was complete." if self.repair_marked_done else ""
        if self.repair_unresolved:
            status += f" The {issue + ' ' if issue else ''}problem is still there."
        receipt = " Please also send me the bill." if self.repair_no_bill else ""
        ask = (f"Could you please refund {amount or 'the repair payment'}?"
               if self.goal == REFUND_GOAL else "Could you take another look and let me know?")
        return f"{opening}{status} {ask}{receipt}"

    def repair_deduction_message(self):
        paid, offered = self.amount, self.repair_refund_offer
        deduction = self.repair_deduction
        if paid is not None and offered is not None:
            difference = paid - offered
            deduction = difference if difference > 0 and deduction in (None, difference) else None
        amount = money(deduction) if deduction is not None else ""
        if self.hinglish:
            opening = f"Hi, {money(offered)} ke refund offer ke liye thanks." if offered is not None else "Hi."
            paid_line = f" Maine repair ke liye {money(paid)} diye the." if paid is not None else ""
            ask = (f"Kya aap bata sakte hain ki baaki {amount} kis cheez ke liye kaat rahe hain?"
                   if amount else "Kya aap bata sakte hain ki refund mein kitna aur kis wajah se kaat rahe hain?")
        else:
            opening = f"Hi, thanks for offering a {money(offered)} refund." if offered is not None else "Hi."
            paid_line = f" I paid {money(paid)} for the repair." if paid is not None else ""
            ask = (f"Could you please explain what the {amount} deduction is for?"
                   if amount else "Could you please explain how you worked out the refund amount?")
        return f"{opening}{paid_line} {ask}"

    def balance(self):
        return self.amount - (self.repaid or Decimal(0)) if self.amount is not None and not self.repayment_unclear else None

    def deposit_help(self):
        value = f"{money(self.amount)} ke deposit ke liye " if self.amount is not None else "Deposit ke liye "
        first = value + "landlord ko WhatsApp par written breakdown maango. Pucho kya deduct kar rahe hain, uske bills kya hain, aur baaki deposit kab return hoga."
        if self.deduction is not None:
            first += f" Pehle painting ke liye {money(self.deduction)} bola tha, toh pucho ki ab poora deposit kyun rok rahe hain."
        if self.whatsapp:
            first += " Jo WhatsApp chats hain, unhe save kar lo."
        return first

    def notice_missing(self):
        fields = []
        if self.amount is None:
            fields.append("how much the deposit was")
        if not self.moved_out:
            fields.append("when you moved out")
        if not self.reason:
            fields.append("whether your landlord gave a reason for keeping it")
        if not fields:
            return ""
        if len(fields) == 1:
            return f"Could you tell me {fields[0]}?"
        return "Could you tell me " + ", ".join(fields[:-1]) + " and " + fields[-1] + "?"

    def deposit_notice(self):
        period = self.moved_out if self.moved_out.endswith("ago") or self.moved_out in (
            "today", "yesterday", "last month",
        ) else "on " + self.moved_out
        reason = ("I haven’t been given a reason for the deduction." if self.reason == "no reason was given"
                  else f"The explanation I was given was that {self.reason.rstrip('.')}.")
        return (
            f"To: {self.recipient}\nSubject: Return of security deposit\n\n"
            f"I moved out {period} and am writing about the {money(self.amount)} security deposit. "
            f"{reason}\n\nPlease {self.goal.rstrip('.')}. If you propose any deductions, "
            "please send a written breakdown and the records supporting them.\n\n"
            "Regards,\n[your name]"
        )

    def no_reply_step(self, message):
        if self.kind == "loan":
            return (
                "Agar reply na aaye, ek short written follow-up bhej kar repayment ki date pucho. "
                "Jo payment records aur chats hain, unhe sambhal kar rakho. Agar phir bhi baat na bane, lawyer ko records dikha sakte ho."
                if self.hinglish else
                "If your friend doesn’t reply, send one short follow-up asking for a repayment date. "
                "Keep the transfer record and messages. A lawyer can review them if you need help deciding what to do next."
            )
        recipient = self.recipient or "the recipient"
        if re.search(r"\b(?:already followed up|followed up twice|sent a reminder)\b", message, re.I):
            return (f"Keep copies of your messages to {recipient} and note when you sent them. "
                    "If the issue is unresolved, ask a lawyer to review what you sent and what evidence you have.")
        return (f"If {recipient} doesn’t reply, send one short follow-up in writing. "
                f"Mention when you first contacted them and restate your request (“{self.goal.rstrip('.')}”). "
                "Keep copies of both messages.")

    def loan_message(self):
        balance = self.balance()
        if balance is None:
            return ""
        if balance < 0:
            return ""
        if not balance:
            return ""
        if self.repaid is None:
            if self.hinglish:
                when = f"{self.loan_when} mein " if self.loan_when else ""
                return f"Hey, {when}jo {money(self.amount)} diye the, unka ek follow-up. Bata dena kab tak wapas bhej paoge. Thanks!"
            return f"Hey, just following up on the {money(self.amount)} I lent you. Could you let me know when you can send it back? Thanks!"
        if self.hinglish:
            return f"Hey, jo paise diye the usme se {money(balance)} baaki hai. Jab chance mile toh bata dena kab tak bhej paoge. Thanks!"
        return f"Hey, just following up on the money I lent you. There’s {money(balance)} left. Could you let me know when you can send it back? Thanks!"

    def membership_message(self):
        greeting = self.recipient
        if greeting.lower().startswith("the "):
            greeting = greeting[4:]
        if self.hinglish and self.cancellation_received and not self.cancellation_confirmed:
            return (f"Hi {greeting},\n\nMujhe cancellation request receive hone ka email mila hai, "
                    "lekin membership band hone ki confirmation nahi mili. Please likh kar bata dijiye "
                    "ki membership band hui hai ya nahi aur kis date se.\n\nThanks.")
        if self.cancellation_received and not self.cancellation_confirmed:
            sent = 'I have an email marked “request received” for my cancellation request, but I have not received confirmation that my membership ended.'
        else:
            sent = "I sent a cancellation request" + (f" {self.cancel_when}" if self.cancel_when else "") + "."
        charge = f" I was charged {money(self.amount)}" if self.amount is not None else ""
        if charge and self.charge_when:
            charge += f" {self.charge_when}"
        request = self.goal.rstrip(".")
        actions = []
        if "whether my membership has been cancelled" in request:
            actions.append(request)
        elif re.search(r"\b(?:confirm|when|membership ends)\b", request, re.I):
            actions.append("confirm my membership end date")
        if re.search(r"\brefund\b", request, re.I):
            actions.append(f"refund the {money(self.amount)} charge" if self.amount is not None else "refund the last charge")
        if re.search(r"\b(?:stop|future|further)\b", request, re.I):
            actions.append("stop future charges")
        if not actions:
            actions = [request]
        ask = (", ".join(actions[:-1]) + ", and " + actions[-1]) if len(actions) > 2 else " and ".join(actions)
        return f"Hi {greeting},\n\n{sent}{charge + '.' if charge else ''} Please {ask}.\n\nThanks."

    def compose_message(self, facts, recent_turns, model):
        goal = self.goal.rstrip(".")
        details = {label: value for label, value in facts.items()
                   if label in ("Reported events", "Reported deposit", "When it happened", "What you reported") and value}
        if model is not None and hasattr(model, "compose_reply"):
            candidate = model.compose_reply(self.recipient, goal, details, recent_turns, self.hinglish, self.short)
            if isinstance(candidate, str) and candidate.strip() and len(candidate) <= 900:
                allowed = " ".join((goal, *details.values()))
                used_numbers = set(re.findall(r"\d[\d,]*", candidate))
                if not LEGAL_CLAIM.search(candidate) and goal.lower() in candidate.lower() and used_numbers <= set(re.findall(r"\d[\d,]*", allowed)):
                    return candidate.strip()
        greeting = self.recipient
        if greeting.lower().startswith(("my ", "the ")):
            greeting = greeting.split(" ", 1)[1]
        note = ""
        if "Reported deposit" in details:
            note = f"I’m following up on my {details['Reported deposit']} security deposit. "
        elif self.kind == "deposit":
            note = "I’m following up about my security deposit. "
        elif "outstanding pay" in goal:
            story = facts.get("What you reported", "")
            period = re.search(r"\b(?:last|past|previous)\s+\d+\s+(?:days?|weeks?|months?)\b", story, re.I)
            note = f"I’m following up about my pay for the {period[0]}. " if period else "I’m following up about my outstanding pay. "
        return f"Hi {greeting},\n\n{note}Could you please {goal}?\n\nThanks."
