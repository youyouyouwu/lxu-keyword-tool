import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
from prompts import SYSTEM_PROMPT, ANALYSIS_TASK

st.set_page_config(page_title="LxU 关键词提炼工具", layout="wide")
st.title("🔍 LxU 详情页关键词批量提炼工具")

# 1. 配置 API
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.warning("⚠️ 请在 Streamlit 云端后台配置你的 API Key")

# 2. 侧边栏
with st.sidebar:
    st.header("排队设置")
    wait_time = st.slider("每个文件处理间隔(秒)", 10, 60, 25)

# 3. 上传与处理
files = st.file_uploader("点击或拖入多个产品 PDF", type="pdf", accept_multiple_files=True)

if files and st.button("🚀 开始批量提炼"):
    model = genai.GenerativeModel(model_name="gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
    results = []
    bar = st.progress(0)
    
    for i, file in enumerate(files):
        bar.progress((i + 1) / len(files))
        st.write(f"正在处理：{file.name}...")
        
        # 存为临时文件并上传
        with open(f"temp_{file.name}", "wb") as f:
            f.write(file.getbuffer())
        
        try:
            gen_file = genai.upload_file(path=f"temp_{file.name}")
            response = model.generate_content([gen_file, ANALYSIS_TASK])
            results.append({"文件名": file.name, "提炼内容": response.text})
            # 实时显示结果
            st.markdown(response.text)
            if i < len(files) - 1:
                time.sleep(wait_time) # 关键排队逻辑
        except Exception as e:
            st.error(f"{file.name} 失败: {e}")

    # 4. 导出
    if results:
        df = pd.DataFrame(results)
        df.to_excel("LxU_Result.xlsx", index=False)
        with open("LxU_Result.xlsx", "rb") as f:
            st.download_button("📥 下载 Excel 结果", f, file_name="LxU_关键词提炼结果.xlsx")