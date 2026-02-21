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
st.set_page_config(page_title="LxU 测品工作流 (分步控制版)", layout="wide")

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
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。
第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台以便让平台快速准确的为我的产品打上准确的标签匹配流量。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。在分析产品的同时也综合考虑推荐商品中类似产品的标题挖掘关键词（需要20个后台设置的关键词，不包含品牌词）
输出要求：
1.保留竖版序号排列外加策略解释的版本，含翻译文。
2.还需要输出一款逗号隔开的版本方便在coupang后台录入。
第二，找精准长尾词做付费推广（需要精准流量词，按相关性排列并打分1-5）。
广告组一为【核心出单词】。广告组二为【精准长尾关键词】。广告组三为【长尾捡漏组广告词】。
第三，生成一个高点击率 (High CTR) 标题方案。
第四，提供一个产品韩语名称用于内部管理。
第五，撰写5条商品好评。
第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出表格。
第七，AI 主图生成建议。

【程序读取专属指令】：
请务必将第六部分的去重汇总关键词，以纯韩文形式放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间，每行一个词。
"""

PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC挖掘以及“精铺快速测品”的高 ROAS 广告策略。我们做的是韩国电商coupang平台，但我是一个中国卖家，输出我能看懂的结果。关键词相关内容不要翻译英文，保持韩文，只要有对应的中文示意即可。

**核心任务：**
基于产品详情页原图及以下 Naver 关键词真实搜索量数据（CSV格式），输出精准广告分组、否定词表。不要含有 LxU 的品牌词。

【市场数据】：
{market_data}

**第一步：全维度分析** (视觉属性识别、痛点挖掘、排除逻辑)
**第二步：关键词清洗与打分** (结合流量与痛点保留核心词和捡漏词，剔除宽泛词)
**第三步：输出二大模块**
模块一：付费广告投放策略表 (Markdown表格，分核心出单词、精准长尾词、捡漏与痛点组，按总搜索量降序，带序号)
模块二：否定关键词列表 (建议屏蔽的词及原因)
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
                for item in data.get("keywordList", [])[:8]: # 限制每个词取前8个拓展
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
# 用来在三个标签页之间传递数据
if "kw_text" not in st.session_state: st.session_state.kw_text = ""
if "df_market" not in st.session_state: st.session_state.df_market = pd.DataFrame()
if "gemini_file_name" not in st.session_state: st.session_state.gemini_file_name = ""

# ==========================================
# 3. 界面布局：三大标签页
# ==========================================
st.title("🛡️ LxU 测品工作流 (三步手动控制版)")
file = st.file_uploader("📥 全局唯一入口：请先上传 PDF 详情页", type=["pdf", "png", "jpg"])

tab1, tab2, tab3 = st.tabs(["📌 第一步：AI 提词", "📈 第二步：搜量回测", "🧠 第三步：终极策略"])

# ----------------- 标签页 1：AI 提词 -----------------
with tab1:
    st.header("1️⃣ 提取初筛关键词")
    if file and st.button("🚀 执行第一步：AI 视觉提炼"):
        model = genai.GenerativeModel("gemini-2.5-flash")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        with st.spinner("Gemini 正在看图写报告..."):
            gen_file = genai.upload_file(path=temp_path)
            while gen_file.state.name == "PROCESSING": time.sleep(2)
            st.session_state.gemini_file_name = gen_file.name # 保存云端文件句柄供第三步用
            
            res1 = model.generate_content([gen_file, PROMPT_STEP_1])
            with st.expander("查看 AI 完整原始报告", expanded=False):
                st.write(res1.text)
                
            # 暴力提取韩文
            match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
            kw_list = []
            if match:
                kw_list = list(dict.fromkeys(re.findall(r'[가-힣]+', match.group(1))))
            else:
                kw_list = list(dict.fromkeys(re.findall(r'[가-힣]+', res1.text[-800:])))[:25]
            
            # 自动填入文本框（核心护城河：允许用户手动修改！）
            st.session_state.kw_text = "\n".join(kw_list)
            st.success("✅ 提取完成！请在下方核对关键词（可手动修改/增删），然后前往【第二步】")
            os.remove(temp_path)

    # 显示一个可编辑的文本框，用户可以随时修改传递给 Naver 的词
    user_edited_kws = st.text_area("✍️ 传给 Naver 的关键词列表 (每行一个，可手动修改)：", value=st.session_state.kw_text, height=300)

# ----------------- 标签页 2：搜量回测 -----------------
with tab2:
    st.header("2️⃣ 获取 Naver 真实数据")
    st.info("将读取第一步文本框中的词汇向 Naver 发起查询。")
    if st.button("📊 执行第二步：开始查询"):
        # 读取用户编辑过的文本框内容
        final_kw_list = [kw.strip() for kw in user_edited_kws.split("\n") if kw.strip()]
        if not final_kw_list:
            st.warning("⚠️ 关键词列表为空，请先执行第一步或手动输入。")
        else:
            pb = st.progress(0)
            st_text = st.empty()
            df = fetch_naver_data(final_kw_list, pb, st_text)
            if not df.empty:
                st.session_state.df_market = df
                st.success("✅ Naver 数据查询成功！请前往【第三步】")
                st.dataframe(df)
            else:
                st.error("❌ 查询失败，Naver 未返回有效数据。")

# ----------------- 标签页 3：终极策略 -----------------
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
                # 调出第一步上传的云端文件
                gen_file = genai.get_file(st.session_state.gemini_file_name)
                
                market_csv = st.session_state.df_market.to_csv(index=False)
                final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                
                res3 = model.generate_content([gen_file, final_prompt])
                st.success("✅ 终极策略生成完毕！")
                st.markdown(res3.text)
                
                # 导出按钮
                st.download_button("📥 导出终极策略 (TXT)", data=res3.text, file_name="LxU_终极策略.txt")
