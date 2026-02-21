import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os
import re
import requests
import hashlib
import hmac
import base64

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品工作流 (终极中文版)", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 缺少 API 密钥！请确保 Secrets 中配置了所有必需的 Key。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 1. 核心指令与函数定义
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。注意：你的整个运营团队都在中国，所以你必须遵守以下极其严格的【语言输出隔离规范】：
1. 所有的“分析过程”、“策略解释”、“使用原因”、“主图建议”等任何沟通描述性质的文字，必须 100% 使用【简体中文】！绝对禁止使用韩文解释！
2. 只有“韩文关键词本身”、“韩语标题”和“商品好评的韩文原文”这三个部分允许出现韩文，且必须全部附带对应的【中文翻译】。

--- 核心任务 ---
第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。综合考虑推荐商品中类似产品的标题挖掘关键词（需要20个后台设置的关键词，不包含品牌词）。
输出要求：
1.保留竖版序号排列，必须外加纯中文的策略解释的版本，并含中文翻译。
2.还需要输出一款纯韩文逗号隔开的版本方便在coupang后台录入。

第二，找精准长尾词做付费推广（需要精准流量词，按相关性排列并打分1-5）。
广告组一为【核心出单词】。
广告组二为【精准长尾关键词】（尽量挖掘30个左右，包含缩写、语序颠倒、场景词、关联竞品等）。
广告组三为【长尾捡漏组广告词】（低CPC、购买意向强、Low Traffic。包含错别字、缩写、方言等变体）。
输出格式：Excel表格形式【序号 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量(High/Medium/Low) | 相关性评分】。

第三，生成一个高点击率 (High CTR) 韩文标题方案：公式 [品牌名] + [直击痛点形容词] + [核心差异化卖点] + [核心大词] + [核心属性/材质] + [场景/功能]。20个字以内，符合韩国人可读性（需附带中文翻译）。

第四，提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五，按照产品卖点撰写5条商品韩文好评，语法自然，表格形式排列（表格必须包含：韩文评价原文、纯中文翻译、纯中文的买家痛点分析）。

第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出表格。

第七，AI 主图生成建议：基于场景词用纯中文建议背景和构图，主图严禁带文字。

【程序读取专属指令 - 极度重要】：
为了方便我的系统自动抓取，请务必将“第六部分”的最终去重汇总关键词，放在以下两个标记之间输出！每行只写一个韩文关键词，尽量不要带中文或序号。
[LXU_KEYWORDS_START]
(在这里填入纯韩文关键词)
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC挖掘以及“精铺快速测品”的高 ROAS 广告策略。整个团队都在中国，所以除韩文关键词外，所有解释分析必须用纯中文输出。

**核心任务：**
基于产品详情页原图及以下 Naver 关键词真实搜索量数据（CSV格式），输出精准广告分组、否定词表。不要含有 LxU 的品牌词。

【市场数据】：
{market_data}

第一步：全维度分析 (视觉属性识别、痛点挖掘、排除逻辑) - 必须纯中文。
第二步：关键词清洗与打分 (结合流量与痛点保留核心词和捡漏词，剔除宽泛词)。
第三步：输出二大模块
模块一：付费广告投放策略表 (Markdown表格，分核心出单词、精准长尾词、捡漏与痛点组，按总搜索量降序，带序号。需包含韩文词、中文翻译和预估流量策略)。
模块二：否定关键词列表 (纯中文简述屏蔽的原因，并列出建议屏蔽的韩文词)。
"""

def clean_for_api(keyword: str) -> str:
    return re.sub(r"\s+", "", keyword)

def make_signature(method: str, uri: str, timestamp: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signature = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")

def normalize_count(raw):
    if isinstance(raw, int): return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("<"): return 5
        if s.startswith(">"):
            num = s[1:].strip()
            return int(num) if num.isdigit() else 0
        s = s.replace(",", "")
        if s.isdigit(): return int(s)
    return 0

def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    total = len(main_keywords)
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 查询中 [{i}/{total}]: {mk}")
        pb.progress(i / total)
        try:
            timestamp = str(int(time.time() * 1000))
            sig = make_signature("GET", "/keywordstool", timestamp)
            headers = {"X-Timestamp": timestamp, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": clean_for_api(mk), "showDetail": 1})
            if res.status_code == 200:
                data = res.json()
                for item in data.get("keywordList", [])[:8]: 
                    pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                    mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                    all_rows.append({"提取主词": mk, "Naver扩展词": item.get("relKeyword", ""), "总搜索量": pc + mob, "竞争度": item.get("compIdx", "-")})
        except Exception:
            pass
        time.sleep(1)
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver扩展词"]).sort_values(by="总搜索量", ascending=False)
    return df

# ==========================================
# 2. 状态保持 (Session State)
# ==========================================
if "kw_text" not in st.session_state: st.session_state.kw_text = ""
if "df_market" not in st.session_state: st.session_state.df_market = pd.DataFrame()
if "gemini_file_name" not in st.session_state: st.session_state.gemini_file_name = ""

# ==========================================
# 3. 界面布局
# ==========================================
st.title("🛡️ LxU 测品工作流 (三步控制版)")
file = st.file_uploader("📥 全局唯一入口：请先上传 PDF 详情页", type=["pdf", "png", "jpg"])

tab1, tab2, tab3 = st.tabs(["📌 第一步：AI提词", "📈 第二步：搜量回测", "🧠 第三步：终极策略"])

# ----------------- 标签页 1 -----------------
with tab1:
    st.header("1️⃣ 提取初筛关键词")
    if file and st.button("🚀 执行第一步：AI 视觉提炼"):
        model = genai.GenerativeModel("gemini-2.5-flash")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        with st.spinner("Gemini 正在看图写报告..."):
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING": time.sleep(2)
            st.session_state.gemini_file_name = gen_file.name 
            
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            with st.expander("查看 AI 完整原始报告 (纯中文说明)", expanded=False):
                st.write(res1.text)
                
            match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
            kw_list = []
            if match:
                raw_block = match.group(1)
                raw_block = re.sub(r'[,，]', '\n', raw_block)
                for line in raw_block.split('\n'):
                    clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                    clean_word = re.sub(r'\s+', ' ', clean_word)
                    if clean_word and clean_word not in kw_list:
                        kw_list.append(clean_word)
            else:
                tail_text = res1.text[-800:]
                for line in tail_text.split('\n'):
                    clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                    clean_word = re.sub(r'\s+', ' ', clean_word)
                    if clean_word and clean_word not in kw_list:
                        kw_list.append(clean_word)
                kw_list = kw_list[:25]
            
            st.session_state.kw_text = "\n".join(kw_list)
            st.success("✅ 提取完成！请核对下方文本框里的词，确认无误后，点击网页最上方的【📈 第二步：搜量回测】标签页。")
            os.remove(temp_path)

    user_edited_kws = st.text_area("✍️ 即将传给 Naver 的纯韩文关键词 (可手动删改)：", value=st.session_state.kw_text, height=300, key="kw_input_area")

# ----------------- 标签页 2 -----------------
with tab2:
    st.header("2️⃣ 获取 Naver 真实数据")
    st.info("💡 提示：这里会直接读取你在第一步确认好的纯韩文关键词。")
    if st.button("📊 执行第二步：开始查询"):
        final_kw_list = [kw.strip() for kw in st.session_state.kw_input_area.split("\n") if kw.strip()]
        if not final_kw_list:
            st.warning("⚠️ 关键词列表为空，请先回到第一步提取关键词！")
        else:
            pb = st.progress(0)
            st_text = st.empty()
            df = fetch_naver_data(final_kw_list, pb, st_text)
            if not df.empty:
                st.session_state.df_market = df
                st.success("✅ Naver 数据查询成功！请点击网页最上方的【🧠 第三步：终极策略】标签页。")
                st.dataframe(df)
            else:
                st.error("❌ 查询失败，Naver 未返回有效数据。")

# ----------------- 标签页 3 -----------------
with tab3:
    st.header("3️⃣ 生成终极广告策略")
    if st.button("🧠 执行第三步：AI 排兵布阵"):
        if st.session_state.df_market.empty:
            st.warning("⚠️ 缺少 Naver 数据，请先执行第二步！")
        elif not st.session_state.gemini_file_name:
            st.warning("⚠️ 缺少源文件句柄，请重新从第一步开始！")
        else:
            with st.spinner("AI 大脑正在融合客观数据进行深度推演..."):
                model = genai.GenerativeModel("gemini-2.5-flash")
                try:
                    gen_file = genai.get_file(st.session_state.gemini_file_name)
                    market_csv = st.session_state.df_market.to_csv(index=False)
                    final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                    
                    res3 = model.generate_content([gen_file, final_prompt])
                    st.success("✅ 终极策略生成完毕！")
                    st.markdown(res3.text)
                    st.download_button("📥 导出终极策略 (TXT)", data=res3.text, file_name="LxU_终极策略.txt")
                except Exception as e:
                    st.error(f"处理失败，可能是云端文件已过期，请重新上传。错误信息：{e}")
