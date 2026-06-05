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

st.title("⚡ Pro MCQ & Board/College Code Matcher")
st.markdown("একাধিক সাল, বোর্ড এবং কলেজের নামসহ MCQ পেস্ট করুন।")

# ----------------------------
# Load Gemini API Key from Secrets
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

        if hasattr(row, "name_en") and pd.notna(row.name_en):
            name_to_eiin[str(row.name_en).strip()] = code

        if hasattr(row, "name_bn") and pd.notna(row.name_bn):
            name_to_eiin[str(row.name_bn).strip()] = code

        if hasattr(row, "short_name") and pd.notna(row.short_name):
            name_to_eiin[str(row.short_name).strip()] = code

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

# RapidFuzz choices cache
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


# ----------------------------
# Gemini Extraction
# ----------------------------
def extract_mcq_with_gemini(raw_text):
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        "gemini-2.5-flash"
    )

    prompt = f"""
তুমি একজন ডাটা এক্সট্রাক্টর।

শুধুমাত্র JSON Array রিটার্ন করবে।

প্রতিটি অবজেক্টে থাকবে:

- question
- options
- answer
- years
- institutions

যদি কোনো তথ্য না পাও তাহলে খালি list বা খালি string ব্যবহার করবে।

JSON ছাড়া অন্য কিছু লিখবে না।

RAW TEXT:
{raw_text}
"""

    response = model.generate_content(prompt)

    text = response.text.strip()

    text = re.sub(
        r"```(?:json)?\s*(.*?)\s*```",
        r"\1",
        text,
        flags=re.DOTALL
    ).strip()

    return text


# ----------------------------
# UI Input
# ----------------------------
user_input = st.text_area(
    "আপনার MCQ গুলো এখানে পেস্ট করুন:",
    height=250
)

# ----------------------------
# Process Button
# ----------------------------
if st.button("✨ ম্যাজিক শুরু করুন"):

    if not user_input.strip():
        st.warning("⚠️ অনুগ্রহ করে MCQ পেস্ট করুন!")
        st.stop()

    with st.spinner("AI ডেটা বিশ্লেষণ করছে..."):

        try:
            json_text = extract_mcq_with_gemini(user_input)

            structured_data = json.loads(json_text)

            results = []

option_labels = ["ক", "খ", "গ", "ঘ", "ঙ", "চ"]

for q_no, item in enumerate(structured_data, start=1):

    question = item.get("question", "").strip()

    options = item.get("options", [])
    answer = item.get("answer", "").strip()

    years = item.get("years", [])
    institutions = item.get("institutions", [])

    # ----------------------------
    # Format Options
    # ----------------------------
    formatted_options = []

    for i, option in enumerate(options):
        if i < len(option_labels):
            formatted_options.append(
                f"{option_labels[i]}. {option}"
            )
        else:
            formatted_options.append(option)

    options_text = "\n".join(formatted_options)

    # ----------------------------
    # Detect Answer Label
    # ----------------------------
    answer_text = answer
    answer_label = ""

    for i, option in enumerate(options):
        if answer.strip().lower() == option.strip().lower():
            if i < len(option_labels):
                answer_label = option_labels[i]
            break

    if answer_label:
        answer_text = f"{answer_label}. {answer}"

    # ----------------------------
    # Match Institutions
    # ----------------------------
    matched_institutions = []

    for inst in institutions:

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

    years_text = ", ".join(years)

    institutions_text = (
        ", ".join(matched_institutions)
        if matched_institutions
        else "কোনো বোর্ড/কলেজ নেই"
    )

    # ----------------------------
    # Final Output
    # ----------------------------
    output_block = (
        f"প্রশ্ন {q_no}:\n"
        f"{question}\n\n"
        f"{options_text}\n\n"
        f"উত্তর: {answer_text}\n"
        f"বোর্ড ও সাল: {institutions_text} ({years_text})"
    )

    results.append(output_block)

            final_output = "\n\n".join(results)

            st.success("✅ সফলভাবে প্রসেস সম্পন্ন হয়েছে!")

            st.text_area(
                "ফলাফল (কপি করার জন্য):",
                value=final_output,
                height=450
            )

            st.download_button(
                "📥 TXT ডাউনলোড",
                final_output,
                file_name="mcq_output.txt",
                mime="text/plain"
            )

        except json.JSONDecodeError:
            st.error("⚠️ Gemini থেকে বৈধ JSON পাওয়া যায়নি।")

            with st.expander("Raw Response"):
                st.code(json_text)

        except Exception as e:
            st.error(f"⚠️ Error: {str(e)}")
