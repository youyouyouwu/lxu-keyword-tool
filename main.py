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
import concurrent.futures

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品工作流 (回归原味版)", layout="wide")

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
# 1. 核心指令
# ==========================================
PROMPT_STEP_1 = """
你是一个在韩国市场拥有多年实战经验的电商运营专家，熟悉 Coupang 与 Naver SmartStore 的搜索机制和用户点击行为。你的整个运营团队都在中国，所以你必须遵守以下极其严格的【语言输出隔离规范】：
1. 所有的“分析过程”、“策略解释”等描述性质的文字，必须 100% 使用【简体中文】！绝对禁止使用韩文解释！
2. 只有“韩文关键词本身”、“韩语标题”和“商品好评的韩文原文”允许出现韩文，且必须全部附带对应的【中文翻译】。

--- 核心任务 ---
基于我提供的商品图片，生成能够提高点击率、语义自然、本土化表达强、突出卖点的商品标题，同时兼顾搜索匹配。

【品牌与通用规则】：
- 品牌名全部默认固定为：LxU
- 严禁使用夸张营销词（如 최고, 1위, 완벽 等）。
- 严禁使用斜杠 /。
- 必须语义通顺，像真实韩国卖家写的，避免机械堆砌关键词。

【💡 极度重要排版要求：一键复制功能】：
你生成的“纯韩文逗号隔开的后台关键词”以及“纯韩文评价”，必须单独放在 Markdown 代码块里面！
**警告：代码块开头只允许写三个反引号 ``` ，绝对不允许出现 ```text 或任何字母！代码块内只有纯韩文（如果是关键词加逗号），不允许有其他多余解释！**

第一部分：Coupang 专属优化 (偏转化与清晰表达)
1. 标题公式：LxU + 核心卖点 + 关键规格或属性 + 使用场景或解决问题点。核心词必须放前面。
-> 输出带中文翻译的标题（韩文标题务必放在上述要求的代码块里）。
2. 挖掘 20 个 Coupang 后台精准关键词（2~20字符）。
-> 必须以 Markdown 表格输出：【序号 | Coupang韩文关键词 | 中文翻译 | 纯中文策略解释】。
-> 表格下方，单独把这20个纯韩文词用逗号隔开，并务必放在上述要求的代码块里输出。

第二部分：Naver 专属优化 (偏搜索覆盖与曝光)
1. 标题规则：LxU + 核心词 + 修饰词与长尾词，加入更多用户搜索表达。
-> 输出带中文翻译的标题（韩文标题务必放在代码块里）。
2. 挖掘 20 个 Naver 后台扩展关键词（偏搜索扩展）。
-> 必须以 Markdown 表格输出：【序号 | Naver韩文关键词 | 中文翻译 | 纯中文策略解释】。
-> 表格下方，单独把这20个纯韩文词用逗号隔开，并务必放在代码块里输出。

第三部分：找精准长尾词做付费推广
广告组一为【核心出单词】，广告组二为【精准长尾关键词】，广告组三为【长尾捡漏组】。
输出格式为 Markdown 表格：【序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量 | 相关性评分(1-5)】。

第四部分：提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五部分：按照产品卖点撰写10条商品韩文好评。
1. 先以 Markdown 表格形式排列：【序号 | 韩文评价原文 | 纯中文翻译 | 买家痛点分析】。
2. 表格下方，将这10条纯韩文评价原文按行隔开，单独放在 ``` 代码块中输出，方便一键复制。

第六部分：AI 主图生成建议：基于场景词用纯中文建议背景和构图。

【程序读取专属指令 - 极度重要】：
将上述所有生成的【韩文关键词】进行全面去重汇总，单列纵向列表输出，并且**必须放在以下两个标记之间**！每行只写一个韩文关键词，尽量不要带中文或序号。
[LXU_KEYWORDS_START]
(在这里填入去重后的纯韩文关键词)
[LXU_KEYWORDS_END]
"""

# ================= 第三步回归原版：完美融合你提供的高价值 Prompt =================
PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC（用户之声）挖掘以及“精铺快速测品”的高 ROAS 广告策略。我们做的韩国电商coupang平台，但我是一个中国卖家，输出我能看懂的结果。关键词相关内容不要翻译英文，保持韩文，只要有对应的中文示意即可。绝对不要含有 LxU 的品牌词！

【以下是市场核心搜索词及拓展词真实流量数据】：
{market_data}

**核心任务：**
基于产品详情页原图特性和上述数据表现，输出精准广告分组、否定词表。

**第一步：全维度分析 (Deep Analysis)**
1. 视觉与属性识别：分析详情页信息，锁定核心属性（材质、形状、功能、场景）。
2. 痛点挖掘（若有评论）：从竞品差评中提炼用户痛点（如：噪音大、易生锈）。
3. 排除逻辑建立：明确“绝对不相关”的属性（如：产品是塑料，排除“不锈钢”）。

**第二步：关键词清洗与打分 (Filtering & Scoring)**
基于我提供的数据列表（特别是第一步提炼的源头词），进行严格筛选：
1. 相关性打分 (1-5分)：
   * 1-2分 (保留)：核心词及精准长尾词。
   * 3分 (保留)：强关联场景或竞品词（可用于捡漏）。
   * 4-5分 (剔除/否定)：宽泛大词或属性错误的词。
2. 流量与痛点加权：
   * 优先保留能解决“竞品痛点”的词。
   * 参考“总搜索量”，保留虽然流量小但极精准的长尾词。

**第三步：输出二大模块 (Output Modules)**

**模块一：付费广告投放策略表**
请以 Markdown 表格输出，**直接填写真实数据，绝不允许输出省略号或虚线排版！**
表头严格固定为：【序号 | 广告组分类 | 相关性评分 | 韩文关键词 | 月总搜索量 | 中文翻译 | 竞争度 | 推荐策略与说明】

* **广告组分类（必须包含以下三类）：**
   * 【核心出单词】：流量较大，完全匹配。
   * 【精准长尾词】：核心词+具体属性。
   * 【捡漏与痛点组】：错别字、倒序、方言、场景词、竞品词。
* **排序规则：** 按分类制作三组关键词结果列表。在同一个分类内部，按“月总搜索量”从高到低排列。
* **数量要求：** 保证准确的情况下尽量保证关键词数量，不要遗漏极品词汇。
* **格式要求：** 关键词后面不需要带出处的小标志（例如 [1] 等）。总搜索量列无数据则预估。

**模块二：否定关键词列表 (Negative Keywords)**
*用于广告后台屏蔽，防止无效烧钱。*
* **建议屏蔽的词：** `[词1], [词2], [词3]...` (列出4-5分的错误属性词)
* **屏蔽原因：** [简述，例如：材质不符（我是塑料，词是金属）、场景错误等]
"""

# ==========================================
# 2. Naver 数据抓取函数 (并发极速版)
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

    def fetch_single(mk):
        rows = []
        try:
            timestamp = str(int(time.time() * 1000))
            sig = make_signature("GET", "/keywordstool", timestamp)
            headers = {"X-Timestamp": timestamp, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": clean_for_api(mk), "showDetail": 1}, timeout=8)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("keywordList", []): 
                    pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                    mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                    rows.append({
                        "Naver实际搜索词": item.get("relKeyword", ""),
                        "月总搜索量": pc + mob,
                        "竞争度": item.get("compIdx", "-"),
                        "AI溯源(原词)": mk
                    })
        except Exception:
            pass
        return rows

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_mk = {executor.submit(fetch_single, mk): mk for mk in main_keywords}
        for future in concurrent.futures.as_completed(future_to_mk):
            mk = future_to_mk[future]
            completed += 1
            st_text.text(f"📊 Naver 极速并发拓词中 [{completed}/{total}]: {mk}")
            pb.progress(completed / total)
            try:
                all_rows.extend(future.result())
            except Exception:
                pass
            time.sleep(0.05) 
            
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False)
    return df

# ==========================================
# 3. 主 UI 与全自动工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂 (回归原味稳定版)")
st.info("💡 提示：运行中如需紧急终止，请点击页面右上角自带的圆形 Stop 按钮。")

# 清理缓存按钮
if st.sidebar.button("🗑️ 清理云端垃圾文件"):
    try:
        count = 0
        for f in genai.list_files():
            genai.delete_file(f.name)
            count += 1
        st.sidebar.success(f"清理了 {count} 个缓存文件！")
    except Exception as e:
        st.sidebar.error(f"清理失败: {e}")

files = st.file_uploader("📥 请上传产品详情页 (强烈建议截图，保持在2MB内)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

if files and st.button("🚀 启动全自动闭环", use_container_width=True):
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    for file in files:
        st.divider()
        st.header(f"📦 正在自动处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        # ------------------ 第一步：自动识图与提取 ------------------
        with st.status("🔍 第一步：AI 视觉提炼与本地化分析...", expanded=True) as s1:
            try:
                gen_file = genai.upload_file(path=temp_path)
                while gen_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gen_file = genai.get_file(gen_file.name)
                
                res1 = model.generate_content([gen_file, PROMPT_STEP_1])
                with st.expander("👉 查看第一步完整报告 (已强制纯中文隔离)", expanded=False):
                    st.write(res1.text)
                
                # 强化版韩文长尾词提取（保留空格）
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
                
                if kw_list:
                    s1.update(label=f"✅ 第一步完成！成功截获 {len(kw_list)} 个纯正韩文词组", state="complete")
                else:
                    s1.update(label="❌ 第一步提取失败，未能找到韩文", state="error")
                    continue 
            except Exception as e:
                s1.update(label=f"❌ AI 请求失败: {e}", state="error")
                st.error("请检查额度是否耗尽，或点击左侧清理云端缓存。")
                continue

        # ------------------ 第二步：自动触发 Naver 流量回测 ------------------
        with st.status("📊 第二步：连接 Naver 获取真实搜索数据 (自动跳转)...", expanded=True) as s2:
            pb = st.progress(0)
            status_txt = st.empty()
            
            df_market = fetch_naver_data(kw_list, pb, status_txt)
            
            if not df_market.empty:
                st.dataframe(df_market)
                target_count = len(kw_list)
                derived_count = len(df_market)
                s2.update(label=f"✅ 第二步完成！已获取最新韩国市场客观数据 (目标词：{target_count} 个 ➡️ 衍生词：{derived_count} 个)", state="complete")
            else:
                s2.update(label="❌ 第二步失败，Naver 未返回有效数据", state="error")
                continue 

        # ------------------ 第三步：自动触发终极策略推演 ------------------
        with st.status("🧠 第三步：主客观数据融合，生成终极策略 (自动跳转)...", expanded=True) as s3:
            try:
                # 保留原词，掐尖拓展词
                seed_df = df_market[df_market["Naver实际搜索词"].isin(kw_list)]
                expanded_df = df_market[~df_market["Naver实际搜索词"].isin(kw_list)].head(250)
                
                final_df = pd.concat([seed_df, expanded_df]).drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False)
                
                market_csv = final_df.to_csv(index=False)
                final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                
                res3 = model.generate_content([gen_file, final_prompt])
                st.markdown("### 🏆 LxU 终极测品策略报告")
                st.success(res3.text)
                
                s3.update(label="✅ 第三步完成！终极排兵布阵已生成", state="complete")
            except Exception as e:
                s3.update(label=f"❌ 第三步失败: {e}", state="error")

        # ------------------ 收尾与导出 ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name)
        except:
            pass
            
        try:
            final_report = f"【LxU 产品测品全景报告：{file.name}】\n\n" + "="*40 + "\n[第一步：AI 视觉提炼 (纯中文)]\n" + res1.text + "\n\n" + "="*40 + "\n[第二步：Naver 客观搜索量 (精炼合集)]\n" + market_csv + "\n\n" + "="*40 + "\n[第三步：终极策略与广告分组]\n" + res3.text
            
            st.download_button(
                label=f"📥 一键下载 {file.name} 完整测品报告 (TXT)", 
                data=final_report, 
                file_name=f"LxU_自动测品全记录_{file.name}.txt"
            )
        except:
            pass
