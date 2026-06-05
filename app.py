import streamlit as st
import pandas as pd
import google.generativeai as genai
from rapidfuzz import process, fuzz # thefuzz এর বদলে অনেক দ্রুত rapidfuzz
import json
import ast
import re
import typing_extensions as typing

st.set_page_config(page_title="Pro MCQ & EIIN Matcher", page_icon="⚡", layout="centered")

st.title("⚡ Pro MCQ & Board/College Code Matcher")
st.markdown("একাধিক সাল, বোর্ড এবং কলেজের নামসহ MCQ পেস্ট করুন।")

# সাইডবারে API Key
api_key = st.sidebar.text_input("আপনার Gemini API Key দিন:", type="password")

@st.cache_data
def load_data():
    df = pd.read_csv('institutions_rows.csv')
    name_to_eiin = {}
    
    # Performance Improvement: iterrows() এর বদলে itertuples()
    for row in df.itertuples(index=False):
        code = ""
        
        # Logic Fix: NaN হ্যান্ডলিং
        if pd.notna(row.code) and str(row.code).strip() and str(row.code).lower() != 'nan':
            code = str(row.code).strip()
        elif pd.notna(row.eiin) and str(row.eiin).strip() and str(row.eiin).lower() != 'nan':
            code = str(row.eiin).strip()
            
        if not code:
            continue
            
        if pd.notna(row.name_en): name_to_eiin[str(row.name_en)] = code
        if pd.notna(row.name_bn): name_to_eiin[str(row.name_bn)] = code
        if pd.notna(row.short_name): name_to_eiin[str(row.short_name)] = code
        
        # Security Fix: eval() এর বদলে ast.literal_eval()
        if pd.notna(row.aliases) and str(row.aliases).strip():
            aliases_str = str(row.aliases)
            try:
                if '[' in aliases_str:
                    aliases = ast.literal_eval(aliases_str)
                    if isinstance(aliases, list):
                        for alias in aliases:
                            name_to_eiin[str(alias)] = code
                else:
                    name_to_eiin[aliases_str] = code
            except (ValueError, SyntaxError):
                pass
                
    return name_to_eiin

name_to_eiin = load_data()

# Schema Definition: Gemini কে নির্দিষ্ট স্ট্রাকচার ফলো করতে বাধ্য করা
class MCQItem(typing.TypedDict):
    question: str
    options: list[str]
    answer: str
    years: list[str]
    institutions: list[str]

def extract_mcq_with_gemini(raw_text, key):
    # API Configure Fix: ফাংশন কলের সময় একবারই কনফিগার হবে
    genai.configure(api_key=key)
    
    model = genai.GenerativeModel(
        'gemini-1.5-flash',
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": list[MCQItem] # Schema enforced
        }
    )
    
    # Prompt Injection Fix: শক্ত প্রম্পট
    prompt = f"""
    তুমি একজন ডাটা এক্সট্রাক্টর। তুমি শুধুমাত্র JSON ফেরত দিবে। কোনো অতিরিক্ত ব্যাখ্যা, ভূমিকা বা উপসংহার দিবে না।
    নিচের টেক্সট থেকে প্রতিটি বহুনির্বাচনী প্রশ্ন (MCQ), তার অপশনসমূহ, উত্তর, উল্লেখিত সাল এবং বোর্ড/কলেজের নাম আলাদা করো।
    
    RAW TEXT:
    {raw_text}
    """
    
    response = model.generate_content(prompt)
    
    # JSON Reliability Fix: মার্কডাউন ব্লক ক্লিন করা
    clean_json = re.sub(r'```(?:json)?\n?(.*?)\n?
```', r'\1', response.text, flags=re.DOTALL).strip()
    return clean_json

user_input = st.text_area(
    "আপনার MCQ গুলো এখানে পেস্ট করুন:", 
    height=250
)

if st.button("✨ ম্যাজিক শুরু করুন"):
    if not api_key:
        st.error("⚠️ প্রথমে সাইডবারে আপনার Gemini API Key দিন!")
    elif not user_input:
        st.warning("অনুগ্রহ করে বক্সে কিছু লিখুন!")
    else:
        with st.spinner('এআই ডেটা অ্যানালাইজ করছে এবং RapidFuzz কোড খুঁজছে...'):
            try:
                json_data = extract_mcq_with_gemini(user_input, api_key)
                structured_data = json.loads(json_data)
                
                results = []
                
                for item in structured_data:
                    question = item.get("question", "")
                    options = "\n".join(item.get("options", []))
                    answer = item.get("answer", "")
                    years = item.get("years", [])
                    institutions = item.get("institutions", [])
                    
                    years_str = ", ".join(years)
                    matched_institutions = []
                    
                    for inst in institutions:
                        # Performance Improvement: rapidfuzz ব্যবহার
                        # Dictionary keys গুলোকে লিস্টে কনভার্ট করে rapidfuzz এ পাস করা হচ্ছে
                        choices = list(name_to_eiin.keys())
                        best_match = process.extractOne(inst, choices, scorer=fuzz.WRatio)
                        
                        if best_match:
                            match_str, score, _ = best_match
                            # Match Threshold Fix: 75 থেকে বাড়িয়ে 85 করা হয়েছে
                            if score >= 85: 
                                eiin_code = name_to_eiin[match_str]
                                matched_institutions.append(f"{inst} [{eiin_code}]")
                            else:
                                matched_institutions.append(f"{inst} [⚠️ কোড পাইনি]")
                        else:
                            matched_institutions.append(f"{inst} [⚠️ কোড পাইনি]")
                            
                    inst_str = ", ".join(matched_institutions) if matched_institutions else "কোনো বোর্ড/কলেজ নেই"
                    
                    final_block = f"{question}\n{options}\n{answer}\n * **বোর্ড ও সাল:** {inst_str} ({years_str})"
                    results.append(final_block)
                            
                st.success("✅ প্রসেস সফলভাবে সম্পন্ন হয়েছে!")
                final_output = "\n\n".join(results)
                st.text_area("ফলাফল (কপি করার জন্য):", value=final_output, height=400)
                
            except json.JSONDecodeError:
                st.error("⚠️ AI থেকে সঠিক JSON পাওয়া যায়নি। অনুগ্রহ করে আবার চেষ্টা করুন।")
            except Exception as e:
                st.error(f"⚠️ একটি অপ্রত্যাশিত সমস্যা হয়েছে: {e}")
