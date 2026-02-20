import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os

# ==========================================
# 1. LxU 专属提炼指令 (已整合你的全套 7 大维度策略)
# ==========================================
SYSTEM_PROMPT = "你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。"

ANALYSIS_TASK = """
第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台以便让平台快速准确的为我的产品打上准确的标签匹配流量。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。在分析产品的同时也综合考虑推荐商品中类似产品的标题挖掘关键词（需要20个后台设置的关键词，不包含品牌词）
输出要求：
1.保留竖版序号排列外加策略解释的版本，含翻译文。
2.还需要输出一款逗号隔开的版本方便在coupang后台录入。

第二，我是一个精铺，推广侧率为前期少量进货快速付费推广测品的卖家。找精准长尾词做付费推广（需要精准流量词，按相关性排列并打分1-5）。
广告组一为【核心出单词】。
广告组二为【精准长尾关键词】（尽量挖掘30个左右，包含缩写如'스뎅'、语序颠倒、场景词、关联竞品如Daiso等）。
广告组三为【长尾捡漏组广告词】（低CPC、购买意向强、Low Traffic。包含错别字、缩写、方言等变体）。
输出格式：Excel表格形式【序号 | 韩文关键词 | 中文翻译 | 策略类型 | 预估流量(High/Medium/Low) | 相关性评分】。

第三，生成一个高点击率 (High CTR) 标题方案：公式 [品牌名] + [直击痛点形容词] + [核心差异化卖点] + [核心大词] + [核心属性/材质] + [场景/功能]。20个字以内，符合韩国人可读性。

第四，提供一个产品韩语名称用于内部管理。

第五，按照产品卖点撰写5条商品好评，语法自然、风格各异，本土化表达，表格形式排列。

第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出表格。

第七，AI 主图生成建议：基于场景词建议背景和构图，主图严禁带文字。

主要说明文字用中文，关键词用韩文。流量分布标准：High(10,000+), Medium(1,000-10,000), Low(<1,000)。
"""

# ==========================================
# 2. 页面配置与 Secrets 静默调用
# ==========================================
st.set_page_config(page_title="LxU 关键词提炼工具-极速版", layout="wide")
st.title("⚡ LxU 关键词提炼与广告策略工具 (2.5 Flash 极速版)")

# --- 核心：默认调用后台 Secrets 里的 Key ---
api_key = st.secrets.get("GEMINI_API_KEY", None)

if not api_key:
    st.error("⚠️ 未在后台检测到 GEMINI_API_KEY，请在 Settings -> Secrets 配置。")
    st.stop()

# 配置 API 
genai.configure(api_key=api_key)

# ==========================================
# 3. 运行界面
# ==========================================
with st.sidebar:
    st.header("⚙️ 引擎状态")
    st.success("✅ 已通过 Secrets 加密连接")
    st.info("当前引擎：Gemini 2.5 Flash (高并发不限流)")
    st.markdown("---")
    wait_time = st.slider("处理间隔(秒)", 5, 60, 15)
    st.write("提示：Flash 引擎速度极快，处理大文件间隔可缩短至 15s。")

# 文件上传
files = st.file_uploader("上传 PDF 或详情页长图", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

if files and st.button("🚀 开始批量深度提炼"):
    # 彻底解决 429 报错！调用免费额度极高、速度极快的 2.5 Flash 模型
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash", 
            system_instruction=SYSTEM_PROMPT
        )
        
        results = []
        bar = st.progress(0)
        
        for i, file in enumerate(files):
            bar.progress((i + 1) / len(files))
            st.subheader(f"📊 正在极速解析：{file.name}")
            
            temp_name = f"temp_{file.name}"
            with open(temp_name, "wb") as f:
                f.write(file.getbuffer())
            
            try:
                with st.spinner('⚡ Flash 引擎正在飞速扫描长图，请稍候...'):
                    # 针对大文件的上传处理
                    gen_file = genai.upload_file(path=temp_name)
                    
                    # 轮询检查大文件是否在 Google 服务器端准备完毕
                    while gen_file.state.name == "PROCESSING":
                        time.sleep(2)
                        gen_file = genai.get_file(gen_file.name)
                    
                    # 生成核心内容
                    response = model.generate_content([gen_file, ANALYSIS_TASK])
                
                # 直接展示深度分析结果
                st.markdown(response.text)
                results.append({"文件名": file.name, "分析结果": response.text})
                
                # 间隔排队逻辑
                if i < len(files) - 1:
                    time.sleep(wait_time)
                    
            except Exception as e:
                st.error(f"处理 {file.name} 出错: {str(e)}")
            finally:
                if os.path.exists(temp_name):
                    os.remove(temp_name)

        if results:
            st.success("✅ 所有产品提炼完成！")
            df = pd.DataFrame(results)
            df.to_excel("LxU_Flash_Results.xlsx", index=False)
            with open("LxU_Flash_Results.xlsx", "rb") as f:
                st.download_button("📥 导出全量 Excel 报告", f, file_name="LxU_Flash分析结果汇总.xlsx")
    except Exception as e:
        st.error(f"模型初始化失败: {e}")
