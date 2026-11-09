# Legal Intake Assistant

A conversational assistant for everyday legal problems in India. It organizes a person's account, reads uploaded evidence or forms, suggests practical next steps, and prepares drafts for their review.

## Public app

[Open the Legal Intake Assistant](https://kuku-legal-intake.streamlit.app/)

## Run locally

Install Python 3.12, then run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

The model is downloaded on its first use. The app does not require an API key. You can also run the original local interface with `python app.py` and open `http://127.0.0.1:8765/`.

## Using the app

Describe the issue in your own words and press Enter to send (Shift+Enter adds a line). Use the clip in the message bar to attach a PDF, PNG, or JPG as evidence; a form is treated as evidence too, and the app will try to match its fields to details you have shared. The case file and downloadable drafts are available within the app. Start a new case when switching to a different issue.

Uploaded files and case details are kept in the current app session. They may be lost if the app restarts. Check extracted details against the original documents and review drafts before sharing them.
