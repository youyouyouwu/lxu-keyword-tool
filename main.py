import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os

# ==========================================
# 1. 究极进化版 Prompt (注入你的 LxU 运营策略)
# ==========================================
SYSTEM_PROMPT = """你是一个深耕韩国 Coupang 平台的跨境电商 SEO 与广告投放专家。
你非常熟悉韩国人的本土搜索习惯、口语缩写及购物痛点。
你的目标是基于用户上传的 PDF 详情页，提炼出精准的标签词、广告词及标题方案。"""

# 将你的详细需求封装进任务指令
ANALYSIS_TASK = """
我是一个做 Coupang 精铺的中国卖家，品牌名为 LxU。请深度解析此详情页并执行以下任务：

【任务一：20个后台标签词】
- 找20个符合本土搜索习惯的韩文词（不含品牌名）。
- 输出：序号 | 韩文 | 中文翻译 | 策略解释。
- 额外：输出一个逗号隔开的版本。

【任务二：付费推广三部曲（含相关性评分 1-5）】
- 广告组一：核心出单词。
- 广告组二：精准长尾词（约30个，覆盖流量入口，按相关性排列）。
- 广告组三：长尾捡漏组（利用错别字、缩写如'스뎅'、语序颠倒、特定场景如'懒人神器'、关联词如'Daiso'）。
- 输出：Excel表格形式【序号 | 韩文关键词 | 中文翻译 | 策略类型 | 预估流量(High/Medium/Low) | 相关性评分】。

【任务三：High CTR 标题方案】
- 公式：[品牌名] + [痛点形容词] + [差异化卖点] + [核心大词] + [属性/材质] + [场景/功能]。
- 要求：20字以内，不含括号，前15个字符决胜负。中性风格。

【任务四：内部管理韩语名】
- 给出一个简洁的产品韩文名称。

【任务五：5条本土化好评】
- 5种不同语气，长短错落，合理断句，不带表情。表格输出。

【任务六：汇总去重】
- 将三个广告组词汇去重，单列纵向列表输出表格。

【任务七：AI 主图策略】
- 基于场景词建议背景和构图，强调卖点，主图不含文字。

请使用中文回答主要说明文字，关键词保持韩文。
"""

# ==========================================
# 2. 页面布局与逻辑
# ==========================================
st.set_page_config(page_title="LxU 关键词提炼工具-专业版", layout="wide")
st.title("🛡️ LxU 关键词提炼与广告策略工具")

with st.sidebar:
    st.header("🔑 密钥配置")
    input_key = st.text_input("在此输入 Gemini API Key", type="password")
    api_key_to_use = input_key if input_key else st.secrets.get("GEMINI_API_KEY", None)
    
    st.markdown("---")
    st.header("⏳ 排队设置")
    wait_time = st.slider("处理间隔(秒)", 10, 60, 25)

if api_key_to_use:
    genai.configure(api_key=api_key_to_use)
    files = st.file_uploader("上传详情页 PDF 或长图", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

    if files and st.button("🚀 开始深度提炼"):
        model = genai.GenerativeModel(model_name="gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
        
        for i, file in enumerate(files):
            st.subheader(f"📊 处理中：{file.name}")
            temp_name = f"temp_{file.name}"
            with open(temp_name, "wb") as f:
                f.write(file.getbuffer())
            
            try:
                gen_file = genai.upload_file(path=temp_name)
                # 使用你的完整 Prompt 进行提问
                response = model.generate_content([gen_file, ANALYSIS_TASK])
                
                # 直接展示深度分析结果
                st.markdown(response.text)
                
                if i < len(files) - 1:
                    time.sleep(wait_time)
            except Exception as e:
                st.error(f"出错: {e}")
            finally:
                if os.path.exists(temp_name):
                    os.remove(temp_name)
else:
    st.info("👈 请先在左侧菜单栏输入你的 API Key。")
