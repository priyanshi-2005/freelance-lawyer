"""Streamlit frontend for the Legal Intake Assistant."""

from copy import deepcopy
from threading import Lock

import streamlit as st

from case_documents import MAX_FILE_BYTES
from intake import Conversation, LEGAL_AID, WELCOME
from model import DEFAULT_MODEL, LocalModel


st.set_page_config(page_title="Legal Intake Assistant", layout="centered")
st.markdown(
    """
    <style>
    .stApp { color: #1d2926; }
    .block-container { max-width: 1120px; padding-top: 2rem; padding-bottom: 2rem; }
    h1 { letter-spacing: -0.025em; }
    [data-testid="stChatMessage"] { border: 1px solid #d7e1dc; border-radius: 16px; }
    [data-testid="stChatMessage"] p { font-size: 1.02rem; }
    [data-testid="stFileUploaderDropzone"] { padding: 0; min-height: 0; border: 0; background: transparent; }
    [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [data-testid="stFileUploaderDropzone"] button { margin: 0; }
    [data-testid="stFileUploader"] small { display: none; }
    [data-testid="stTextArea"] textarea { min-height: 90px; }
    [data-testid="stForm"] { margin-top: 4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


class LockedModel:
    """Serialize generation while sharing one downloaded model across sessions."""

    def __init__(self):
        self.model = LocalModel(DEFAULT_MODEL, dtype="auto")
        self.lock = Lock()

    def intake(self, *args, **kwargs):
        with self.lock:
            return self.model.intake(*args, **kwargs)

    def extract(self, *args, **kwargs):
        with self.lock:
            return self.model.extract(*args, **kwargs)

    def compose_reply(self, *args, **kwargs):
        with self.lock:
            return self.model.compose_reply(*args, **kwargs)


@st.cache_resource(show_spinner="Loading the language model for the first conversation…")
def shared_model():
    return LockedModel()


def fresh_case():
    st.session_state.case = Conversation()
    st.session_state.messages = [{"role": "assistant", "reply": WELCOME}]
    st.session_state.show_case = False


def initialize():
    if "case" not in st.session_state:
        fresh_case()


def source_link(source):
    if source:
        st.link_button(source["label"], source["url"])


def draft_download(case, response, key):
    draft = response.get("draft")
    if not draft:
        return
    title = response.get("draft_title") or "Case file"
    st.markdown(draft.replace("\n", "  \n"))
    pdf = case.build_pdf(title, draft)
    st.download_button(
        f"Download {pdf.name}", pdf.content, file_name=pdf.name,
        mime=pdf.media_type, key=f"draft-{key}",
    )


def use_choice(choice, message_index):
    case = deepcopy(st.session_state.case)
    response = case.choose(choice["id"])
    st.session_state.case = case
    st.session_state.messages.append({"role": "user", "reply": choice["label"]})
    st.session_state.messages.append({"role": "assistant", **response})


def render_message(item, index):
    avatar = ":material/gavel:" if item["role"] == "assistant" else ":material/person:"
    with st.chat_message(item["role"], avatar=avatar):
        st.markdown(item.get("reply", "").replace("\n", "  \n"))
        if item.get("attachment_label"):
            st.caption(item["attachment_label"])
        source_link(item.get("source"))
        for source in item.get("sources", ()):
            source_link(source)
        draft_download(st.session_state.case, item, index)
        for choice_index, choice in enumerate(item.get("choices", ())):
            if st.button(
                choice["label"], key=f"choice-{index}-{choice_index}-{choice['id']}",
                use_container_width=False,
            ):
                use_choice(choice, index)
                st.rerun()


def case_panel():
    if not st.session_state.show_case:
        return
    case = st.session_state.case
    view = case.view()
    with st.container(border=True):
        st.caption("Details and records you reported in this chat")
        if not view["facts"] and not view["records"] and not view["attachments"]:
            st.write("No case details yet.")
            return
        if view["facts"]:
            st.subheader("Reported details", divider=False)
            for label, value in view["facts"].items():
                st.markdown(f"**{label}:** {value}")
        if view["records"]:
            st.subheader("Reported records", divider=False)
            for label, values in view["records"].items():
                st.markdown(f"**{label}:** {', '.join(values)}")
        if view["attachments"]:
            st.subheader("Files in this case", divider=False)
            for uploaded in case.uploads:
                with st.expander(f"{uploaded.purpose.title()} · {uploaded.name}"):
                    for page, method, text in uploaded.pages:
                        st.caption(f"Page {page} · {method}")
                        st.text(text[:1200] or "No readable text found.")
                    st.download_button(
                        "Download original", uploaded.content, file_name=uploaded.name,
                        mime=uploaded.media_type, key=f"original-{uploaded.id}",
                    )
        draft, note = case.draft()
        if draft:
            st.caption(note)
            pdf = case.build_pdf("Case file", draft)
            st.download_button(
                "Download case file as PDF", pdf.content, file_name="case-file.pdf",
                mime="application/pdf", key="case-pdf",
            )


def submit(message, upload):
    message = (message or "").strip()
    if not message and upload is None:
        return
    if len(message) > 2500:
        st.error("Keep your message under 2,500 characters.")
        return

    case = deepcopy(st.session_state.case)
    attachment = None
    try:
        if upload is not None:
            content = upload.getvalue()
            if len(content) > MAX_FILE_BYTES:
                raise ValueError("Choose a file no larger than 5 MB.")
            attachment = case.attach(upload.name, content, "evidence")
        if message:
            with st.spinner("Reading your message and the attached file…" if attachment else "Preparing a response…"):
                response = case.respond(message, shared_model(), attachment=attachment)
        else:
            response = case.describe_upload(attachment)
    except ValueError as error:
        st.error(str(error))
        return
    except Exception:
        st.error("I couldn’t process that message. Your existing case is unchanged. Please try again.")
        return

    st.session_state.case = case
    user_text = message or f"Attached {attachment.name}"
    user_item = {"role": "user", "reply": user_text}
    if attachment:
        user_item["attachment_label"] = f"{attachment.purpose.title()}: {attachment.name}"
    st.session_state.messages.append(user_item)
    st.session_state.messages.append({"role": "assistant", **response})


initialize()
st.title("Legal Intake Assistant")
st.caption("Organize an everyday legal problem in India and find a practical next step.")
st.divider()

left, _, right = st.columns([1, 5, 1])
with left:
    if st.button("View case file", use_container_width=False):
        st.session_state.show_case = not st.session_state.show_case
with right:
    if st.button("Start new case", use_container_width=False):
        fresh_case()
        st.rerun()

case_panel()
for index, message in enumerate(st.session_state.messages):
    render_message(message, index)

# Chat-style input: Enter sends, Shift+Enter adds a new line, and the clip
# attaches evidence (PDF/photo/screenshot) in the same bar.
prompt = st.chat_input(
    "Tell me what happened in your own words",
    accept_file=True,
    file_type=("pdf", "png", "jpg", "jpeg"),
    max_chars=2500,
)
if prompt:
    files = getattr(prompt, "files", None) or []
    text = getattr(prompt, "text", "") or ""
    submit(text, files[0] if files else None)
    st.rerun()

st.caption("Attach evidence (a PDF, photo, or screenshot, up to 5 MB) with the clip. Enter sends; Shift+Enter adds a line. Keep PINs, OTPs, and passwords out of uploads.")
st.markdown(
    f"Legal resources · [{LEGAL_AID['label']}]({LEGAL_AID['url']}) explains who can apply "
    "for free legal aid and how to apply."
)
st.caption("General legal information and case preparation for your review.")
