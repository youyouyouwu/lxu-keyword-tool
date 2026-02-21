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
st.set_page_config(page_title="LxU 测品工作流 (终极稳健版)", layout="wide")

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
# 1. 核心指令 (第一步强制表格输出)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。注意：你的整个运营团队都在中国，所以你必须遵守以下极其严格的【语言输出隔离规范】：
1. 所有的“分析过程”、“策略解释”、“使用原因”、“主图建议”等任何沟通描述性质的文字，必须 100% 使用【简体中文】！绝对禁止使用韩文解释！
2. 只有“韩文关键词本身”、“韩语标题”和“商品好评的韩文原文”这三个部分允许出现韩文，且必须全部附带对应的【中文翻译】。

--- 核心任务 ---
第一，找出20个产品关键词。
【强制输出格式】：
1. 必须将这20个关键词以 Markdown 表格形式输出！
表格骨架严格如下：
| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
|---|---|---|---|
| 1 | ... | ... | ... |
2. 在表格下方，单独输出一款纯韩文、逗号隔开的版本。

第二，输出广告分组（核心/精准长尾/捡漏）。
输出格式：Markdown 表格形式，表头：【序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量 | 相关性评分】。

第三至第七部分（标题、内部名称、好评表、汇总表、主图建议）均按要求执行，所有解释文字必须纯中文。

【程序读取专属指令】：
将“第六部分”去重汇总关键词放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间，每行一个。
"""

PROMPT_STEP_3 = """
你是一位韩国 Coupang 跨境电商运营专家。除韩语关键词外，所有分析用纯中文。
基于以下 Naver 数据输出终极策略：
{market_data}

第一步：全维度分析 (视觉/痛点) - 纯中文。
第二步：输出统一的付费广告投放策略表格。
表头：| 序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 月总搜索量 | 竞争度 | 推荐策略与说明 |
第三步：否定关键词列表 (纯中文简述理由)。
"""

# ==========================================
# 2. Naver 数据抓取函数
# ==========================================
def clean_for_api(keyword: str) -> str:
    return re.sub(r"\s+", "", keyword)

def make_signature(method: str, uri: str, timestamp: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signature = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")

def normalize_count(raw):
    if isinstance(raw, int): return raw
    if isinstance(raw, str):
        s = raw.strip().replace(",", "")
        if s.startswith("<"): return 5
        return int(s) if s.isdigit() else 0
    return 0

def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    total = len(main_keywords)
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 查询中 [{i}/{total}]: {mk}")
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
                    all_rows.append({
                        "Naver实际搜索词": item.get("relKeyword", ""),
                        "月总搜索量": pc + mob,
                        "竞争度": item.get("compIdx", "-"),
                        "AI溯源(原词)": mk
                    })
        except Exception: pass
        time.sleep(1)
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False) if not df.empty else df

# ==========================================
# 3. 主工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂")

files = st.file_uploader("📥 上传产品详情页", type=["pdf", "png", "jpg"], accept_multiple_files=True)

if files and st.button("🚀 启动全自动闭环"):
    # 建议使用兼容性最好的 1.5-flash
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    for file in files:
        st.divider()
        st.header(f"📦 处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        with st.status("🔍 第一步：AI 识图与表格提词...", expanded=True) as s1:
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING": time.sleep(2); gen_file = genai.get_file(gen_file.name)
                
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            with st.expander("查看第一步报告", expanded=False): st.write(res1.text)
                
            match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
            kw_list = []
            if match:
                raw_block = match.group(1)
                for line in re.sub(r'[,，]', '\n', raw_block).split('\n'):
                    clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                    if clean_word: kw_list.append(re.sub(r'\s+', ' ', clean_word))
            
            if kw_list: s1.update(label=f"✅ 第一步完成", state="complete")
            else: s1.update(label="❌ 提取失败", state="error"); continue

        with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
            pb = st.progress(0); txt = st.empty()
            df_market = fetch_naver_data(kw_list, pb, txt)
            if not df_market.empty:
                st.dataframe(df_market)
                s2.update(label=f"✅ 第二步完成 (目标：{len(kw_list)} ➡️ 衍生：{len(df_market)})", state="complete")
            else: s2.update(label="❌ 第二步无数据", state="error"); continue 

        with st.status("🧠 第三步：生成终极策略...", expanded=True) as s3:
            res3 = model.generate_content([gen_file, PROMPT_STEP_3.format(market_data=df_market.to_csv(index=False))])
            st.markdown("### 🏆 LxU 终极测品策略报告")
            st.success(res3.text)
            s3.update(label="✅ 第三步完成", state="complete")

        os.remove(temp_path)
        try: genai.delete_file(gen_file.name)
        except: pass
