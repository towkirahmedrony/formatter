import streamlit as st
import pandas as pd
import google.generativeai as genai
from rapidfuzz import process, fuzz
import json
import ast
import re
import typing_extensions as typing

# ----------------------------
# Page Config
# ----------------------------
st.set_page_config(
    page_title="Pro MCQ & EIIN Matcher",
    page_icon="⚡",
    layout="centered"
)

st.title("⚡ Pro MCQ & Institution Matcher")
st.markdown("একাধিক বিশ্ববিদ্যালয়, ইউনিট, সাল ও ব্যাখ্যাসহ MCQ ফরম্যাট করুন।")

# ----------------------------
# Load Gemini API Key
# ----------------------------
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("⚠️ Streamlit Secrets-এ GEMINI_API_KEY পাওয়া যায়নি।")
    st.stop()


# ----------------------------
# Load Institution Database
# ----------------------------
@st.cache_data
def load_data():
    df = pd.read_csv("institutions_rows.csv")

    name_to_eiin = {}

    for row in df.itertuples(index=False):
        code = ""

        if (
            hasattr(row, "code")
            and pd.notna(row.code)
            and str(row.code).strip()
            and str(row.code).lower() != "nan"
        ):
            code = str(row.code).strip()

        elif (
            hasattr(row, "eiin")
            and pd.notna(row.eiin)
            and str(row.eiin).strip()
            and str(row.eiin).lower() != "nan"
        ):
            code = str(row.eiin).strip()

        if not code:
            continue

        for field in ["name_en", "name_bn", "short_name"]:
            if hasattr(row, field):
                value = getattr(row, field)

                if pd.notna(value):
                    value = str(value).strip()

                    if value:
                        name_to_eiin[value] = code

        if hasattr(row, "aliases") and pd.notna(row.aliases):
            aliases_str = str(row.aliases).strip()

            if aliases_str:
                try:
                    if aliases_str.startswith("["):
                        aliases = ast.literal_eval(aliases_str)

                        if isinstance(aliases, list):
                            for alias in aliases:
                                alias = str(alias).strip()

                                if alias:
                                    name_to_eiin[alias] = code
                    else:
                        name_to_eiin[aliases_str] = code

                except (ValueError, SyntaxError):
                    pass

    return name_to_eiin


name_to_eiin = load_data()
choices = list(name_to_eiin.keys())


# ----------------------------
# Gemini Schema
# ----------------------------
class MCQItem(typing.TypedDict):
    question: str
    options: list[str]
    answer: str
    years: list[str]
    institutions: list[str]
    units: list[str]
    explanation: str
    subject: str
    chapter: str
    topic: str


# ----------------------------
# Helper Functions
# ----------------------------
def normalize_list(value):
    """Convert string/list/None into a clean list."""

    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(x).strip()
            for x in value
            if x is not None and str(x).strip()
        ]

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        return [value]

    return [str(value).strip()]


def get_field(item, *keys, default=""):
    """Support alternative field names."""

    for key in keys:
        value = item.get(key)

        if value is not None:
            return value

    return default


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


# ----------------------------
# Gemini Extraction
# ----------------------------
def extract_mcq_with_gemini(raw_text):

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    prompt = f"""
তুমি একজন অত্যন্ত নির্ভুল MCQ Data Extractor।

তোমার কাজ হলো দেওয়া RAW TEXT থেকে প্রতিটি MCQ-এর তথ্য সংগ্রহ করে
শুধুমাত্র একটি valid JSON Array রিটার্ন করা।

প্রতিটি প্রশ্নের জন্য নিচের JSON Structure অনুসরণ করবে:

{{
    "question": "সম্পূর্ণ প্রশ্ন",
    "options": [
        "প্রথম অপশন",
        "দ্বিতীয় অপশন",
        "তৃতীয় অপশন",
        "চতুর্থ অপশন"
    ],
    "answer": "সঠিক উত্তর",
    "years": ["2022-23", "2020-21"],
    "institutions": ["CU", "NSTU"],
    "units": ["A", "B"],
    "explanation": "প্রশ্নের ব্যাখ্যা",
    "subject": "বাংলা",
    "chapter": "অধ্যায়ের নাম",
    "topic": "নির্দিষ্ট টপিক"
}}

গুরুত্বপূর্ণ নিয়ম:

1. প্রতিটি প্রশ্নের মূল বক্তব্য হুবহু সংরক্ষণ করবে।

2. কোনো প্রশ্ন বা অপশন বাদ দেবে না।

3. সবগুলো অপশন একই ক্রমে রাখবে।

4. সঠিক উত্তর থাকলে সেটি সংগ্রহ করবে।

5. years ফিল্ডে প্রশ্নের সঙ্গে সম্পর্কিত সব সাল সংরক্ষণ করবে।

6. institutions ফিল্ডে সব বিশ্ববিদ্যালয়, বোর্ড বা প্রতিষ্ঠানের নাম সংরক্ষণ করবে।

7. units ফিল্ডে সংশ্লিষ্ট সব ইউনিটের নাম বা নম্বর সংরক্ষণ করবে।

8. একই প্রশ্ন একাধিক বিশ্ববিদ্যালয়, ইউনিট বা সালে এসে থাকলে
সব তথ্য একই প্রশ্নের অধীনে সংরক্ষণ করবে।

9. explanation ফিল্ডে ইনপুটে থাকা ব্যাখ্যা হুবহু সংগ্রহ করবে।
ব্যাখ্যা না থাকলে খালি string ("") দেবে।
নিজে থেকে কোনো ব্যাখ্যা তৈরি করবে না।

10. subject, chapter ও topic ইনপুটে থাকলে সংগ্রহ করবে।
না থাকলে খালি string দেবে।

11. কোনো তথ্য অনুমান করে তৈরি করবে না।

12. প্রশ্নের ক্রম অপরিবর্তিত রাখবে।

13. একই প্রশ্নের ভিন্ন সংস্করণ থাকলে সেগুলোকে জোর করে
একটি প্রশ্নে একত্রিত করবে না।

14. কোনো প্রশ্নের তথ্য না পাওয়া গেলে সংশ্লিষ্ট string খালি
অথবা list খালি রাখবে।

15. কোনো অতিরিক্ত প্রশ্ন তৈরি করবে না।

16. JSON ছাড়া অন্য কোনো লেখা, Markdown বা Code Fence দেবে না।

RAW TEXT:
{raw_text}
"""

    response = model.generate_content(prompt)

    if not response.text:
        raise ValueError("Gemini থেকে কোনো Response পাওয়া যায়নি।")

    text = response.text.strip()

    text = re.sub(
        r"```(?:json)?\s*(.*?)\s*```",
        r"\1",
        text,
        flags=re.DOTALL
    ).strip()

    return text


# ----------------------------
# Institution Matching
# ----------------------------
def match_institutions(institutions):

    matched_institutions = []

    for inst in institutions:

        inst = str(inst).strip()

        if not inst:
            continue

        best_match = process.extractOne(
            inst,
            choices,
            scorer=fuzz.WRatio
        )

        if best_match:

            matched_name, score, _ = best_match

            if score >= 85:

                eiin_code = name_to_eiin[matched_name]

                matched_institutions.append(
                    f"{inst} [{eiin_code}]"
                )

            else:

                matched_institutions.append(
                    f"{inst} [⚠️ কোড পাইনি]"
                )

        else:

            matched_institutions.append(
                f"{inst} [⚠️ কোড পাইনি]"
            )

    return matched_institutions


# ----------------------------
# Format MCQ
# ----------------------------
def format_mcq(item, q_no):

    question = clean_text(
        get_field(item, "question")
    )

    options = normalize_list(
        get_field(item, "options")
    )

    answer = clean_text(
        get_field(item, "answer")
    )

    years = normalize_list(
        get_field(item, "years", "year")
    )

    institutions = normalize_list(
        get_field(item, "institutions", "institution")
    )

    units = normalize_list(
        get_field(item, "units", "unit")
    )

    explanation = clean_text(
        get_field(item, "explanation", "ব্যাখ্যা")
    )

    subject = clean_text(
        get_field(item, "subject", "বিষয়")
    )

    chapter = clean_text(
        get_field(item, "chapter", "অধ্যায়")
    )

    topic = clean_text(
        get_field(item, "topic")
    )

    # ----------------------------
    # Format Options
    # ----------------------------
    option_labels = ["ক", "খ", "গ", "ঘ", "ঙ", "চ"]

    formatted_options = []

    for i, option in enumerate(options):

        option_text = str(option).strip()

        if i < len(option_labels):

            formatted_options.append(
                f"{option_labels[i]}. {option_text}"
            )

        else:

            formatted_options.append(option_text)

    options_text = "\n".join(formatted_options)

    # ----------------------------
    # Detect Answer Label
    # ----------------------------
    answer_text = answer

    if answer:

        # Check if answer is an option label
        answer_match = re.match(
            r"^\s*([কখগঘঙচ])(?:[.)\s]|$)",
            answer
        )

        if answer_match:

            label = answer_match.group(1)

            if label in option_labels:

                index = option_labels.index(label)

                if index < len(options):

                    answer_text = (
                        f"{label}. {options[index]}"
                    )

        else:

            # Check if answer matches option text
            for i, option in enumerate(options):

                if answer.strip().lower() == str(option).strip().lower():

                    if i < len(option_labels):

                        answer_text = (
                            f"{option_labels[i]}. {option}"
                        )

                    break

    # ----------------------------
    # Match Institutions
    # ----------------------------
    matched_institutions = match_institutions(
        institutions
    )

    # ----------------------------
    # Final Output
    # ----------------------------
    output_parts = []

    output_parts.append(
        f"প্রশ্ন {q_no}:\n\n{question}"
    )

    if options_text:
        output_parts.append(options_text)

    if answer_text:
        output_parts.append(
            f"উত্তর: {answer_text}"
        )

    # Institution
    if matched_institutions:
        output_parts.append(
            f"প্রতিষ্ঠান: {', '.join(matched_institutions)}"
        )

    # Unit
    if units:
        output_parts.append(
            f"ইউনিট: {', '.join(units)}"
        )

    # Years
    if years:
        output_parts.append(
            f"সাল: {', '.join(years)}"
        )

    # Subject
    if subject:
        output_parts.append(
            f"বিষয়: {subject}"
        )

    # Chapter
    if chapter:
        output_parts.append(
            f"অধ্যায়: {chapter}"
        )

    # Topic
    if topic:
        output_parts.append(
            f"টপিক: {topic}"
        )

    # Explanation
    if explanation:
        output_parts.append(
            f"ব্যাখ্যা: {explanation}"
        )

    return "\n".join(output_parts)


# ----------------------------
# UI Input
# ----------------------------
user_input = st.text_area(
    "আপনার MCQ গুলো এখানে পেস্ট করুন:",
    height=300,
    placeholder="এখানে প্রশ্ন, অপশন, উত্তর, বিশ্ববিদ্যালয়, ইউনিট, সাল ও ব্যাখ্যাসহ MCQ পেস্ট করুন..."
)


# ----------------------------
# Process Button
# ----------------------------
if st.button("✨ ম্যাজিক শুরু করুন", use_container_width=True):

    if not user_input.strip():

        st.warning("⚠️ অনুগ্রহ করে MCQ পেস্ট করুন!")
        st.stop()

    with st.spinner("AI ডেটা বিশ্লেষণ করছে..."):

        json_text = ""

        try:

            # Extract Data
            json_text = extract_mcq_with_gemini(
                user_input
            )

            structured_data = json.loads(
                json_text
            )

            if not isinstance(structured_data, list):
                raise ValueError(
                    "Gemini-এর Response JSON Array নয়।"
                )

            results = []

            # Format Each Question
            for q_no, item in enumerate(
                structured_data,
                start=1
            ):

                if not isinstance(item, dict):
                    continue

                output_block = format_mcq(
                    item,
                    q_no
                )

                results.append(output_block)

            if not results:
                raise ValueError(
                    "কোনো MCQ পাওয়া যায়নি।"
                )

            final_output = "\n\n".join(results)

            # Success
            st.success(
                f"✅ সফলভাবে {len(results)}টি প্রশ্ন প্রসেস হয়েছে!"
            )

            # Output
            st.code(
                final_output,
                language="text"
            )

            # Download
            st.download_button(
                label="📥 TXT ডাউনলোড",
                data=final_output,
                file_name="mcq_output.txt",
                mime="text/plain",
                use_container_width=True
            )

        except json.JSONDecodeError:

            st.error(
                "⚠️ Gemini থেকে বৈধ JSON পাওয়া যায়নি।"
            )

            with st.expander("Raw Response"):
                st.code(json_text)

        except Exception as e:

            st.error(
                f"⚠️ Error: {str(e)}"
            )
