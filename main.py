import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os

# ==========================================
# 1. 指令配置区 (原 prompts.py 内容已合并至此)
# ==========================================
SYSTEM_PROMPT = "你是一个精通韩国电商（Coupang、Naver）的SEO专家，擅长从图片和PDF详情页中提炼高转化的核心关键词。"

ANALYSIS_TASK = """请深度扫描这个产品详情页，并完成以下提炼任务：
1. 核心关键词：提取5个最精准的行业大词。
2. 属性关键词：提取产品的材质、规格、功能相关词。
3. 韩文蓝海词建议：给出5个适合在Naver/Coupang搜索的韩文长尾词。
请直接以结构化表格形式输出，不要有任何开场白。"""

# ==========================================
# 2. 页面设置与逻辑
# ==========================================
st.set_page_config(page_title="LxU 关键词提炼工具", layout="wide")
st.title("🔍 LxU 详情页关键词批量提炼工具")

# 配置 API (从 Streamlit Secrets 读取)
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.warning("⚠️ 请在 Streamlit 云端后台配置你的 API Key (Settings -> Secrets)")

# 侧边栏
with st.sidebar:
    st.header("排队设置")
    wait_time = st.slider("每个文件处理间隔(秒)", 10, 60, 25)
    st.info("免费版 API 建议间隔 25 秒左右。")

# 文件上传
files = st.file_uploader("点击或拖入多个产品 PDF", type="pdf", accept_multiple_files=True)

if files and st.button("🚀 开始批量提炼"):
    # 初始化模型
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro", 
        system_instruction=SYSTEM_PROMPT
    )
    
    results = []
    bar = st.progress(0)
    status_text = st.empty()
    
    for i, file in enumerate(files):
        # 更新进度条
        progress_val = (i + 1) / len(files)
        bar.progress(progress_val)
        status_text.write(f"⏳ 正在处理第 {i+1}/{len(files)} 个：{file.name}...")
        
        # 存为临时文件
        temp_filename = f"temp_{file.name}"
        with open(temp_filename, "wb") as f:
            f.write(file.getbuffer())
        
        try:
            # 上传至 Gemini 临时存储
            gen_file = genai.upload_file(path=temp_filename)
            
            # 生成内容
            response = model.generate_content([gen_file, ANALYSIS_TASK])
            
            # 记录结果
            results.append({"文件名": file.name, "提炼内容": response.text})
            
            # 实时显示在网页上
            with st.expander(f"📄 {file.name} 的提炼结果", expanded=True):
                st.markdown(response.text)
            
            # 清理临时文件
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                
            # 排队等待逻辑 (最后一个文件不需要等)
            if i < len(files) - 1:
                time.sleep(wait_time)
                
        except Exception as e:
            st.error(f"❌ {file.name} 处理失败: {str(e)}")

    # 4. 导出 Excel
    if results:
        st.success("✅ 批量提炼完成！")
        df = pd.DataFrame(results)
        output_file = "LxU_Keyword_Results.xlsx"
        df.to_excel(output_file, index=False)
        
        with open(output_file, "rb") as f:
            st.download_button(
                label="📥 下载所有关键词分析结果 (Excel)",
                data=f,
                file_name="LxU_关键词提炼汇总.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
