"""
CNKI search via Playwright browser automation.

Config: ~/.lit-search-cite/config.json  (VPN URL, CNKI WebVPN base, etc.)
Session: ~/.lit-search-cite/cnki_session.json  (browser cookies, persisted)

On first run with no config: a setup wizard opens a browser window to guide
you through VPN login and CNKI WebVPN URL detection. Settings are saved and
reused automatically — setup only needs to happen once.

Usage:
    # First-time setup — don't know your VPN URL? Pass --school:
    python cnki-playwright.py --setup --school scau
    python cnki-playwright.py --setup --school "华南农业大学"

    # First-time setup — you know your VPN URL:
    python cnki-playwright.py --setup

    # Warm up CNKI cookies after setup (required once before headless search):
    python cnki-playwright.py --login-only --no-headless

    # Search (headless once session is saved):
    python cnki-playwright.py --query "大语言模型 代码生成" --limit 20

    # Save results to JSON:
    python cnki-playwright.py --query "transformer attention" --json-output results.json

    # Download PDFs for top results:
    python cnki-playwright.py --query "医学图像分割" --download --output C:/Papers

    # Debug mode (visible browser window):
    python cnki-playwright.py --query "deep learning" --no-headless
"""

import sys
import json
import argparse
import io
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

# Fix Windows console UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("ERROR: playwright not installed.")
    print("Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────────
CONFIG_DIR  = Path.home() / ".lit-search-cite"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE  = CONFIG_DIR / "cnki_session.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# ── Config management ──────────────────────────────────────────────────────────
def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[config] Saved to {CONFIG_FILE}")

def is_configured(config):
    return bool(config.get("vpn_url") and config.get("cnki_vpn_base"))

# ── Session management ─────────────────────────────────────────────────────────
def save_session(context):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STATE_FILE))
    print(f"[session] Saved to {STATE_FILE}")

def get_session_path():
    return str(STATE_FILE) if STATE_FILE.exists() else None

# ── VPN URL discovery ──────────────────────────────────────────────────────────
# Map of Chinese university names / abbreviations → VPN portal domain.
# Each school appears twice: English abbreviation + Chinese full name.
# Sources: official IT/library pages + community-verified.
# If a URL is wrong or outdated, probe_vpn_url() falls back to HTTP probing
# and manual entry — the list is a best-effort starting point.
_KNOWN_VPN = {
    # ── 985 Universities ──────────────────────────────────────────────────────
    "pku":       "vpn.pku.edu.cn",           "北京大学":           "vpn.pku.edu.cn",
    "thu":       "webvpn.tsinghua.edu.cn",   "清华大学":           "webvpn.tsinghua.edu.cn",
    "tsinghua":  "webvpn.tsinghua.edu.cn",
    "fudan":     "webvpn.fudan.edu.cn",      "复旦大学":           "webvpn.fudan.edu.cn",
    "sjtu":      "vpn.sjtu.edu.cn",          "上海交通大学":       "vpn.sjtu.edu.cn",
    "zju":       "webvpn.zju.edu.cn",        "浙江大学":           "webvpn.zju.edu.cn",
    "nju":       "vpn.nju.edu.cn",           "南京大学":           "vpn.nju.edu.cn",
    "ustc":      "webvpn.ustc.edu.cn",       "中国科学技术大学":   "webvpn.ustc.edu.cn",
    "中科大":    "webvpn.ustc.edu.cn",
    "whu":       "webvpn.whu.edu.cn",        "武汉大学":           "webvpn.whu.edu.cn",
    "hust":      "webvpn.hust.edu.cn",       "华中科技大学":       "webvpn.hust.edu.cn",
    "sysu":      "webvpn.sysu.edu.cn",       "中山大学":           "webvpn.sysu.edu.cn",
    "scut":      "webvpn.scut.edu.cn",       "华南理工大学":       "webvpn.scut.edu.cn",
    "hit":       "webvpn.hit.edu.cn",        "哈尔滨工业大学":     "webvpn.hit.edu.cn",
    "xjtu":      "webvpn.xjtu.edu.cn",      "西安交通大学":       "webvpn.xjtu.edu.cn",
    "buaa":      "webvpn.buaa.edu.cn",       "北京航空航天大学":   "webvpn.buaa.edu.cn",
    "beihang":   "webvpn.buaa.edu.cn",       "北航":               "webvpn.buaa.edu.cn",
    "bit":       "webvpn.bit.edu.cn",        "北京理工大学":       "webvpn.bit.edu.cn",
    "csu":       "webvpn.csu.edu.cn",        "中南大学":           "webvpn.csu.edu.cn",
    "sdu":       "webvpn.sdu.edu.cn",        "山东大学":           "webvpn.sdu.edu.cn",
    "jlu":       "webvpn.jlu.edu.cn",        "吉林大学":           "webvpn.jlu.edu.cn",
    "cqu":       "webvpn.cqu.edu.cn",        "重庆大学":           "webvpn.cqu.edu.cn",
    "uestc":     "webvpn.uestc.edu.cn",      "电子科技大学":       "webvpn.uestc.edu.cn",
    "nwpu":      "webvpn.nwpu.edu.cn",       "西北工业大学":       "webvpn.nwpu.edu.cn",
    "bnu":       "webvpn.bnu.edu.cn",        "北京师范大学":       "webvpn.bnu.edu.cn",
    "ruc":       "vpn.ruc.edu.cn",           "中国人民大学":       "vpn.ruc.edu.cn",
    "nankai":    "webvpn.nankai.edu.cn",     "南开大学":           "webvpn.nankai.edu.cn",
    "tongji":    "webvpn.tongji.edu.cn",     "同济大学":           "webvpn.tongji.edu.cn",
    "hnu":       "webvpn.hnu.edu.cn",        "湖南大学":           "webvpn.hnu.edu.cn",
    "xmu":       "webvpn.xmu.edu.cn",        "厦门大学":           "webvpn.xmu.edu.cn",
    "dlut":      "webvpn.dlut.edu.cn",       "大连理工大学":       "webvpn.dlut.edu.cn",
    "seu":       "webvpn.seu.edu.cn",        "东南大学":           "webvpn.seu.edu.cn",
    "tju":       "webvpn.tju.edu.cn",        "天津大学":           "webvpn.tju.edu.cn",
    "lzu":       "webvpn.lzu.edu.cn",        "兰州大学":           "webvpn.lzu.edu.cn",
    "scu":       "webvpn.scu.edu.cn",        "四川大学":           "webvpn.scu.edu.cn",
    "neu":       "webvpn.neu.edu.cn",        "东北大学":           "webvpn.neu.edu.cn",
    "ecnu":      "webvpn.ecnu.edu.cn",       "华东师范大学":       "webvpn.ecnu.edu.cn",
    # ── 211 Universities ─────────────────────────────────────────────────────
    "scau":      "vpn.scau.edu.cn",          "华南农业大学":       "vpn.scau.edu.cn",
    "bjtu":      "webvpn.bjtu.edu.cn",       "北京交通大学":       "webvpn.bjtu.edu.cn",
    "ustb":      "webvpn.ustb.edu.cn",       "北京科技大学":       "webvpn.ustb.edu.cn",
    "buct":      "webvpn.buct.edu.cn",       "北京化工大学":       "webvpn.buct.edu.cn",
    "bupt":      "webvpn.bupt.edu.cn",       "北京邮电大学":       "webvpn.bupt.edu.cn",
    "bjfu":      "webvpn.bjfu.edu.cn",       "北京林业大学":       "webvpn.bjfu.edu.cn",
    "bucm":      "webvpn.bucm.edu.cn",       "北京中医药大学":     "webvpn.bucm.edu.cn",
    "cnu":       "webvpn.cnu.edu.cn",        "首都师范大学":       "webvpn.cnu.edu.cn",
    "ccmu":      "webvpn.ccmu.edu.cn",       "首都医科大学":       "webvpn.ccmu.edu.cn",
    "bsu":       "webvpn.bsu.edu.cn",        "北京体育大学":       "webvpn.bsu.edu.cn",
    "blcu":      "webvpn.blcu.edu.cn",       "北京语言大学":       "webvpn.blcu.edu.cn",
    "bfsu":      "webvpn.bfsu.edu.cn",       "北京外国语大学":     "webvpn.bfsu.edu.cn",
    "cufe":      "webvpn.cufe.edu.cn",       "中央财经大学":       "webvpn.cufe.edu.cn",
    "uibe":      "webvpn.uibe.edu.cn",       "对外经济贸易大学":   "webvpn.uibe.edu.cn",
    "cuc":       "webvpn.cuc.edu.cn",        "中国传媒大学":       "webvpn.cuc.edu.cn",
    "cupl":      "webvpn.cupl.edu.cn",       "中国政法大学":       "webvpn.cupl.edu.cn",
    "muc":       "webvpn.muc.edu.cn",        "中央民族大学":       "webvpn.muc.edu.cn",
    "ncepu":     "webvpn.ncepu.edu.cn",      "华北电力大学":       "webvpn.ncepu.edu.cn",
    "cugb":      "webvpn.cugb.edu.cn",       "中国地质大学北京":   "webvpn.cugb.edu.cn",
    "cug":       "webvpn.cug.edu.cn",        "中国地质大学":       "webvpn.cug.edu.cn",
    "中国地质大学武汉": "webvpn.cug.edu.cn",
    "cumt":      "webvpn.cumt.edu.cn",       "中国矿业大学":       "webvpn.cumt.edu.cn",
    "upc":       "webvpn.upc.edu.cn",        "中国石油大学华东":   "webvpn.upc.edu.cn",
    "cup":       "webvpn.cup.edu.cn",        "中国石油大学北京":   "webvpn.cup.edu.cn",
    "ouc":       "webvpn.ouc.edu.cn",        "中国海洋大学":       "webvpn.ouc.edu.cn",
    "cau":       "webvpn.cau.edu.cn",        "中国农业大学":       "webvpn.cau.edu.cn",
    "cpu":       "webvpn.cpu.edu.cn",        "中国药科大学":       "webvpn.cpu.edu.cn",
    "shu":       "webvpn.shu.edu.cn",        "上海大学":           "webvpn.shu.edu.cn",
    "dhu":       "webvpn.dhu.edu.cn",        "东华大学":           "webvpn.dhu.edu.cn",
    "ecust":     "webvpn.ecust.edu.cn",      "华东理工大学":       "webvpn.ecust.edu.cn",
    "sufe":      "webvpn.sufe.edu.cn",       "上海财经大学":       "webvpn.sufe.edu.cn",
    "sisu":      "webvpn.shisu.edu.cn",      "上海外国语大学":     "webvpn.shisu.edu.cn",
    "shisu":     "webvpn.shisu.edu.cn",
    "shutcm":    "webvpn.shutcm.edu.cn",     "上海中医药大学":     "webvpn.shutcm.edu.cn",
    "suda":      "webvpn.suda.edu.cn",       "苏州大学":           "webvpn.suda.edu.cn",
    "nuaa":      "webvpn.nuaa.edu.cn",       "南京航空航天大学":   "webvpn.nuaa.edu.cn",
    "njust":     "webvpn.njust.edu.cn",      "南京理工大学":       "webvpn.njust.edu.cn",
    "nust":      "webvpn.njust.edu.cn",
    "njnu":      "webvpn.njnu.edu.cn",       "南京师范大学":       "webvpn.njnu.edu.cn",
    "njau":      "webvpn.njau.edu.cn",       "南京农业大学":       "webvpn.njau.edu.cn",
    "njfu":      "webvpn.njfu.edu.cn",       "南京林业大学":       "webvpn.njfu.edu.cn",
    "njupt":     "webvpn.njupt.edu.cn",      "南京邮电大学":       "webvpn.njupt.edu.cn",
    "njucm":     "webvpn.njucm.edu.cn",      "南京中医药大学":     "webvpn.njucm.edu.cn",
    "hhu":       "webvpn.hhu.edu.cn",        "河海大学":           "webvpn.hhu.edu.cn",
    "jiangnan":  "webvpn.jiangnan.edu.cn",   "江南大学":           "webvpn.jiangnan.edu.cn",
    "hfut":      "webvpn.hfut.edu.cn",       "合肥工业大学":       "webvpn.hfut.edu.cn",
    "ahu":       "webvpn.ahu.edu.cn",        "安徽大学":           "webvpn.ahu.edu.cn",
    "fzu":       "webvpn.fzu.edu.cn",        "福州大学":           "webvpn.fzu.edu.cn",
    "hqu":       "webvpn.hqu.edu.cn",        "华侨大学":           "webvpn.hqu.edu.cn",
    "zzu":       "webvpn.zzu.edu.cn",        "郑州大学":           "webvpn.zzu.edu.cn",
    "henu":      "webvpn.henu.edu.cn",       "河南大学":           "webvpn.henu.edu.cn",
    "whut":      "webvpn.whut.edu.cn",       "武汉理工大学":       "webvpn.whut.edu.cn",
    "ccnu":      "webvpn.ccnu.edu.cn",       "华中师范大学":       "webvpn.ccnu.edu.cn",
    "hzau":      "webvpn.hzau.edu.cn",       "华中农业大学":       "webvpn.hzau.edu.cn",
    "zuel":      "webvpn.zuel.edu.cn",       "中南财经政法大学":   "webvpn.zuel.edu.cn",
    "jnu":       "webvpn.jnu.edu.cn",        "暨南大学":           "webvpn.jnu.edu.cn",
    "scnu":      "webvpn.scnu.edu.cn",       "华南师范大学":       "webvpn.scnu.edu.cn",
    "szu":       "webvpn.szu.edu.cn",        "深圳大学":           "webvpn.szu.edu.cn",
    "sustech":   "webvpn.sustech.edu.cn",    "南方科技大学":       "webvpn.sustech.edu.cn",
    "gdut":      "webvpn.gdut.edu.cn",       "广东工业大学":       "webvpn.gdut.edu.cn",
    "gzhu":      "webvpn.gzhu.edu.cn",       "广州大学":           "webvpn.gzhu.edu.cn",
    "gxu":       "webvpn.gxu.edu.cn",        "广西大学":           "webvpn.gxu.edu.cn",
    "gzucm":     "webvpn.gzucm.edu.cn",      "广州中医药大学":     "webvpn.gzucm.edu.cn",
    "smu":       "webvpn.smu.edu.cn",        "南方医科大学":       "webvpn.smu.edu.cn",
    "hunnu":     "webvpn.hunnu.edu.cn",      "湖南师范大学":       "webvpn.hunnu.edu.cn",
    "swu":       "webvpn.swu.edu.cn",        "西南大学":           "webvpn.swu.edu.cn",
    "swjtu":     "webvpn.swjtu.edu.cn",      "西南交通大学":       "webvpn.swjtu.edu.cn",
    "swufe":     "webvpn.swufe.edu.cn",      "西南财经大学":       "webvpn.swufe.edu.cn",
    "sicau":     "webvpn.sicau.edu.cn",      "四川农业大学":       "webvpn.sicau.edu.cn",
    "gzu":       "webvpn.gzu.edu.cn",        "贵州大学":           "webvpn.gzu.edu.cn",
    "ynu":       "webvpn.ynu.edu.cn",        "云南大学":           "webvpn.ynu.edu.cn",
    "ynau":      "webvpn.ynau.edu.cn",       "云南农业大学":       "webvpn.ynau.edu.cn",
    "utibet":    "webvpn.utibet.edu.cn",     "西藏大学":           "webvpn.utibet.edu.cn",
    "nwu":       "webvpn.nwu.edu.cn",        "西北大学":           "webvpn.nwu.edu.cn",
    "snnu":      "webvpn.snnu.edu.cn",       "陕西师范大学":       "webvpn.snnu.edu.cn",
    "nwafu":     "webvpn.nwafu.edu.cn",      "西北农林科技大学":   "webvpn.nwafu.edu.cn",
    "nwsuaf":    "webvpn.nwafu.edu.cn",
    "xju":       "webvpn.xju.edu.cn",        "新疆大学":           "webvpn.xju.edu.cn",
    "imu":       "webvpn.imu.edu.cn",        "内蒙古大学":         "webvpn.imu.edu.cn",
    "hrbeu":     "webvpn.hrbeu.edu.cn",      "哈尔滨工程大学":     "webvpn.hrbeu.edu.cn",
    "heu":       "webvpn.hrbeu.edu.cn",
    "neau":      "webvpn.neau.edu.cn",       "东北农业大学":       "webvpn.neau.edu.cn",
    "nefu":      "webvpn.nefu.edu.cn",       "东北林业大学":       "webvpn.nefu.edu.cn",
    "lnu":       "webvpn.lnu.edu.cn",        "辽宁大学":           "webvpn.lnu.edu.cn",
    "hlju":      "webvpn.hlju.edu.cn",       "黑龙江大学":         "webvpn.hlju.edu.cn",
    "dufe":      "webvpn.dufe.edu.cn",       "东北财经大学":       "webvpn.dufe.edu.cn",
    "sxu":       "webvpn.sxu.edu.cn",        "山西大学":           "webvpn.sxu.edu.cn",
    "tyut":      "webvpn.tyut.edu.cn",       "太原理工大学":       "webvpn.tyut.edu.cn",
    "hbu":       "webvpn.hbu.edu.cn",        "河北大学":           "webvpn.hbu.edu.cn",
    "ysu":       "webvpn.ysu.edu.cn",        "燕山大学":           "webvpn.ysu.edu.cn",
    # ── Other major universities ──────────────────────────────────────────────
    "ncu":       "webvpn.ncu.edu.cn",        "南昌大学":           "webvpn.ncu.edu.cn",
    "jxnu":      "webvpn.jxnu.edu.cn",       "江西师范大学":       "webvpn.jxnu.edu.cn",
    "gxmu":      "webvpn.gxmu.edu.cn",       "广西医科大学":       "webvpn.gxmu.edu.cn",
    "stu":       "webvpn.stu.edu.cn",        "汕头大学":           "webvpn.stu.edu.cn",
    "csu2":      "webvpn.csust.edu.cn",      "长沙理工大学":       "webvpn.csust.edu.cn",
    "csust":     "webvpn.csust.edu.cn",
    "hbust":     "webvpn.hbust.edu.cn",      "湖北工业大学":       "webvpn.hbust.edu.cn",
    "wzu":       "webvpn.wzu.edu.cn",        "温州大学":           "webvpn.wzu.edu.cn",
    "zjut":      "webvpn.zjut.edu.cn",       "浙江工业大学":       "webvpn.zjut.edu.cn",
    "zjnu":      "webvpn.zjnu.edu.cn",       "浙江师范大学":       "webvpn.zjnu.edu.cn",
    "nbu":       "webvpn.nbu.edu.cn",        "宁波大学":           "webvpn.nbu.edu.cn",
    "hdu":       "webvpn.hdu.edu.cn",        "杭州电子科技大学":   "webvpn.hdu.edu.cn",
    "ahmu":      "webvpn.ahmu.edu.cn",       "安徽医科大学":       "webvpn.ahmu.edu.cn",
    "cmu":       "webvpn.cmu.edu.cn",        "重庆医科大学":       "webvpn.cmu.edu.cn",
    "smmu":      "webvpn.smmu.edu.cn",       "海军军医大学":       "webvpn.smmu.edu.cn",
    "fmmu":      "webvpn.fmmu.edu.cn",       "空军军医大学":       "webvpn.fmmu.edu.cn",
    "imun":      "webvpn.imun.edu.cn",       "内蒙古大学":         "webvpn.imun.edu.cn",
    "sdnu":      "webvpn.sdnu.edu.cn",       "山东师范大学":       "webvpn.sdnu.edu.cn",
    "qdu":       "webvpn.qdu.edu.cn",        "青岛大学":           "webvpn.qdu.edu.cn",
    "ouc2":      "webvpn.ouc.edu.cn",
    "ujinan":    "webvpn.ujn.edu.cn",        "济南大学":           "webvpn.ujn.edu.cn",
    "ujn":       "webvpn.ujn.edu.cn",
    "hebtu":     "webvpn.hebtu.edu.cn",      "河北师范大学":       "webvpn.hebtu.edu.cn",
    "haust":     "webvpn.haust.edu.cn",      "河南科技大学":       "webvpn.haust.edu.cn",
    "henu2":     "webvpn.henu.edu.cn",
    "lntu":      "webvpn.lntu.edu.cn",       "辽宁工程技术大学":   "webvpn.lntu.edu.cn",
    "jlnu":      "webvpn.jlnu.edu.cn",       "吉林农业大学":       "webvpn.jlnu.edu.cn",
    "nmu":       "webvpn.nmu.edu.cn",        "宁夏医科大学":       "webvpn.nmu.edu.cn",
    "nxu":       "webvpn.nxu.edu.cn",        "宁夏大学":           "webvpn.nxu.edu.cn",
    "qhu":       "webvpn.qhu.edu.cn",        "青海大学":           "webvpn.qhu.edu.cn",
    "xzu":       "webvpn.xzu.edu.cn",        "徐州大学":           "webvpn.xzu.edu.cn",
    "dzu":       "webvpn.dzu.edu.cn",        "遵义医科大学":       "webvpn.dzu.edu.cn",
    "kmust":     "webvpn.kmust.edu.cn",      "昆明理工大学":       "webvpn.kmust.edu.cn",
    "ynnu":      "webvpn.ynnu.edu.cn",       "云南师范大学":       "webvpn.ynnu.edu.cn",
}

# Common CNKI WebVPN subdomain patterns for a given VPN domain.
# Most universities follow one of these two formats.
_CNKI_VPN_PATTERNS = [
    "kns-cnki-net-s.{vpn_domain}",   # subdomain format — most common
    "kns.cnki.net.{vpn_domain}",
    "cnki.{vpn_domain}",
]


def probe_vpn_url(school_hint):
    """
    Given a school name or abbreviation, try to find the VPN portal URL.
    Returns (vpn_url, source) or (None, reason).
    """
    key = school_hint.strip().lower()

    # 1. Direct lookup in known list
    if key in _KNOWN_VPN:
        domain = _KNOWN_VPN[key]
        return f"https://{domain}", f"known list ({key})"

    # 2. Try to extract abbreviation from input (e.g. "SCAU" from "华南农业大学(SCAU)")
    import re
    abbr_match = re.search(r'\b([a-zA-Z]{2,8})\b', school_hint)
    if abbr_match:
        abbr = abbr_match.group(1).lower()
        if abbr in _KNOWN_VPN:
            domain = _KNOWN_VPN[abbr]
            return f"https://{domain}", f"known list ({abbr})"

    # 3. Probe common URL patterns using the hint as abbreviation
    candidates = [
        f"https://vpn.{key}.edu.cn",
        f"https://webvpn.{key}.edu.cn",
        f"https://vpn2.{key}.edu.cn",
    ]
    print(f"[VPN probe] Trying common URL patterns for '{school_hint}' ...")
    for url in candidates:
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status < 400:
                print(f"[VPN probe] Responding: {url} (HTTP {resp.status})")
                return url, "auto-probed"
        except Exception:
            pass
        # Also try GET (some portals reject HEAD)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status < 400:
                print(f"[VPN probe] Responding: {url} (HTTP {resp.status})")
                return url, "auto-probed"
        except Exception:
            pass

    return None, "not found"


def suggest_vpn_search(school_hint):
    """Print search suggestions to help user find their VPN URL."""
    print()
    print(f"[Setup] Could not auto-detect VPN URL for '{school_hint}'.")
    print("[Setup] To find your institution's VPN:")
    print(f"  1. Search in browser: \"{school_hint} webvpn\" 或 \"{school_hint} 图书馆VPN\"")
    print(f"  2. Visit your school's IT or library website and look for 'VPN' or '远程访问'")
    print(f"  3. Check your school email for IT onboarding messages with VPN instructions")
    print(f"  4. Ask your library or IT helpdesk: '如何在校外访问知网？'")
    print()


# ── Setup wizard ───────────────────────────────────────────────────────────────
def run_setup_wizard(playwright, school_hint=None):
    """
    Interactive first-time setup. Opens a browser window so the user can log
    in to their institution's VPN and navigate to CNKI. Detects the CNKI
    WebVPN URL pattern automatically and saves config for future headless use.
    """
    print("\n" + "=" * 60)
    print("  lit-search-cite: CNKI First-Time Setup")
    print("=" * 60)
    print()
    print("This wizard configures your institution's VPN for CNKI access.")
    print("Settings are saved to ~/.lit-search-cite/config.json and reused")
    print("automatically — you only need to do this once per machine.")
    print()
    print("Requirement: your institution must provide a WebVPN or library")
    print("portal that routes to CNKI (知网).")
    print()

    # Step 1: get VPN URL — try auto-detection from school hint first
    vpn_url = None

    if school_hint:
        print(f"[Setup] Looking up VPN URL for: {school_hint}")
        guessed, source = probe_vpn_url(school_hint)
        if guessed:
            print(f"[Setup] Found: {guessed}  ({source})")
            ans = input("[Setup] Use this URL? (y / n, or paste a different URL): ").strip()
            if ans.lower() == 'y':
                vpn_url = guessed
            elif ans.lower() != 'n' and ans.startswith("http"):
                vpn_url = ans
            # if 'n', fall through to manual entry below
        else:
            suggest_vpn_search(school_hint)

    if not vpn_url:
        vpn_url = input("Step 1 — Enter your institution's VPN portal URL\n"
                        "  (e.g., https://vpn.pku.edu.cn or https://webvpn.tsinghua.edu.cn)\n"
                        "  Tip: if unsure, search \"[your school] webvpn\" in a browser first.\n"
                        "  URL: ").strip()
    if not vpn_url:
        print("[Setup] No URL provided. Aborting.")
        sys.exit(1)
    if not vpn_url.startswith("http"):
        vpn_url = "https://" + vpn_url

    print()
    print(f"[Setup] Opening browser at: {vpn_url}")
    print("[Setup] Please:")
    print("  a) Log in to your VPN portal")
    print("  b) Navigate to CNKI / 知网 through the VPN portal")
    print("  c) Wait until any CNKI page has loaded in the browser")
    print()
    print("[Setup] Once you are on a CNKI page, come back here and press Enter...")

    # Open browser and navigate to VPN portal
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(user_agent=UA, ignore_https_errors=True)
    page = context.new_page()

    try:
        page.goto(vpn_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"[Setup] Warning: {e}")

    # Wait for user to navigate to CNKI
    input()

    # Step 2: detect CNKI WebVPN base URL
    current_url = page.url
    print(f"[Setup] Detected browser URL: {current_url}")

    cnki_vpn_base = _detect_cnki_vpn_base(current_url)
    if cnki_vpn_base:
        print(f"[Setup] Auto-detected CNKI WebVPN base: {cnki_vpn_base}")
        ans = input("[Setup] Is this correct? (y/n): ").strip().lower()
        if ans != 'y':
            cnki_vpn_base = None

    if not cnki_vpn_base:
        print()
        print("[Setup] Could not auto-detect. The CNKI WebVPN base is the part of")
        print("        the URL before any path — e.g., for a URL like:")
        print("        https://kns-cnki-net-s.vpn.example.edu.cn/kns8/...")
        print("        the base is: https://kns-cnki-net-s.vpn.example.edu.cn")
        cnki_vpn_base = input("  Enter your CNKI WebVPN base URL: ").strip()
        if not cnki_vpn_base.startswith("http"):
            cnki_vpn_base = "https://" + cnki_vpn_base

    # Step 3: optional username hint
    print()
    username = input("Step 2 — VPN username / student ID (optional, used as a login hint).\n"
                     "  Press Enter to skip: ").strip()

    # Save session cookies before closing browser
    save_session(context)
    browser.close()

    # Save config
    config = load_config()
    config["vpn_url"] = vpn_url
    config["cnki_vpn_base"] = cnki_vpn_base.rstrip("/")
    if username:
        config["vpn_username"] = username
    save_config(config)

    print()
    print("[Setup] Done! Configuration saved:")
    print(f"  VPN portal  : {vpn_url}")
    print(f"  CNKI WebVPN : {cnki_vpn_base}")
    print()
    print("Searches will now run headlessly. If your session expires (~7 days):")
    print("  python cnki-playwright.py --login-only --no-headless")
    print("To re-run this wizard:")
    print("  python cnki-playwright.py --setup")
    print()

    return config


def _detect_cnki_vpn_base(url):
    """Auto-detect CNKI WebVPN base URL from a page URL."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if "cnki" in host.lower():
            return f"{parsed.scheme}://{host}"
    except Exception:
        pass
    return None

# ── VPN / CAS helpers ──────────────────────────────────────────────────────────
def ensure_vpn_login(page, vpn_url, username=None, password=None, timeout_sec=120):
    """Navigate to VPN portal and wait for login."""
    print(f"[VPN] Navigating to {vpn_url} ...")
    page.goto(vpn_url, wait_until="domcontentloaded", timeout=30000)

    if _vpn_is_logged_in(page):
        print("[VPN] Session valid (cookie reuse)")
        return True

    if username and password:
        print("[VPN] Attempting credential login ...")
        try:
            page.fill('input[name="username"], #username', username, timeout=5000)
            page.fill('input[name="password"], #password', password, timeout=5000)
            page.click('button[type="submit"], input[type="submit"]', timeout=5000)
            page.wait_for_load_state("networkidle", timeout=15000)
            if _vpn_is_logged_in(page):
                print("[VPN] Credential login successful")
                return True
        except Exception as e:
            print(f"[VPN] Credential login failed: {e}")

    print(f"[VPN] Please log in manually in the browser window.")
    print(f"[VPN] Waiting up to {timeout_sec}s ...")
    try:
        page.wait_for_function(
            """() => {
                const t = document.title;
                return t && t !== '' && !t.includes('统一身份认证') && !t.includes('Login');
            }""",
            timeout=timeout_sec * 1000
        )
        print("[VPN] Login detected")
        return True
    except PlaywrightTimeout:
        print("[VPN] Timed out waiting for login")
        return False


def _vpn_is_logged_in(page):
    try:
        page.wait_for_selector(
            '.sdp-portal-header, .user-avatar, .portal-container, .app-list, '
            '.nav-user-info, #logout, [class*="portal"]',
            timeout=3000
        )
        return True
    except PlaywrightTimeout:
        return False


def handle_cas_login(page, username=None, password=None, timeout_sec=120):
    """Handle CAS / SSO login page if encountered after a VPN redirect."""
    title = page.title()
    url = page.url
    is_cas = ("统一身份认证" in title or "认证中心" in title or
              "cas" in url.lower() or "sso" in url.lower() or
              "authserver" in url.lower() or "ssoserver" in url.lower())
    if not is_cas:
        return

    print(f"[CAS] Detected institutional SSO: {title}")

    if username and password:
        try:
            page.fill('#username, input[name="username"]', username, timeout=5000)
            page.fill('#password, input[name="password"]', password, timeout=5000)
            page.click('#submit-btn, button[type="submit"], input[type="submit"]', timeout=5000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            print(f"[CAS] Login submitted")
            return
        except Exception as e:
            print(f"[CAS] Auto-login failed: {e}")

    print("[CAS] Please complete the institutional SSO login manually.")
    print(f"[CAS] Waiting up to {timeout_sec}s ...")
    try:
        page.wait_for_function(
            """() => !document.title.includes('统一身份认证') && !document.title.includes('认证中心')""",
            timeout=timeout_sec * 1000
        )
        print("[CAS] Login complete")
    except PlaywrightTimeout:
        print("[CAS] Timed out waiting for SSO login.")


def _wait_past_loading(page, timeout_ms=45000):
    """Wait until past bot-detection / loading / security-verification screens."""
    try:
        page.wait_for_function(
            """() => {
                const t = document.title;
                return t && t !== 'Loading...' && t !== '安全验证' && t.length > 0;
            }""",
            timeout=timeout_ms
        )
    except PlaywrightTimeout:
        pass  # proceed anyway; caller will check for results


def _goto_via_js(page, url, timeout_ms=30000):
    """Navigate using JS to avoid ERR_ABORTED on VPN subdomain redirects."""
    try:
        page.evaluate(f"window.location.href = {json.dumps(url)}")
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        try:
            page.goto(url, wait_until="commit", timeout=timeout_ms)
        except Exception as e:
            if "ERR_ABORTED" not in str(e):
                raise
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)


def _open_cnki_from_portal(page, config, username=None, password=None):
    """
    Warm up the VPN tunnel by visiting the portal first, then navigate to CNKI.
    Handles institutional SSO redirects that appear en route.
    """
    vpn_url      = config["vpn_url"]
    cnki_vpn_base = config["cnki_vpn_base"]

    print("[VPN] Initializing VPN tunnel via portal ...")
    try:
        page.goto(vpn_url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        err = str(e)
        if "interrupted by another navigation" not in err and "ERR_ABORTED" not in err:
            raise
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    handle_cas_login(page, username, password)

    # Try to find a CNKI link in the portal app list
    try:
        sel = 'a[href*="cnki"], a:text-matches("知网|CNKI", "i")'
        href = page.locator(sel).first.get_attribute("href", timeout=4000)
        if href:
            print("[VPN] Found CNKI portal link — clicking ...")
            page.click(sel, timeout=4000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            handle_cas_login(page, username, password)
            _wait_past_loading(page)
            return
    except Exception:
        pass

    # Fallback: JS-navigate directly to CNKI through WebVPN
    target = f"{cnki_vpn_base}/kns8/defaultresult/index"
    print("[VPN] Portal link not found — JS-navigating to CNKI ...")
    _goto_via_js(page, target)
    handle_cas_login(page, username, password)
    _wait_past_loading(page)

# ── Search ─────────────────────────────────────────────────────────────────────
def search_cnki(page, config, query, limit=20, db="SCDB", username=None, password=None):
    """Search CNKI and return structured results."""
    _open_cnki_from_portal(page, config, username, password)

    cnki_vpn_base = config["cnki_vpn_base"]
    encoded    = quote(query)
    search_url = f"{cnki_vpn_base}/kns8/defaultresult/index?kw={encoded}&korder=td&db={db}"
    print("[CNKI] Navigating to search results ...")
    _goto_via_js(page, search_url)
    _wait_past_loading(page, timeout_ms=8000)
    handle_cas_login(page, username, password)
    _wait_past_loading(page)

    try:
        page.wait_for_selector(
            '.result-table-list tbody tr, '
            '.GridTableContent tr[onmouseover], '
            '#gridTable tbody tr',
            timeout=20000
        )
    except PlaywrightTimeout:
        title = page.title()
        print(f"[CNKI] Results table not found. Page title: {title!r}")
        debug_path = STATE_FILE.parent / "cnki_debug.png"
        page.screenshot(path=str(debug_path))
        print(f"[CNKI] Debug screenshot saved: {debug_path}")
        return []

    results = page.evaluate("""(limit) => {
        const selectors = [
            '.result-table-list tbody tr',
            '.GridTableContent tr[onmouseover]',
            '#gridTable tbody tr'
        ];
        let rows = [];
        for (const sel of selectors) {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) { rows = Array.from(found); break; }
        }
        const items = [];
        for (let i = 0; i < Math.min(rows.length, limit); i++) {
            const row = rows[i];
            const titleEl  = row.querySelector('.name a, td.name a, a[href*="detail"]');
            const authorEl = row.querySelector('.author, td.author');
            const sourceEl = row.querySelector('.source, td.source');
            const dateEl   = row.querySelector('.date, td.date');
            const citeEl   = row.querySelector('.quote, td.quote, .cite-num');
            const dbEl     = row.querySelector('.data, td.data, .database');
            if (titleEl && titleEl.innerText.trim()) {
                items.push({
                    title:     titleEl.innerText.trim(),
                    href:      titleEl.href || '',
                    author:    authorEl ? authorEl.innerText.replace(/\\s+/g,' ').trim() : '',
                    journal:   sourceEl ? sourceEl.innerText.trim() : '',
                    year:      dateEl   ? dateEl.innerText.trim().substring(0, 4) : '',
                    citations: citeEl   ? citeEl.innerText.replace(/[^0-9]/g,'') || '0' : '0',
                    database:  dbEl     ? dbEl.innerText.trim() : ''
                });
            }
        }
        return items;
    }""", limit)

    try:
        count_text = page.locator('.pagerTitleCell, .search-result-header, #countId').first.inner_text(timeout=3000)
        print(f"[CNKI] Total results: {count_text.strip()}")
    except Exception:
        pass

    print(f"[CNKI] Extracted {len(results)} papers")
    return results

# ── PDF download ───────────────────────────────────────────────────────────────
def download_pdf(page, paper_href, output_dir=".", username=None, password=None):
    """Navigate to a CNKI paper detail page and attempt PDF download."""
    if not paper_href:
        return None

    print("[PDF] Opening paper detail page ...")
    # Navigate via the page context to preserve CNKI session cookies
    try:
        page.goto(paper_href, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        page.goto(paper_href, wait_until="load", timeout=25000)
    page.wait_for_timeout(5000)
    _wait_past_loading(page)
    handle_cas_login(page, username, password)

    title = page.title()
    if "安全验证" in title or "验证" in title:
        print("[PDF] CNKI CAPTCHA detected — waiting for manual solve (up to 60s)...")
        try:
            page.wait_for_function(
                """() => !document.title.includes('安全验证')""",
                timeout=60000
            )
            page.wait_for_timeout(3000)
        except:
            print("[PDF] CAPTCHA not solved — only --no-headless with manual interaction works")
            return None

    # Strategy: find any download link on the page
    all_links = page.locator("a").all()
    pdf_url = None
    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            text = (link.inner_text() or "").strip()
            onclick = link.get_attribute("onclick") or ""
            if ".pdf" in href.lower() or "pdf/ads" in href or "download/order" in href:
                pdf_url = href
                break
            if "下载" in text and (href or onclick):
                pdf_url = href or onclick
                break
        except:
            pass
    
    if pdf_url and (pdf_url.startswith("http") or pdf_url.startswith("/")):
        base = "/".join(page.url.split("/")[:3])  # e.g. https://kns-cnki-net-s.vpn.scau.edu.cn
        if pdf_url.startswith("/"):
            pdf_url = f"{base}{pdf_url}"
        print(f"[PDF] Found PDF link: {pdf_url[:80]}...")
        import urllib.parse
        # Download via browser session to keep VPN cookies
        resp = page.evaluate("""async (url) => {
            const r = await fetch(url);
            const blob = await r.blob();
            const reader = new FileReader();
            return new Promise((resolve) => {
                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                reader.readAsDataURL(blob);
            });
        }""", pdf_url)
        import base64, urllib.parse
        pdf_bytes = base64.b64decode(resp)
        fname = urllib.parse.urlparse(pdf_url).path.split("/")[-1] or "cnki_paper.pdf"
        if not fname.endswith(".pdf"):
            fname += ".pdf"
        dest = Path(output_dir) / fname
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf_bytes)
        print(f"[PDF] Saved: {dest} ({len(pdf_bytes)} bytes)")
        return str(dest)

    # Fallback: use CSS selectors for clickable download buttons
    pdf_btn_sel = (
        'a:has-text("PDF"), '
        'a:has-text("下载"), '
        'a[href*="pdf/ads/v1/pdf/"], '
        'a[href*="download/order"], '
        'a[onclick*="DownLoad"]'
    )
    try:
        btn = page.locator(pdf_btn_sel).first
        btn.wait_for(timeout=8000)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # CNKI downloads may trigger: direct download, navigation to PDF URL, or new window
        btn_href = btn.get_attribute("href")
        if btn_href and btn_href.endswith(".pdf"):
            # Direct PDF link — download via requests
            import urllib.request
            fname = btn_href.split("/")[-1] or "cnki_paper.pdf"
            dest = output_path / fname
            urllib.request.urlretrieve(btn_href, str(dest))
            print(f"[PDF] Saved: {dest}")
            return str(dest)

        # Try Playwright download event (triggers on standard download buttons)
        with page.expect_download(timeout=30000) as dl_info:
            btn.click()
        download = dl_info.value
        fname = download.suggested_filename or "cnki_paper.pdf"
        dest  = output_path / fname
        download.save_as(str(dest))
        print(f"[PDF] Saved: {dest}")
        return str(dest)

    except PlaywrightTimeout:
        # Debug: save page content to understand what's on the page
        page.screenshot(path=str(Path(output_dir) / "cnki_debug.png"), full_page=False)
        print("[PDF] No PDF download button found — saved debug screenshot")
        return None
    except Exception as e:
        print(f"[PDF] Download error: {e}")
        return None

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="CNKI search + PDF download via Playwright.\n"
                    "Config: ~/.lit-search-cite/config.json\n"
                    "Session: ~/.lit-search-cite/cnki_session.json"
    )
    parser.add_argument("--query",       "-q", help="Search query (Chinese or English)")
    parser.add_argument("--limit",       "-n", type=int, default=20, help="Max results (default 20)")
    parser.add_argument("--db",                default="SCDB", help="CNKI database code (default SCDB = all)")
    parser.add_argument("--output",      "-o", default=".", help="PDF output directory")
    parser.add_argument("--json-output", "-j", help="Save results to JSON file")
    parser.add_argument("--download",    "-d", action="store_true", help="Download PDFs for top 5 results")
    parser.add_argument("--setup",             action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--school",            help="School name or abbreviation for VPN auto-detection (e.g. scau, pku, 清华大学)")
    parser.add_argument("--login-only",        action="store_true", help="Login and save session only (no search)")
    parser.add_argument("--no-headless",       action="store_true", help="Show browser window (default: headless)")
    parser.add_argument("--username",    "-u", help="VPN username (overrides saved config)")
    parser.add_argument("--password",    "-p", help="VPN password")
    args = parser.parse_args()

    with sync_playwright() as pw:

        # ── Force re-setup ────────────────────────────────────────────────────
        if args.setup:
            run_setup_wizard(pw, school_hint=args.school)
            return

        # ── Load config; auto-setup on first run ──────────────────────────────
        config = load_config()
        if not is_configured(config):
            print("[cnki-playwright] No configuration found. Starting first-time setup ...")
            config = run_setup_wizard(pw)

        vpn_url  = config["vpn_url"]
        username = args.username or config.get("vpn_username") or None
        password = args.password or None

        # ── Login only (session refresh) ──────────────────────────────────────
        if args.login_only:
            browser = pw.chromium.launch(headless=False)
            state_path = get_session_path()
            ctx_opts = {"user_agent": UA, "ignore_https_errors": True}
            if state_path:
                ctx_opts["storage_state"] = state_path
                print("[session] Loading saved session")
            context = browser.new_context(**ctx_opts)
            page    = context.new_page()
            ok = ensure_vpn_login(page, vpn_url, username, password)
            if not ok:
                print("[ERROR] VPN login failed.")
                browser.close()
                sys.exit(1)
            # Navigate to CNKI so session includes CNKI cookies (avoids 安全验证 on headless runs)
            print("[Login] Navigating to CNKI to warm up session cookies ...")
            _open_cnki_from_portal(page, config, username, password)
            save_session(context)
            print("[Done] Session saved with CNKI cookies. Future headless runs will reuse them.")
            browser.close()
            return

        # ── Search ────────────────────────────────────────────────────────────
        if not args.query:
            print("[ERROR] Provide --query to search, --login-only to refresh session, "
                  "or --setup to reconfigure.")
            sys.exit(1)

        state_path = get_session_path()
        headless   = not args.no_headless and state_path is not None

        browser  = pw.chromium.launch(headless=headless)
        ctx_opts = {"user_agent": UA, "ignore_https_errors": True}
        if state_path:
            ctx_opts["storage_state"] = state_path
            print("[session] Loading saved session")

        context = browser.new_context(**ctx_opts)
        page    = context.new_page()

        ok = ensure_vpn_login(page, vpn_url, username, password)
        if not ok:
            print("[ERROR] VPN login failed.")
            print("Re-run: python cnki-playwright.py --login-only --no-headless")
            browser.close()
            sys.exit(1)

        save_session(context)

        results = search_cnki(page, config, args.query, args.limit, args.db, username, password)

        if not results:
            print("[CNKI] No results returned.")
            browser.close()
            sys.exit(0)

        print(f"\n{'='*60}")
        print(f"Results ({len(results)}) for: {args.query}")
        print('='*60)
        for i, r in enumerate(results, 1):
            print(f"\n[{i}] {r['title']}")
            if r['author']:    print(f"    Authors  : {r['author']}")
            if r['journal']:   print(f"    Journal  : {r['journal']}  ({r['year']})")
            if r['citations']: print(f"    Citations: {r['citations']}")
            if r['href']:      print(f"    Link     : {r['href']}")

        if args.download:
            print(f"\n[PDF] Downloading top {min(5, len(results))} papers ...")
            for r in results[:5]:
                download_pdf(page, r['href'], args.output)

        if args.json_output:
            with open(args.json_output, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n[JSON] Saved {len(results)} results to {args.json_output}")

        save_session(context)
        browser.close()


if __name__ == "__main__":
    main()
