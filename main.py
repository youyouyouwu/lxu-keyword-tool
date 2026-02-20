import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os

# ==========================================
# 1. 提炼指令配置 (合并自 prompts.py)
# ==========================================
SYSTEM_PROMPT = "你是一个精通韩国电商（Coupang、Naver）的SEO专家，擅长从图片和PDF详情页中提炼高转化的核心关键词。"

ANALYSIS_TASK = """请深度扫描这个产品详情页，并完成以下提炼任务：
1. 核心关键词：提取5个最精准的行业大词。
2. 属性关键词：提取产品的材质、规格、功能相关词。
3. 韩文蓝海词建议：给出5个适合在Naver/Coupang搜索的韩文长尾词。
请直接以结构化表格形式输出，不要有任何开场白。"""

# ==========================================
# 2. 页面布局
# ==========================================
st.set_page_config(page_title="LxU 关键词提炼工具", layout="wide")
st.title("🔍 LxU 详情页关键词批量提炼工具")

# --- 侧边栏：API Key 输入 ---
with st.sidebar:
    st.header("🔑 密钥配置")
    # type="password" 会隐藏输入的字符，更安全
    input_key = st.text_input("在此输入 Gemini API Key", type="password")
    
    # 确定要使用的 Key
    api_key_to_use = input_key if input_key else st.secrets.get("GEMINI_API_KEY", None)
    
    if not api_key_to_use:
        st.warning("👈 请先在左侧输入 API Key")
    
    st.markdown("---")
    st.header("排队设置")
    wait_time = st.slider("每个文件处理间隔(秒)", 10, 60, 25)

# ==========================================
# 3. 核心业务逻辑
# ==========================================
if api_key_to_use:
    genai.configure(api_key=api_key_to_use)
    
    files = st.file_uploader("上传 PDF 详情页", type="pdf", accept_multiple_files=True)

    if files and st.button("🚀 开始批量提炼"):
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro", 
            system_instruction=SYSTEM_PROMPT
        )
        
        results = []
        bar = st.progress(0)
        
        for i, file in enumerate(files):
            bar.progress((i + 1) / len(files))
            st.write(f"⏳ 正在提炼：{file.name}...")
            
            # 创建临时文件
            temp_name = f"temp_{file.name}"
            with open(temp_name, "wb") as f:
                f.write(file.getbuffer())
            
            try:
                # 调用 API
                gen_file = genai.upload_file(path=temp_name)
                response = model.generate_content([gen_file, ANALYSIS_TASK])
                
                # 记录结果
                results.append({"文件名": file.name, "提炼内容": response.text})
                
                # 页面实时展示
                with st.expander(f"✅ {file.name} 结果", expanded=True):
                    st.markdown(response.text)
                
                # 间隔排队逻辑
                if i < len(files) - 1:
                    time.sleep(wait_time)
            except Exception as e:
                st.error(f"❌ {file.name} 出错: {e}")
            finally:
                if os.path.exists(temp_name):
                    os.remove(temp_name)

        # 导出 Excel
        if results:
            df = pd.DataFrame(results)
            df.to_excel("LxU_Results.xlsx", index=False)
            with open("LxU_Results.xlsx", "rb") as f:
                st.download_button("📥 下载关键词汇总 (Excel)", f, file_name="LxU_提炼结果.xlsx")
