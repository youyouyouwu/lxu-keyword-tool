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
import io 
import zipfile              
import markdown  # 🚀 新增：用于将文本渲染为极美网页排版

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品工作流 (终极稳定版)", layout="wide")

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
- 标题中【绝对不要使用任何标点符号】，词语之间用空格自然隔开即可。
- 标题必须【语句通顺自然】，符合真实韩国本土买家的搜索和阅读习惯。

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

第三部分：生成用于Naver查量的“候选关键词模板”（此阶段无真实流量数据）

重要定位：
- 当前仅基于详情页内容生成“候选关键词模板/词根组合”，用于下一步去Naver API扩展与查量。
- 你不是在做最终投放策略，不允许输出“确定可投”的结论。
- 禁止凭空编造具体流量数值。

一、先建立类目闭环（必须先做）
从详情页中提取并输出（用于约束后续关键词）：
1) 主体锚点（核心商品名词，1~3个）
2) 必须属性锚点（决定类目边界，3~8个）
3) 可选属性锚点（不改变类目，3~10个）
4) 排他边界（不适配/不包含/容易跨类目的词，至少8个）
5) 高风险上位词黑名单（行业词/泛词/服务词，至少10个）

二、候选关键词模板生成规则（强制执行）
你只能生成两类内容：
A) 详情页中明确出现或可直接同义替换的“主体词/属性词”
B) 由【主体锚点 + 必须属性锚点】拼接形成的“查询组合模板”
禁止：
- 生成与主体无关的行业词/服务词/泛词
- 使用过于抽象的词（如 工事/装修/工具/材料/服务 等）
- 生成“无法对应商品实体结构”的词
- 给出具体流量数字

三、三组广告结构（此阶段仅作为“查量优先级”，不是最终投放组）
广告组一：【核心出单词候选】（用于优先查量）
- 以“主体锚点/主体同义词”为主
- 若主体过泛，必须用“必须属性”做组合模板
- 输出 5~8 个候选/模板

广告组二：【精准长尾关键词候选】（用于主力查量）
- 主体 + 必须属性（规格/结构/适配对象/连接方式等）
- 输出 8~15 个候选/模板

广告组三：【长尾捡漏候选】（用于补充查量）
- 主体 + 可选属性 + 场景（仅限详情页明确出现的场景）
- 输出 8~15 个候选/模板

四、输出格式（Markdown表格，表头必须中文）
说明：
- “预估流量”列此阶段只能填：高 / 中 / 低（代表查量优先级，不是实际流量）
- “相关性评分”按类目闭环匹配度给 1~5
- “中文策略解释”≤20字，解释为什么适合作为查量入口

输出Markdown表格：

| 序号 | 广告组分类 | 韩文关键词（候选/模板） | 中文翻译 | 中文策略解释 | 预估流量（高/中/低） | 相关性评分(1-5) |

五、额外要求
1) 总行数控制在 25~35（因为后续还要扩展查量）
2) 必须优先输出“可作为查量入口的代表词/模板”，避免同义词堆叠
3) 若某候选词属于“主体泛词”，必须在策略解释中标注“需属性组合”
4) 禁止出现品牌名
5) 禁止使用“/”连接关键词

第四部分：提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五部分：按照产品卖点撰写10条商品韩文好评。
1. 先以 Markdown 表格形式排列：【序号 | 韩文评价原文 | 纯中文翻译 | 买家痛点分析】。
2. 表格下方，将这10条纯韩文评价原文按行隔开，单独放在 ``` 代码块中输出，方便一键复制。

第六部分：AI 主图生成建议：基于场景词用纯中文建议背景和构图。

【程序读取专属指令 - 极度重要】：
将上述所有生成的【韩文关键词】进行全面去重汇总，单列横向输出，并且**必须放在以下两个标记之间**！
⚠️ 警告：这里的关键词之间【必须使用英文逗号 (,) 隔开】！绝对不允许只用空格连在一起！
[LXU_KEYWORDS_START]
关键词1,关键词2,关键词3
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
【以下是市场核心搜索词及拓展词真实流量数据】：
{market_data}

=======================================================
你是一位拥有10年实战经验的韩国 Coupang 跨境电商高级广告操盘手。
除“韩文关键词”外，所有解释分析必须用纯中文输出。
绝对不要出现任何品牌词（包含 LxU 等）。

你的任务不是生成新关键词，而是：
基于我提供的【产品原图/详情页切片】与上方【market_data真实流量数据】，从数据中筛选出可直接投放的关键词，并输出最终广告投放结构与否定词。
严禁输出 market_data 中不存在的新关键词。

━━━━━━━━━━━━━━━━━━
【0）强制规则（必须遵守，否则视为失败）】
━━━━━━━━━━━━━━━━━━
1) 关键词来源规则（最重要）：
- “韩文关键词”必须 100% 来自 market_data 原文，不得新增、不得改写、不得拆词重组生成新词
- “月总搜索量”必须 100% 来自 market_data 原始数据，不得编造、不得估算

2) 禁止项：
- 禁止出现任何品牌词（包含 LxU）
- 禁止使用“/”斜杠连接关键词
- 禁止输出“...”省略号
- 禁止空行、禁止表格缺行、缺列
- 除韩文关键词外，所有文字必须为纯中文

3) 输出控制：
- 只允许输出：①字段映射确认 ②极简锚点 ③最终投放表格 ④否定词
- 不要输出任何额外分析段落，不要输出长篇解释

━━━━━━━━━━━━━━━━━━
【1）字段映射校验（防读错列，必须先做）】
━━━━━━━━━━━━━━━━━━
你必须先在开头用纯中文输出一小段“字段映射确认”，格式如下（只输出这4行）：
- 关键词列 = xxx
- 搜索量列 = xxx
- 中文翻译列 = xxx（若无则写“缺失”）
- 竞争度列 = xxx（若无则写“缺失”）

如果你无法确认关键词列或搜索量列，请停止输出并说明缺少字段（不要生成表格）。

━━━━━━━━━━━━━━━━━━
【2）极简产品锚点（只为控方向，不要长篇）】
━━━━━━━━━━━━━━━━━━
用纯中文极简输出（总计不超过8行）：
- 主体锚点（韩文+中文，1~3个）
- 必须属性锚点（韩文+中文，3~8个）
- 高风险排除方向（中文即可，5~10个：行业词/服务词/上位泛词/跨类目词）

注意：此段只用于后续选词控偏，不做长文解析。

━━━━━━━━━━━━━━━━━━
【3）最终结果：高价值付费广告投放策略表（核心中的核心，必须填满）】
━━━━━━━━━━━━━━━━━━
这部分是最终输出结果，必须严格执行，不得省略、不得简写、不得输出任何额外内容。

【3.1 选词要求（强制）】
- 你必须从 market_data 中筛选 15–25 个关键词（总行数必须在这个范围内）
- 必须分配到三组广告组，且任何一组都不允许为空
- 建议数量结构（必须尽量满足，除非数据不足）：
  - 核心出单词：5–8个
  - 精准长尾词：6–10个
  - 捡漏与痛点组：4–7个
- 若数据不足无法满足上述数量结构：
  - 也必须保证三组都非空
  - 并用一句纯中文说明“数据不足原因”（只允许一句话）

- 同义词/近义词簇只保留代表词，避免重复投放
- 禁止只按搜索量排序：必须兼顾相关性与泛词风险
- 高流量但跨类目风险高的词：必须淘汰或降级为“组合/测试”，不得放入核心出单词

【3.2 三组广告结构定义（强制）】
A. 【核心出单词】
- 最贴近主体锚点与必须属性
- 相关性评分一般应 ≥4
- 若关键词偏泛（例如上位主词），必须在“推荐策略与说明”中标注：需属性组合控流量

B. 【精准长尾词】
- 主体 + 关键属性/规格/适配对象/结构词
- 主力转化词，适合稳定出单

C. 【捡漏与痛点组】
- 搜索量较低但意图明确
- 对应明确痛点/场景（必须与产品直接相关）
- 适合低预算测试与补充转化

【3.3 表格排序与填表规则（强制）】
- 表格必须按三大分类顺序展示：
  核心出单词 ➜ 精准长尾词 ➜ 捡漏与痛点组
- 每个分类内部必须按“月总搜索量”降序排列
- 表格必须逐行填满真实数据，不许省略号，不许空行，不许缺列
- 相关性评分(1-5)：只基于产品锚点匹配度给分（5最高）
- 推荐策略与说明：纯中文 ≤20字，必须可执行（单独/组合/测试/控泛词/低预算等）
- 若 market_data 缺少“中文翻译”，你必须基于语义补齐中文翻译
- 若 market_data 缺少“竞争度”，你必须用“高/中/低”补齐
  （但关键词与搜索量仍必须来自 market_data）

【强制 Markdown 表格格式】（必须严格使用此表头）：

| 序号 | 广告组分类 | 相关性评分(1-5) | 韩文关键词 | 月总搜索量 | 中文翻译 | 竞争度 | 推荐策略与说明 |
|---|---|---|---|---|---|---|---|

━━━━━━━━━━━━━━━━━━
【4）否定关键词列表（Negative Keywords，至少10个）】
━━━━━━━━━━━━━━━━━━
- 建议屏蔽的词：从 market_data 中挑出至少10个触发“高风险排除方向”、无购物意图或明显跨类目的词，用逗号隔开（必须是真实存在的词）
- 屏蔽原因：纯中文简述（1–2句话即可）

结束输出。
"""

# ==========================================
# 2. 强力引擎：安全生成与数据抓取
# ==========================================

def safe_generate(model, contents, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            res = model.generate_content(contents)
            return res.text 
        except Exception as e:
            if attempt < max_retries:
                time.sleep(3) 
            else:
                return f"❌ 严重错误：API 连续 {max_retries} 次无响应或被安全拦截，无法生成内容。详情：{str(e)}"

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
        df = df.drop_duplicates(subset=["Naver实际搜索词"])
        
        seed_no_space = [str(k).replace(" ", "") for k in main_keywords]
        df['is_seed'] = df['Naver实际搜索词'].apply(lambda x: str(x).replace(" ", "") in seed_no_space)
        
        df.insert(1, '词组属性', df['is_seed'].apply(lambda x: '🎯 目标原词' if x else '💡 衍生拓展词'))
        df = df.sort_values(by=["is_seed", "月总搜索量"], ascending=[False, False])
        df = df.drop(columns=['is_seed'])
        
    return df

# ==========================================
# 3. 主 UI 与全自动工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂 (终极防崩溃版)")
st.info("💡 提示：运行中如需紧急终止，请点击页面右上角自带的圆形 Stop 按钮。")

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
    
    master_zip_buffer = io.BytesIO()
    master_zip = zipfile.ZipFile(master_zip_buffer, 'w', zipfile.ZIP_DEFLATED)
    
    for file in files:
        st.divider()
        st.header(f"📦 正在自动处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        res1_text = ""
        res3_text = ""
        kw_list = []
        market_csv = ""
        folder_name = os.path.splitext(file.name)[0]

        # ------------------ 第一步：自动识图与提取 ------------------
        with st.status("🔍 第一步：AI 视觉提炼与本地化分析...", expanded=True) as s1:
            try:
                gen_file = genai.upload_file(path=temp_path)
                while gen_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gen_file = genai.get_file(gen_file.name)
                
                res1_text = safe_generate(model, [gen_file, PROMPT_STEP_1])
                
                if res1_text.startswith("❌"):
                    s1.update(label="❌ 第一步 AI 生成彻底失败", state="error")
                    st.error(res1_text)
                    continue
                
                with st.expander("👉 查看第一步完整报告 (已强制纯中文隔离)", expanded=False):
                    st.write(res1_text)
                
                match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1_text, re.DOTALL | re.IGNORECASE)
                if match:
                    raw_block = match.group(1)
                    raw_block = re.sub(r'[，\n、|]', ',', raw_block) 
                    for kw in raw_block.split(','):
                        clean_word = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', kw).strip()
                        clean_word = re.sub(r'\s+', ' ', clean_word)
                        if clean_word and clean_word not in kw_list:
                            kw_list.append(clean_word)
                else:
                    tail_text = res1_text[-800:]
                    tail_text = re.sub(r'[，\n、|]', ',', tail_text)
                    for kw in tail_text.split(','):
                        clean_word = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', kw).strip()
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
                s1.update(label=f"❌ 本地系统逻辑错误: {e}", state="error")
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
                seed_df = df_market[df_market["词组属性"] == '🎯 目标原词']
                expanded_df = df_market[df_market["词组属性"] == '💡 衍生拓展词'].head(250)
                
                final_df = pd.concat([
                    seed_df.sort_values(by="月总搜索量", ascending=False), 
                    expanded_df.sort_values(by="月总搜索量", ascending=False)
                ]).drop_duplicates(subset=["Naver实际搜索词"])
                
                market_csv = final_df.to_csv(index=False)
                final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                
                res3_text = safe_generate(model, [gen_file, final_prompt])
                
                if res3_text.startswith("❌"):
                    s3.update(label="❌ 第三步 AI 生成彻底失败", state="error")
                    st.error(res3_text)
                else:
                    st.markdown("### 🏆 LxU 终极测品策略报告")
                    st.success(res3_text)
                    s3.update(label="✅ 第三步完成！终极排兵布阵已生成", state="complete")
            except Exception as e:
                s3.update(label=f"❌ 第三步系统逻辑错误: {e}", state="error")

        # ------------------ 收尾与文件生成 (🚀 升级为高定网页版报告) ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name)
        except:
            pass
            
        try:
            # === 解析与提炼 ===
            def parse_md_table(md_text, keyword):
                lines = md_text.split('\n')
                table_data = []
                is_table = False
                for line in lines:
                    line = line.strip()
                    if '|' in line and keyword in line:
                        is_table = True
                        table_data.append(line)
                        continue
                    if is_table:
                        if line.startswith('|') or line.endswith('|') or '|' in line:
                            if '---' not in line:
                                table_data.append(line)
                        else:
                            if len(line.strip()) > 0: 
                                break
                if not table_data:
                    return pd.DataFrame()
                parsed_rows = []
                for row in table_data:
                    cols = [col.strip() for col in row.split('|')]
                    if cols and not cols[0]: cols = cols[1:]   
                    if cols and not cols[-1]: cols = cols[:-1] 
                    parsed_rows.append(cols)
                if len(parsed_rows) > 1:
                    return pd.DataFrame(parsed_rows[1:], columns=parsed_rows[0])
                return pd.DataFrame()

            raw_titles = []
            for line in res1_text.split('\n'):
                line_clean = line.strip()
                if 'LxU' in line_clean and not any(x in line_clean for x in ['公式', '规则', '卖点', '核心词', '翻译', '中文']):
                    clean_t = re.sub(r'```[a-zA-Z]*', '', line_clean)
                    clean_t = clean_t.strip('`*>- \t')
                    if clean_t.startswith('LxU') and clean_t not in raw_titles:
                        raw_titles.append(clean_t)
            
            coupang_title = raw_titles[0] if len(raw_titles) > 0 else "未提取到 Coupang 标题，请查阅全景报告"
            naver_title = raw_titles[1] if len(raw_titles) > 1 else "未提取到 Naver 标题，请查阅全景报告"

            kw_lines = []
            for line in res1_text.split('\n'):
                if ('，' in line or ',' in line) and '|' not in line and re.search(r'[가-힣]', line):
                    if line.count(',') + line.count('，') >= 5: 
                        clean_kw = re.sub(r'```[a-zA-Z]*', '', line).strip()
                        clean_kw = clean_kw.strip('`').strip()
                        if clean_kw and clean_kw not in kw_lines:
                            kw_lines.append(clean_kw)
            
            coupang_kws = kw_lines[0] if len(kw_lines) > 0 else "未提取到 Coupang 关键词，请查阅全景报告"
            naver_kws = kw_lines[1] if len(kw_lines) > 1 else "未提取到 Naver 关键词，请查阅全景报告"

            df_sheet1 = pd.DataFrame({
                "信息维度": ["Coupang 标题", "Coupang 后台关键词", "Naver 标题", "Naver 后台关键词"],
                "提炼内容": [coupang_title, coupang_kws, naver_title, naver_kws]
            })

            df_comments = parse_md_table(res1_text, "韩文评价原文")
            df_ads = parse_md_table(res3_text, "广告组分类")

            # === 写入 Excel (内存) ===
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df_sheet1.to_excel(writer, index=False, sheet_name='登品标题')
                if not df_comments.empty:
                    df_comments.to_excel(writer, index=False, sheet_name='评论区内容')
                else:
                    pd.DataFrame([{"提示": "未找到规范的评价表格"}]).to_excel(writer, index=False, sheet_name='评论区内容')
                if not df_ads.empty:
                    df_ads.to_excel(writer, index=False, sheet_name='广告投放关键词')
                else:
                    pd.DataFrame([{"提示": "未找到规范的广告策略表"}]).to_excel(writer, index=False, sheet_name='广告投放关键词')
            excel_data = excel_buffer.getvalue()

            # === 🚀 写入精美 HTML 网页报告 (完美替代容易乱码的 Word) ===
            css_style = """
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", "Microsoft YaHei", sans-serif; padding: 40px; max-width: 1000px; margin: auto; line-height: 1.6; color: #333; background-color: #f4f6f9; }
                .container { background: #ffffff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
                h1 { color: #1E3A8A; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; text-align: center; }
                h2 { color: #2563eb; margin-top: 30px; }
                h3 { color: #475569; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; border-radius: 8px; overflow: hidden; }
                th, td { border: 1px solid #e2e8f0; padding: 12px 15px; text-align: left; }
                th { background-color: #f8fafc; color: #1e293b; font-weight: 600; }
                tr:nth-child(even) { background-color: #f1f5f9; }
                pre { background-color: #1e293b; padding: 20px; border-radius: 8px; overflow-x: auto; color: #f8fafc; font-family: monospace; }
                code { background-color: #e2e8f0; padding: 2px 6px; border-radius: 4px; color: #b91c1c; font-size: 0.9em; }
                .print-btn { display: block; width: 200px; margin: 20px auto; padding: 10px; background-color: #2563eb; color: white; text-align: center; text-decoration: none; border-radius: 5px; font-weight: bold; cursor: pointer; border: none; }
                @media print { .print-btn { display: none; } body { background-color: white; } .container { box-shadow: none; padding: 0; } }
            </style>
            """
            
            # 使用 markdown 库将 AI 生成的文本转换为 HTML 表格和排版
            html_part1 = markdown.markdown(res1_text, extensions=['tables', 'fenced_code'])
            html_part3 = markdown.markdown(res3_text, extensions=['tables', 'fenced_code'])

            html_content = f"""
            <!DOCTYPE html>
            <html lang="zh-CN">
            <head>
                <meta charset="utf-8">
                <title>LxU 测品全景报告 - {folder_name}</title>
                {css_style}
            </head>
            <body>
                <div class="container">
                    <button class="print-btn" onclick="window.print()">🖨️ 保存为高质量 PDF</button>
                    <h1>📊 LxU 测品全景报告</h1>
                    <p style="text-align: center; color: #64748b;">报告归属产品：{folder_name} | 生成日期：自动记录</p>
                    
                    <h2>🔍 第一步：AI 视觉提炼与本地化分析</h2>
                    {html_part1}
                    
                    <hr style="border: 1px dashed #cbd5e1; margin: 40px 0;">
                    
                    <h2>🧠 第三步：产品深度解析与终极广告策略</h2>
                    {html_part3}
                </div>
            </body>
            </html>
            """
            
            # === 将生成的 Excel 和 HTML 网页写入主 ZIP 包 ===
            master_zip.writestr(f"{folder_name}/LxU_数据表_{folder_name}.xlsx", excel_data)
            # 存为 .html 后缀
            master_zip.writestr(f"{folder_name}/LxU_视觉报告_{folder_name}.html", html_content.encode('utf-8'))
            
            st.success(f"📦 【{file.name}】 处理完毕！已打包存入内存。")
            
        except Exception as e:
            st.error(f"处理 {file.name} 构建导出文件时发生错误: {e}")

    # ==========================================
    # 4. 循环结束后，提供统一大压缩包下载
    # ==========================================
    master_zip.close() # 关闭ZIP写入流
    if files:
        st.divider()
        st.markdown("### 🎉 全部产品处理完成！")
        st.download_button(
            label=f"📥 一键下载全部结果 (ZIP 压缩包)", 
            data=master_zip_buffer.getvalue(), 
            file_name="LxU_批量测品结果合集.zip",
            mime="application/zip",
            use_container_width=True
        )


