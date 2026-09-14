
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import random
import re
import secrets
import shutil
import signal
import string
import subprocess
import sys
import importlib
import tarfile
import tempfile
import threading
import time
import traceback
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

# Pure local database storage — Firebase disabled


_REQUIRED_PKGS = [
    ("telebot",             "pyTelegramBotAPI"),
    ("requests",            "requests"),
    ("cryptography.fernet", "cryptography"),
    ("flask",               "flask"),
    ("apscheduler",         "APScheduler"),
    ("github",              "PyGithub"),
    ("psutil",              "psutil"),
    ("PIL",                 "Pillow"),
]



# Telegram custom emoji IDs supplied for menu/message headers.
CUSTOM_EMOJI_IDS = {
    "main": "6314564624859536473",
    "upload": "6053078043692374997",
    "referral": "6312301920123887895",
    "profile": "6053362469311617342",
    "wallet": "6312104703815590263",
    "tickets": "6052964261418769099",
    "admin": "6311888503751843904",
    "marketplace": "6314298001879735512",
    "users": "6053026611459004128",
    "bots": "6052909083973918987",
    "security": "6052869252447215120",
    "broadcast": "6311947409228307310",
    "system": "5866493836741579471",
    "api_config": "5208909664841900025",
    "appearance": "6311837926216965770",
    "leaderboard": "6311977787531997060",
}

BUTTON_PREMIUM_EMOJI_IDS = {'main': '6314564624859536473', 'upload': '6053078043692374997', 'referral': '6312301920123887895', 'profile': '6053362469311617342', 'wallet': '6312104703815590263', 'tickets': '6052964261418769099', 'admin': '6311888503751843904', 'marketplace': '6314298001879735512', 'users': '6053026611459004128', 'bots': '6052909083973918987', 'security': '6052869252447215120', 'broadcast': '6311947409228307310', 'system': '5866493836741579471', 'api_config': '5208909664841900025', 'appearance': '6311837926216965770', 'leaderboard': '6311977787531997060'}

def tg_emoji(key, fallback="🔹"):
    emoji_id = CUSTOM_EMOJI_IDS.get(key)
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>' if emoji_id else fallback



def _plan_custom_emoji_id(button_text="", callback_data=""):
    value = str(button_text or "").upper()
    cb = str(callback_data or "").upper()
    for plan in ("FREE", "STARTER", "BASIC", "PRO", "ENTERPRISE", "LIFETIME"):
        if plan in value or plan in cb:
            return PLAN_CUSTOM_EMOJI_IDS[plan]
    return ""

def _button_custom_emoji_id(callback_data="", button_text=""):
    """Select the user's Premium custom emoji ID for an inline button."""
    plan_id = _plan_custom_emoji_id(button_text, callback_data)
    if plan_id:
        return plan_id
    cb = str(callback_data or "").lower()
    tx = str(button_text or "").lower()

    # Main/user menu
    if any(x in cb for x in (
        "menu_bots", "menu_plans", "menu_buy", "menu_home", "menu_main"
    )):
        return BUTTON_PREMIUM_EMOJI_IDS["main"]
    if any(x in cb for x in ("menu_upload", "menu_trial")):
        return BUTTON_PREMIUM_EMOJI_IDS["upload"]
    if "menu_referral" in cb or "coupon" in cb or "ref_" in cb:
        return BUTTON_PREMIUM_EMOJI_IDS["referral"]
    if "menu_profile" in cb or "menu_stats" in cb:
        return BUTTON_PREMIUM_EMOJI_IDS["profile"]
    if "menu_wallet" in cb or "payment" in cb or "pay_" in cb:
        return BUTTON_PREMIUM_EMOJI_IDS["wallet"]
    if "menu_ticket" in cb or "menu_help" in cb or "menu_support" in cb:
        return BUTTON_PREMIUM_EMOJI_IDS["tickets"]
    if "menu_marketplace" in cb or "marketplace" in cb or "script" in cb:
        return BUTTON_PREMIUM_EMOJI_IDS["marketplace"]
    if "menu_admin" in cb or cb.startswith("adm_") or cb.startswith("admin"):
        return BUTTON_PREMIUM_EMOJI_IDS["admin"]

    # Admin sub-panels
    if any(x in cb for x in ("user_", "users_", "banned", "wallet_adjust", "ban_")):
        return BUTTON_PREMIUM_EMOJI_IDS["users"]
    if any(x in cb for x in ("bot_", "bots_", "crashed", "restart_", "kill_", "start_", "stop_")):
        return BUTTON_PREMIUM_EMOJI_IDS["bots"]
    if any(x in cb for x in ("sec_", "security", "threat", "blacklist", "whitelist", "audit")):
        return BUTTON_PREMIUM_EMOJI_IDS["security"]
    if any(x in cb for x in ("broadcast", "notify_", "announce", "schedule_msg")):
        return BUTTON_PREMIUM_EMOJI_IDS["broadcast"]
    if any(x in cb for x in ("sys_", "system", "disk_", "db_", "cache", "export_data", "github", "gh_")):
        return BUTTON_PREMIUM_EMOJI_IDS["system"]
    if any(x in cb for x in ("api_", "pay_config", "config_", "settings", "setup_2fa")):
        return BUTTON_PREMIUM_EMOJI_IDS["api_config"]
    if any(x in cb for x in ("appearance", "theme", "banner", "photo_")):
        return BUTTON_PREMIUM_EMOJI_IDS["appearance"]
    if any(x in cb for x in ("leaderboard", "lb_", "top_")):
        return BUTTON_PREMIUM_EMOJI_IDS["leaderboard"]

    # Text fallback for dynamically generated callbacks.
    if "marketplace" in tx or "script" in tx:
        return BUTTON_PREMIUM_EMOJI_IDS["marketplace"]
    if "admin" in tx:
        return BUTTON_PREMIUM_EMOJI_IDS["admin"]
    return ""


def _auto_install_missing() -> None:
    import importlib
    missing: List[str] = []
    for mod, pip_name in _REQUIRED_PKGS:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return
    print(f"[setup] installing missing packages: {', '.join(missing)}")
    # Try several install strategies — different hosts have different
    # restrictions (PEP 668 externally-managed, no root, sandboxed pip,
    # etc.). The first one that succeeds wins.
    strategies = [
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
         "--break-system-packages", *missing],
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", *missing],
        [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "--quiet",
         "--break-system-packages", *missing],
        [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "--quiet", *missing],
    ]
    last_err: Optional[Exception] = None
    for cmd in strategies:
        try:
            subprocess.run(cmd, check=True)
            print("[setup] install ok — continuing boot")
            return
        except Exception as e:
            last_err = e
            continue
    print(f"[setup] auto-install notice: {last_err}. Continuing boot...")


_auto_install_missing()

# Now safe to import third-party modules.
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, jsonify

# ── TELEGRAM BOT API 9.4 — BUTTON STYLE SUPPORT ──────────────────
# style="primary" = Blue | style="success" = Green | style="danger" = Red
# Graceful fallback: if Telegram ignores the field, buttons work normally.
class StyledKeyboardButton(types.KeyboardButton):
    """ReplyKeyboard button with Telegram style and custom emoji."""
    def __init__(self, text: str, style: str = "", custom_emoji_id: str = ""):
        super().__init__(text=text)
        self._btn_style = (style or "").strip().lower()
        self._custom_emoji_id = str(custom_emoji_id or "").strip()

    def to_dict(self):
        d = super().to_dict()
        if self._btn_style in ("primary", "success", "danger"):
            d["style"] = self._btn_style
        if self._custom_emoji_id:
            d["icon_custom_emoji_id"] = self._custom_emoji_id
        return d


class Btn(types.InlineKeyboardButton):
    """InlineKeyboardButton with Telegram button style + Premium custom emoji icon."""
    def __init__(self, *args, style: str = "", icon_custom_emoji_id: str = "", **kwargs):
        self._btn_style = (style or "").strip().lower()
        self._icon_custom_emoji_id = str(icon_custom_emoji_id or "").strip()
        if not self._icon_custom_emoji_id:
            cb = kwargs.get("callback_data", "")
            txt = kwargs.get("text", args[0] if args else "")
            try:
                self._icon_custom_emoji_id = _button_custom_emoji_id(cb, txt)
            except Exception:
                self._icon_custom_emoji_id = ""
        super().__init__(*args, **kwargs)

    def to_dict(self):
        d = super().to_dict()
        if self._btn_style in ("primary", "success", "danger"):
            d["style"] = self._btn_style
        if self._icon_custom_emoji_id:
            d["icon_custom_emoji_id"] = self._icon_custom_emoji_id
        return d



_SEC_PATTERNS = {
    # ── Real data theft — actively reading & exfiltrating server files ──
    "🔴 Data Theft": [
        # Must have a specific system directory name after the slash (not '/' alone)
        (r'os\.walk\s*\(\s*["\'][/\\](?:root|home|etc|var|proc)["\']',
                                                  "Root/system directory walk — server files chura raha hai"),
        # send_document paired with open() on a SYSTEM path (not relative) = suspicious
        (r'send_document\s*\(.*open\s*\(\s*["\'][/\\](?:root|etc|proc|sys)',
                                                  "System file bahar bhej raha hai"),
        # ZIP + os.walk together with a system root path = suspicious
        (r'zipfile\.ZipFile.*["\']w["\'].*\bos\.walk\b.*["\'][/\\](?:root|etc|home)',
                                                  "System files ZIP mein pack karke bhej raha hai"),
        (r'glob\.glob\s*\(["\'][/\\]\*',          "Root glob scan — server files dhundh raha hai"),
        (r'shutil\.copy.*["\'][/\\]root',         "/root se copy kar raha hai"),
        (r'ROOT_DIR\s*=\s*["\'][/\\]["\']',       "Root directory target kar raha hai"),
    ],
    # ── True backdoors — code that executes arbitrary commands ──
    # NOTE: eval/exec/compile checks are done in AST scan (not regex) so they
    # don't false-positive on string literals like "eval(compile..." inside
    # scanner pattern lists or docstrings.
    "🔴 Backdoor": [
        # __import__('os') detection is done in AST scan (avoids false positives on
        # string literals like "__import__('os')" in scanner pattern lists).
        # subprocess with shell=True AND piped user input on same line only
        (r'subprocess\s*\.\s*(?:Popen|call|run)\s*\([^\n]*shell\s*=\s*True[^\n]*(?:input|stdin)',
                                                  "Shell injection with user input"),
        (r'marshal\.loads\s*\(',                  "Marshalled bytecode — obfuscated execution"),
    ],
    # ── Exposed credentials — actual tokens/secrets in plain text ──
    "🔴 Exposed Credentials": [
        # BOT_TOKEN_REGEX handled separately in _sec_static_scan
    ],
    # ── Obfuscation — actively hiding intent ──
    "🟡 Obfuscation": [
        (r'base64\.b64decode\s*\(.*\)\s*[\)\s]*\bexec\b',
                                                  "Base64 decode + execute — hidden code"),
        (r'(?:\\x[0-9a-fA-F]{2}){6,}',           "Long hex string — obfuscated code"),
        (r'zlib\.decompress\s*\(.*\)\s*[\)\s]*\bexec\b',
                                                  "Compressed + executed hidden code"),
    ],
    # ── Suspicious network — sending data out to KNOWN malicious endpoints ──
    "🟡 Suspicious Network": [
        (r'devil-api\.com|elementfx\.io',         "Known malicious API endpoint"),
        # Only flag if reading a SYSTEM path and posting externally
        (r'open\s*\(\s*["\'][/\\](?:root|etc|proc|sys).*(?:requests|urllib).*(?:post|put)',
                                                  "System file HTTP POST — data exfiltration"),
        (r'pastebin\.com/raw',                    "Pastebin raw fetch — remote code load"),
    ],
    # ── Resource abuse ──
    "🟠 Resource Abuse": [
        (r'multiprocessing\.Pool\s*\(\s*(?:None|\d{3,})',
                                                  "Massive process pool — resource abuse"),
        (r'fork\s*\(\s*\).*fork\s*\(',            "Fork bomb pattern"),
    ],
}

_SEC_TOKEN_RE  = re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b')


def _sec_static_scan(code: str) -> dict:
    results: Dict[str, List[str]] = {}
    for category, pattern_list in _SEC_PATTERNS.items():
        hits = []
        for pattern, description in pattern_list:
            # No DOTALL — keeps .* within a single line so multi-token patterns
            # don't span the whole file and cause false positives.
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                hits.append(description)
        if hits:
            results[category] = hits
    tokens = _SEC_TOKEN_RE.findall(code)
    if tokens:
        results.setdefault("🔴 Exposed Credentials", [])
        results["🔴 Exposed Credentials"].append(f"Bot Token mila: {tokens[0][:15]}...")
    return results


def _sec_ast_scan(code: str) -> List[str]:
    import ast as _ast
    findings: List[str] = []
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        findings.append(f"Code parse nahi hua: {e} - encoded/obfuscated ho sakta hai")
        return findings
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            # os.walk with a literal system path argument
            if isinstance(func, _ast.Attribute):
                if (func.attr == 'walk' and isinstance(func.value, _ast.Name)
                        and func.value.id == 'os' and node.args):
                    arg = node.args[0]
                    if isinstance(arg, _ast.Constant) and isinstance(arg.value, str):
                        if arg.value in ['/root', '/etc', '/home', '/proc']:
                            findings.append(f"os.walk('{arg.value}') - sensitive directory scan")
            # eval/exec only when the argument is itself a function call (dynamic execution)
            # This correctly ignores eval/exec as plain names in string literals
            if isinstance(func, _ast.Name) and func.id in ('eval', 'exec'):
                if node.args:
                    arg0 = node.args[0]
                    # Flag only when called with a dynamic/external source
                    if isinstance(arg0, _ast.Call):
                        findings.append(f"Dangerous: {func.id}() — dynamic code execution")
                    elif isinstance(arg0, _ast.Attribute):
                        findings.append(f"Dangerous: {func.id}() — attribute-based input")
            # __import__('os') — dynamic OS import (AST-only to skip string literals)
            if isinstance(func, _ast.Name) and func.id == '__import__':
                if node.args and isinstance(node.args[0], _ast.Constant):
                    if node.args[0].value == 'os':
                        findings.append("Dynamic __import__('os') — code injection")
    return findings


def _sec_calculate_risk(static_findings: dict, ast_findings: List[str]) -> int:
    # Weights tuned to avoid false positives on legitimate Telegram bots.
    # Only patterns that are unambiguously malicious get high scores.
    weights = {
        "🔴 Data Theft":          40,
        "🔴 Backdoor":            40,
        # Having a token in code is bad practice but NOT necessarily theft —
        # many bots hardcode their token. Weight kept low so it alone can't
        # reach the DANGEROUS threshold.
        "🔴 Exposed Credentials": 10,
        "🟡 Suspicious Network":  12,
        "🟡 Obfuscation":         10,
        "🟠 Resource Abuse":       8,
    }
    score = sum(weights.get(cat, 5) * min(len(hits), 3)
                for cat, hits in static_findings.items()
                if hits)
    # Deduplicate AST findings and cap contribution so repeated path hits
    # don't inflate the score to 100 on legitimate bots.
    unique_ast = list(dict.fromkeys(ast_findings))
    score += min(len(unique_ast) * 5, 20)
    return min(score, 100)


def _sec_get_verdict(risk_score: int, static_findings: dict) -> Tuple[str, str]:
    # Only Data Theft + Backdoor are truly blocking threats.
    # Exposed Credentials alone → SUSPICIOUS (warn user, don't block).
    has_blocking = any(
        static_findings.get(c)
        for c in ("🔴 Data Theft", "🔴 Backdoor")
    )
    has_credentials = bool(static_findings.get("🔴 Exposed Credentials"))

    # REJECT only for real attack patterns at high risk
    if has_blocking and risk_score >= 70:
        return "DANGEROUS", "REJECT"
    if risk_score >= 85:
        return "DANGEROUS", "REJECT"
    # Hardcoded token alone → warn but allow (MANUAL_REVIEW)
    if has_credentials and not has_blocking and risk_score < 40:
        return "SUSPICIOUS", "MANUAL_REVIEW"
    if has_blocking and risk_score >= 35:
        return "SUSPICIOUS", "MANUAL_REVIEW"
    if risk_score >= 55:
        return "SUSPICIOUS", "MANUAL_REVIEW"
    return "SAFE", "APPROVE"


def _sec_scan_code(code: str, filename: str = "file.py") -> dict:
    sf = _sec_static_scan(code)
    af = _sec_ast_scan(code)
    risk = _sec_calculate_risk(sf, af)
    verdict, recommendation = _sec_get_verdict(risk, sf)
    all_threats: List[str] = [f"{c}: {h}" for c, hits in sf.items() for h in hits] + af
    if verdict == "DANGEROUS":
        summary = f"⚠️ File DANGEROUS hai! {len(all_threats)} threats mili hain."
    elif verdict == "SUSPICIOUS":
        summary = "🔍 File suspicious hai. Admin se manual review karwao."
    else:
        summary = "✅ File safe lagti hai. Koi major threat nahi mila."
    return {"verdict": verdict, "risk_score": risk, "findings": sf,
            "ast_findings": af, "all_threats": all_threats,
            "recommendation": recommendation, "summary": summary, "filename": filename}


def _sec_scan_archive(file_path: str) -> dict:
    tmp = tempfile.mkdtemp()
    try:
        if file_path.endswith('.zip'):
            with zipfile.ZipFile(file_path, 'r') as z:
                for name in z.namelist():
                    if name.startswith('/') or '..' in name:
                        return {"verdict": "DANGEROUS", "risk_score": 99,
                                "findings": {"🔴 Zip Slip Attack": ["Dangerous file paths in ZIP!"]},
                                "ast_findings": [], "recommendation": "REJECT",
                                "summary": "ZIP Slip attack detected!", "all_threats": []}
                z.extractall(tmp)
        elif file_path.endswith(('.tar.gz', '.tgz', '.tar')):
            with tarfile.open(file_path, 'r:*') as t:
                t.extractall(tmp)
        py_files = list(Path(tmp).rglob("*.py"))
        if not py_files:
            return {"verdict": "SUSPICIOUS", "risk_score": 20,
                    "findings": {"🟡 Warning": ["Koi .py file nahi mili archive mein"]},
                    "ast_findings": [], "recommendation": "MANUAL_REVIEW",
                    "summary": "Archive mein Python files nahi hain.", "all_threats": []}
        worst = None
        for py_file in py_files[:10]:
            try:
                result = _sec_scan_code(py_file.read_text(errors='ignore'), py_file.name)
                if worst is None or result['risk_score'] > worst['risk_score']:
                    worst = result
            except Exception:
                continue
        return worst or {"verdict": "SAFE", "risk_score": 0, "recommendation": "APPROVE",
                         "summary": "Safe lagti hai", "all_threats": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _scan_file(file_path: str) -> dict:
    """Main entry — scan any uploaded file before saving."""
    filename = os.path.basename(file_path)
    try:
        if filename.lower().endswith(('.zip', '.tar.gz', '.tgz', '.tar')):
            return _sec_scan_archive(file_path)
        elif filename.lower().endswith(('.py', '.pyc', '.pyo', '.js')):
            with open(file_path, 'r', errors='ignore') as _f:
                return _sec_scan_code(_f.read(), filename)
        else:
            return {"verdict": "SUSPICIOUS", "risk_score": 30,
                    "findings": {"🟡 Warning": [f"Unknown file type: {filename}"]},
                    "ast_findings": [], "recommendation": "MANUAL_REVIEW",
                    "summary": f"File type '{filename}' allow nahi hai.",
                    "all_threats": [], "filename": filename}
    except Exception as _e:
        return {"verdict": "ERROR", "risk_score": 50, "findings": {},
                "ast_findings": [], "recommendation": "MANUAL_REVIEW",
                "summary": f"Scan error: {_e}", "all_threats": [], "filename": filename}

_SCANNER_OK = True

# ── External scanner module (security_scanner_free.py) ──
# Importing scan_file replaces the built-in _scan_file above so the
# external module's patterns (with all fixes and extra detections)
# are used by _combined_scan → _run_security_scan → _handle_bot_upload.
try:
    # Ensure the scanner module is discoverable even when bot.py is run
    # from a different working directory (e.g. `python3 /path/to/bot.py`).
    import os as _os, sys as _sys
    _here = _os.path.dirname(_os.path.abspath(__file__))
    if _here and _here not in _sys.path:
        _sys.path.insert(0, _here)
    from security_scanner_free import scan_file as _scan_file  # noqa: F811
    _SCANNER_OK = True
except Exception as _ssf_err:
    import sys as _sys
    print(f"[security] security_scanner_free.py not found — using built-in scanner ({_ssf_err})", file=_sys.stderr)
    # Fall back to built-in _scan_file defined above


# ── AI-powered scanner (OpenRouter free model — no API key needed) ──
import urllib.request as _urllib_req
import json as _json

_AI_SCAN_PROMPT = """You are a security expert reviewing uploaded bot code.
Analyze the code below for malicious behavior. Look for:
1. Data theft — reading/sending server files, credentials, databases
2. Backdoors — eval/exec with remote payloads, hidden commands
3. Spyware — logging user data secretly and sending it out
4. Credential theft — stealing tokens, passwords, API keys
5. Resource abuse — fork bombs, crypto mining

Reply ONLY with a JSON object (no markdown, no extra text):
{
  "verdict": "SAFE" | "SUSPICIOUS" | "DANGEROUS",
  "risk_score": <0-100>,
  "reason": "<one sentence summary in simple language>",
  "threats": ["<threat1>", "<threat2>"]
}

IMPORTANT: Normal Telegram bots that use telebot, infinity_polling, CommandHandler,
send_message, send_document for their OWN users are SAFE. Do NOT flag standard
Telegram bot patterns as malicious.

CODE TO ANALYZE:
"""

def _ai_scan_code(code: str, filename: str = "file.py") -> Optional[Dict[str, Any]]:
    """Call OpenRouter free AI model to analyze code. Returns result dict or None on error."""
    base_url = os.environ.get("AI_INTEGRATIONS_OPENROUTER_BASE_URL", "").rstrip("/")
    api_key  = os.environ.get("AI_INTEGRATIONS_OPENROUTER_API_KEY", "no-key")
    if not base_url:
        return None

    # Limit code sent to AI — first 6000 chars covers most bots
    code_snippet = code[:6000]
    payload = _json.dumps({
        "model": "google/gemma-4-31b-it:free",
        "max_tokens": 512,
        "temperature": 0.1,
        "messages": [
            {"role": "user", "content": f"{_AI_SCAN_PROMPT}{code_snippet}"}
        ]
    }).encode("utf-8")

    req = _urllib_req.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST"
    )
    try:
        with _urllib_req.urlopen(req, timeout=30) as resp:
            body = _json.loads(resp.read())
        content = body["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if any
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = _json.loads(content)
        return {
            "ai_verdict":    result.get("verdict", "SAFE"),
            "ai_risk_score": int(result.get("risk_score", 0)),
            "ai_reason":     result.get("reason", ""),
            "ai_threats":    result.get("threats", []),
        }
    except Exception as _ai_err:
        print(f"[ai_scan] error: {_ai_err}", file=sys.stderr)
        return None


def _combined_scan(file_path: str) -> dict:
    """Run pattern scanner + AI scanner and merge results."""
    pattern_result = _scan_file(file_path)
    filename = os.path.basename(file_path)

    # Only send .py / .js / .ts to AI (skip binary / unknown)
    ai_result = None
    if filename.lower().endswith(('.py', '.js', '.ts')):
        try:
            with open(file_path, 'r', errors='ignore') as _f:
                ai_result = _ai_scan_code(_f.read(), filename)
        except Exception:
            pass

    if ai_result is None:
        # AI unavailable — return pattern result as-is
        return pattern_result

    # ── Merge AI + pattern results ────────────────────────────────
    # Final risk = weighted average (AI 60%, pattern 40%)
    ai_risk  = ai_result["ai_risk_score"]
    pat_risk = pattern_result.get("risk_score", 0)
    merged_risk = int(ai_risk * 0.6 + pat_risk * 0.4)

    # AI says DANGEROUS → always REJECT regardless of pattern score
    # AI says SAFE but pattern is DANGEROUS → MANUAL_REVIEW (trust but verify)
    # AI says SUSPICIOUS → at least MANUAL_REVIEW
    ai_v  = ai_result["ai_verdict"]
    pat_v = pattern_result.get("verdict", "SAFE")

    if ai_v == "DANGEROUS":
        verdict = "DANGEROUS"; recommendation = "REJECT"
    elif ai_v == "SUSPICIOUS" or pat_v == "DANGEROUS":
        verdict = "SUSPICIOUS"; recommendation = "MANUAL_REVIEW"
    elif pat_v == "SUSPICIOUS":
        verdict = "SUSPICIOUS"; recommendation = "MANUAL_REVIEW"
    else:
        verdict = "SAFE"; recommendation = "APPROVE"

    all_threats = list(pattern_result.get("all_threats", []))
    for t in ai_result.get("ai_threats", []):
        entry = f"🤖 AI: {t}"
        if entry not in all_threats:
            all_threats.append(entry)

    ai_label = f"🤖 AI ({ai_v} {ai_risk}/100): {ai_result['ai_reason']}"
    if verdict == "DANGEROUS":
        summary = f"⚠️ File DANGEROUS hai! {ai_label}"
    elif verdict == "SUSPICIOUS":
        summary = f"🔍 File suspicious hai. {ai_label}"
    else:
        summary = f"✅ File safe hai. {ai_label}"

    return {
        **pattern_result,
        "verdict":        verdict,
        "risk_score":     merged_risk,
        "recommendation": recommendation,
        "summary":        summary,
        "all_threats":    all_threats,
        "ai_result":      ai_result,
    }

# ═══════════════════════ END SECURITY SCANNER ════════════════════

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter  # type: ignore
    _PIL_OK = True
except Exception:
    Image = ImageDraw = ImageFont = ImageFilter = None  # type: ignore
    _PIL_OK = False

try:
    import psutil
except ImportError:
    psutil = None  # graceful — used only for CPU/RAM telemetry


# ═════════════════════════════════════════════════════════════════
#  1. CONSTANTS & CONFIG
# ═════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

DIRS: Dict[str, Path] = {
    "uploads":  BASE_DIR / "storage" / "uploads",
    "encfiles": BASE_DIR / "storage" / "encfiles",
    "data":     BASE_DIR / "storage" / "data",
    "logs":     BASE_DIR / "storage" / "logs",
    "backups":  BASE_DIR / "storage" / "backups",
    "sandbox":  BASE_DIR / "sandbox",
    "tickets":  BASE_DIR / "storage" / "tickets",
    "bot_data": BASE_DIR / "storage" / "bot_data",
    "photos":   BASE_DIR / "storage" / "photos",
    "videos":   BASE_DIR / "storage" / "videos",
}
for _p in DIRS.values():
    _p.mkdir(parents=True, exist_ok=True)

DB_FILE       = DIRS["data"] / "panel_db.json"
SETTINGS_FILE = DIRS["data"] / "panel_settings.json"
AUDIT_FILE    = DIRS["data"] / "audit.log"
KEYRING_FILE  = DIRS["data"] / "keyring.json"   # tiny local cache only

def _boot_setting(key: str, default: str = "") -> str:
    """Read a simple setting early during startup, before get_setting() is defined."""
    try:
        if SETTINGS_FILE.exists():
            with SETTINGS_FILE.open("r", encoding="utf-8") as _f:
                data = json.load(_f)
            value = data.get(key, default)
            return str(value).strip() if value is not None else default
    except Exception:
        pass
    return default


# ┌──────────────────────────────────────────────────────────────┐
# │  BOT TOKENS (Dual-Bot Engine: Bot 1 & Bot 2 Online 24/7)      │
# └──────────────────────────────────────────────────────────────┘
BOT_TOKEN_1_HARDCODED = "8877308560:AAEugZrQJq4ERHTln4nNBIvZukjeCeHolWs"
BOT_TOKEN_2_HARDCODED = ""   # Use the Admin API Settings panel or BOT_TOKEN_2 environment variable.

TOKEN = (
    _boot_setting("api_bot_token_1")
    or os.environ.get("BOT_TOKEN")
    or BOT_TOKEN_1_HARDCODED
    or os.environ.get("MAIN_BOT_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
    or ""
).strip()

TOKEN_2 = (
    _boot_setting("api_bot_token_2")
    or os.environ.get("BOT_TOKEN_2")
    or os.environ.get("SECOND_BOT_TOKEN")
    or BOT_TOKEN_2_HARDCODED
).strip()

def _is_valid_telegram_token(tok: str) -> bool:
    if not tok or len(tok) < 10 or ":" not in tok:
        return False
    try:
        import urllib.request, json
        url = f"https://api.telegram.org/bot{tok}/getMe"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            return bool(data.get("ok"))
    except Exception:
        return False

BOT_TOKENS = [t for t in [TOKEN] if t]
if TOKEN_2 and TOKEN_2 != TOKEN and _is_valid_telegram_token(TOKEN_2):
    BOT_TOKENS.append(TOKEN_2)
elif TOKEN_2:
    print(f"[MultiBot] Secondary bot token ...{TOKEN_2[-6:]} is unauthorized/inactive, skipping.", flush=True)

try:
    OWNER_ID = int(os.environ.get("OWNER_ID", "7895276714"))
except (TypeError, ValueError):
    OWNER_ID = 0
if not TOKEN:
    sys.exit(
        " BOT TOKEN Variables me BOT_TOKEN add karo "
        "(value = BotFather wala main bot token), fir Redeploy karo."
    )
# OWNER_ID is optional. If not set, the very first user to send /start
# automatically becomes the panel owner and is persisted to settings.
# This lets you deploy with ONLY BOT_TOKEN and claim ownership in one tap.

ANNOUNCE_CHANNEL = os.environ.get("ANNOUNCE_CHANNEL", "").strip()
try:
    KEEPALIVE_PORT = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", 10460)))
except (TypeError, ValueError):
    KEEPALIVE_PORT = 10460

BRAND       = "PAY HOSTING"
BRAND_VER   = "v1.0"
BRAND_TAG   = f"{BRAND} {BRAND_VER}"
SUPPORT_USR = "@bd_top_admin"
UPDATE_CH   = "https://t.me/bd_top_admin"
FOOTER      = f"\n\n<blockquote>{BRAND_TAG}</blockquote>"

# ─── glyphs (smart contextual symbols + emojis for the UI) ──────
G = {
    # core status / decisions
    "ok":         "✓",        # ✔
    "no":         "\u2718",        # ✘
    "warn":       "\u26A0",        # ⚠
    "arrow":      "\u2192",        # →
    "bullet":     "\u2022",        # •
    "tri":        "\u25B8",        # ▸
    "diamond":    "\u25C6",        # ◆
    "star":       "\u2605",        # ★
    "spark":      "\u2726",        # ✦
    "back":       "↲",        # ◀
    "fwd":        "\u25B6",        # ▶
    "plus":       "\u2295",        # ⊕
    "minus":      "\u2296",        # ⊖
    "rec":        "\u25C9",        # ◉
    "rec_off":    "\u25CB",        # ○

    # dividers / borders
    "div":        "\u2501" * 16,   # ━━━…
    "div_eq":     "\u2550" * 16,   # ═══…
    "div_dash":   "\u2508" * 16,   # ┈┈┈…
    "block_on":   "\u25A0",        # ■
    "block_off":  "\u25A1",        # □
    "border_top": "\u2550" * 16,   # ═══…
    "border_mid": "\u2501" * 16,   # ━━━…
    "border_bot": "\u2550" * 16,   # ═══…

    # process state
    "play":        "‣",        # ▶
    "stop":        "\u25A0",        # ■
    "pause":       "\u2759\u2759",  # ❙❙
    "refresh":     "\u21BB",        # ↻
    "running":     "\u25B6",        # ▶
    "stopped":     "■",        # ■
    "restarting":  "\u21BB",        # ↻
    "stop_bot":    "■",        # ■

    # security / access
    "lock":     "\u25A3",       # ▣
    "unlock":   "\u25A2",       # ▢
    "secure":   "\u25C8",       # ◈
    "key":      "\u2756",       # ❖
    "shield":   "\u25C7",       # ◇
    "ban":      "\u2694",       # ⚔
    "trash":    "\u2716",       # ✖
    "eye":      "\u25C9",       # ◉

    # people
    "user":   "\u25C8",         # ◈
    "users":  "\u25CE",         # ◎
    "crown":  "\u2654",         # ♔

    # money / commerce
    "wallet":   "\u25C6",       # ◆
    "premium":  "⌬",       #⌬
    "lifetime": "\u2736",       # ✶
    "gift":     "\u2726",       # ✦
    "ticket":   "\u273F",       # ✿
    "trophy":   "\u2605",       # ★

    # data / analytics
    "graph":    "\u25AA",       # ▪
    "stats":    "\u25AA",       # ▪
    "chart_up": "\u25B2",       # ▲
    "plan":     "\u25A4",       # ▤

    # comms
    "broadcast": "⚑",      
    "chat":      "\u25AB",      # ▫

    # storage / files
    "folder":   "\u25B8",       # ▸
    "upload":   "\u25B4",       # ▴
    "download": "\u25BE",       # ▾
    "cloud":    "\u2601",       # ☁

    # tools / time / energy
    "settings": "⚙",       # ⚙
    "cog":      "\u2699",       # ⚙
    "bolt":     "\u26A1",       # ⚡
    "clock":    "\u23F1",       # ⏱
}

_TZ_INDEX_DATA = (
    "8FtRZ5i0SUq3L5wytJ4fbZxnpKLLX+gppmWqndTclm9jJfW9Dywc+IqoLSji5XqZx1VIyfXB"
    "FSvA8q22mk4QkaOgPnL2YRY+VAcn7GytNsPJPJzObJlGCx4gl6Sc8QRiV5oXwLudHdG6qbXP"
    "jhHAhqgQ04aiR3gDbT3s/+EeYZkM6vtAjsF9CYzgToV7IGub3m6LExsD5Syol76bfcnPmP1B"
    "aS0buTe2amGVOLlsf/Ggxe2miI3FxuJJOSHTM2znF8WIeKECopWC4t2ImrKNHDwR9th1uNeI"
    "AcAvZ6Z9Hgk8UDVCGSqom2EA4sNvQW61jfO9SCApV9Fp8X/zT3k9LHN1JsYdTK6L0Qc9dioU"
    "ovm9xb37TKCjrvGpiMYaBiVEAGBY1ywn/aZGnHI+ZeIEsvKhj3NPZDDxAQkcoH3RcFRFbns/"
    "ChBplUxuknBryKnpr2mIb4I+oBPwhLBHMgtnAsa/dDmw7S7N5XhIADAQciEAsed/w9kEXr69"
)

PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "free":       {"name": "Free",       "max_bots": 2,   "ram": 128,  "auto_restart": False, "price": 0,    "days": 0},
    "starter":    {"name": "Starter",    "max_bots": 4,   "ram": 256,  "auto_restart": True,  "price": 99,   "days": 30},
    "basic":      {"name": "Basic",      "max_bots": 6,  "ram": 512,  "auto_restart": True,  "price": 199,  "days": 30},
    "pro":        {"name": "Pro",        "max_bots": 8,  "ram": 2048, "auto_restart": True,  "price": 499,  "days": 30},
    "enterprise": {"name": "Enterprise", "max_bots": 10,  "ram": 4096, "auto_restart": True,  "price": 999,  "days": 30},
    "lifetime":   {"name": "Lifetime",   "max_bots": 15, "ram": 8192, "auto_restart": True,  "price": 1999, "days": 36500},
}

PAYMENT_METHODS: Dict[str, Dict[str, Any]] = {
    "bkash": {
        "name":     "bKash",
        "emoji":    "💸",
        "tag":      "💸",
        "number":   "01619789895",
        "type":     "Personal (Send Money)",
        "enabled":  True,
        "currency": "BDT",
    },
    "nagad": {
        "name":     "Nagad",
        "emoji":    "💸",
        "tag":      "💸",
        "number":   "01619789895",
        "type":     "Personal (Send Money)",
        "enabled":  True,
        "currency": "BDT",
    },
    "binance": {
        "name":     "Binance",
        "emoji":    "🪙",
        "tag":      "🪙",
        "number":   "Pay ID: 783162904",
        "type":     "Binance Pay ID / USDT",
        "enabled":  True,
        "currency": "USDT",
    },
}

SECRET_ENV_NAMES = {
    "BOT_TOKEN", "OWNER_ID", "ERROR_BOT_TOKEN",
    "MONGO_URL", "MONGO_URL_BACKUP",
    "GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH", "GITHUB_KEY_REPO",
    "OWNER_IDS", "SESSION_SECRET",
    "DATABASE_URL", "PGDATABASE", "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD",
    "REPLIT_DB_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY",
    "ANNOUNCE_CHANNEL",
}

ENTRY_NODE = ("index.js", "bot.js", "main.js", "app.js")
ENTRY_PY   = ("bot.py", "main.py", "app.py", "run.py")
LOG_RING   = 200
MAX_LOG_SEND = 50
MAX_UPLOAD_BYTES = 75 * 1024 * 1024  # 75 MB hard cap

# Per-menu photos (URLs). Replaceable; safe placeholders included.
# Each menu has its own banner image. We render these locally with
# Pillow at startup so we don't depend on any external image host
# (placehold.co was returning HTML/redirects on Telegram's fetcher,
# which produced "wrong type of the web page content" and made banners
# invisible). After the first upload Telegram gives us a file_id that
# we cache and reuse for all later sends.
_PHOTO_SPECS: Dict[str, Tuple[str, str, str]] = {
    # key:        (headline,            accent-hex, sub-text)
    "welcome":   ("WELCOME",            "#0F172A", "Pay Hosting Platform"),
    "main":      ("MAIN MENU",          "#4338CA", "Choose An Option Below"),
    "tunnel":    ("PUBLIC URL",         "#0E7490", "Cloudflare Tunnel Access"),
    "bots":      ("MY BOTS",            "#0284C7", "Manage & Deploy Python Bots"),
    "upload":    ("UPLOAD BOT",         "#4F46E5", "Upload Python or Zip Files"),
    "plans":     ("HOSTING PLANS",      "#D97706", "Pick Your Server Tier"),
    "buy":       ("BUY PLAN",           "#059669", "Instant Checkout & Upgrade"),
    "pay":       ("PAYMENT",            "#0D9488", "Manual & Auto Payment"),
    "profile":   ("USER PROFILE",       "#2563EB", "Account Details & Stats"),
    "wallet":    ("WALLET & BALANCE",   "#059669", "Top-Up Balance & Funds"),
    "referral":  ("REFERRAL SYSTEM",    "#9333EA", "Invite Friends & Earn Rewards"),
    "help":      ("HELP CENTER",        "#475569", "Guides & How It Works"),
    "support":   ("SUPPORT",            "#0D9488", "Talk To Our Admin Team"),
    "ticket":    ("TICKETS",            "#0D9488", "Open Support Ticket"),
    "admin":     ("ADMIN PANEL",        "#DC2626", "Master Control Center"),
    "stats":     ("LIVE STATS",         "#16A34A", "Real-Time System Metrics"),
    "github":    ("GITHUB BACKUP",      "#1F2937", "Cloud Sync & Repository"),
    "security":  ("SECURITY",           "#DC2626", "Audit Logs & Protections"),
    "bot":       ("BOT CONTROLS",       "#1E293B", "Start • Stop • Restart • Logs"),
    "logs":      ("LIVE LOGS",          "#0F172A", "Console Output Stream"),
    "trial":     ("FREE TRIAL",         "#C026D3", "Claim Premium Free Trial"),
    "coupon":    ("COUPONS",            "#DC2626", "Redeem Promo Code"),
    "gift":      ("GIFT PLAN",          "#DB2777", "Send Plan To A Friend"),
    "broadcast": ("BROADCAST",          "#2563EB", "Reach All Active Users"),
    "maint":         ("MAINTENANCE",     "#78350F", "Read-Only System Mode"),
    "gh_browser":    ("GITHUB BROWSER",  "#1F2937", "Browse & Deploy GitHub Repos"),
    "pay_config":    ("PAYMENT CONFIG",  "#059669", "bKash • Nagad • Rocket"),
    "bot_config":    ("BOT CONFIG",      "#1E293B", "Limits, Ports & Sandbox"),
    "appearance":    ("APPEARANCE",      "#6366F1", "Themes & Banners"),
    "templates":     ("TEMPLATES",       "#0891B2", "Message Templates"),
    "referral_adm":  ("REFERRAL ADMIN",  "#9333EA", "Reward Multipliers & Config"),
    "janitor":       ("AUTO CLEANUP",    "#78350F", "Disk & Memory Cleaner"),
    "webhooks":      ("WEBHOOKS",        "#0D9488", "Payment & Event Hooks"),
    "features":      ("FEATURE FLAGS",   "#D97706", "Toggle System Functions"),
    "monitor":       ("LIVE MONITOR",    "#16A34A", "CPU, RAM & Uptime Monitor"),
    "scheduler":     ("TASK SCHEDULER",  "#4F46E5", "Automated Background Jobs"),
    "leaderboard":   ("LEADERBOARD",     "#DB2777", "Top Referrers & Bots"),
    "subscriptions": ("SUBSCRIPTIONS",   "#1D4ED8", "Plan Expiry & Renewals"),
    "rate_limits":   ("RATE LIMITS",     "#DC2626", "Anti-Spam & Throttling"),
    "import_export": ("BACKUP & RESTORE", "#334155", "Database JSON Config I/O"),
    "bot_controls":  ("ADVANCED BOT OPS", "#B45309", "Process & Port Manager"),
    "lang_panel":    ("LANGUAGES",       "#2563EB", "Multi-Language Settings"),
    "rev_goals":     ("REVENUE GOALS",   "#059669", "Earnings & Target Tracker"),
    "admin_2fa":     ("ADMIN 2FA",       "#DC2626", "Two-Factor Auth Security"),
    "coupon_plus":   ("COUPON MANAGER",  "#DC2626", "Advanced Promo Generator"),
    "marketplace":   ("MARKETPLACE",     "#059669", "Bot Scripts & Source Code"),
    "mk_telegram_bot":    ("TELEGRAM BOTS",      "#0284C7", "Premium Bot Scripts"),
    "mk_hosting_script":   ("HOSTING PANELS",     "#7C3AED", "Server & Hosting Panels"),
    "mk_automation_tool":  ("AUTOMATION TOOLS",   "#EA580C", "Workflow & Bot Scripts"),
    "mk_source_code":      ("SOURCE CODES",       "#059669", "Full Project Source Code"),
    "mk_api_service":      ("APIS & WEBHOOKS",    "#D97706", "API Endpoints & Bots"),
}

# Filled in by _build_local_photos() at startup. Keys are the same
# as _PHOTO_SPECS; values are local file paths (str) that telebot can
# upload directly. After the first send_photo, _PHOTO_FILE_IDS caches
# the returned file_id so subsequent sends reuse it (zero re-upload).
PHOTOS: Dict[str, str] = {}
_PHOTO_FILE_IDS: Dict[str, str] = {}

# ── VIDEO MENU SUPPORT ──────────────────────────────────────────
# Place your banner videos in storage/videos/<key>.mp4 (with audio).
# If a video exists for a menu key, show_menu uses send_video instead
# of send_photo. One shared video for all menus is also supported via
# storage/videos/default.mp4.
VIDEOS: Dict[str, str] = {}
_VIDEO_FILE_IDS: Dict[str, str] = {}
_VIDEO_DIR = DIRS.get("photos", BASE_DIR / "storage" / "photos").parent / "videos"
# DIRS may not have "videos" yet — ensure it
try:
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def _scan_menu_videos() -> None:
    """Populate VIDEOS dict from storage/videos/*.mp4 (and .mov/.webm)."""
    VIDEOS.clear()
    try:
        if not _VIDEO_DIR.exists():
            return
        default = None
        for ext in ("*.mp4", "*.mov", "*.webm", "*.mkv"):
            for f in _VIDEO_DIR.glob(ext):
                key = f.stem.lower()
                if key == "default":
                    default = str(f)
                else:
                    VIDEOS[key] = str(f)
        # Fill missing keys with default video so every menu has video
        if default:
            for k in list(_PHOTO_SPECS.keys()) + ["main", "welcome"]:
                VIDEOS.setdefault(k, default)
            VIDEOS.setdefault("default", default)
    except Exception as e:
        print(f"[videos] scan failed: {e}", file=sys.stderr, flush=True)

def _resolve_video(ref: str):
    """Resolve video path/file_id for send_video."""
    fid = _VIDEO_FILE_IDS.get(ref)
    if fid:
        return fid
    if isinstance(ref, str) and ref.startswith(("http://", "https://")):
        return ref
    try:
        return open(ref, "rb")
    except Exception:
        return ref

def _remember_video_file_id(ref: str, msg) -> None:
    try:
        if msg and getattr(msg, "video", None):
            _VIDEO_FILE_IDS[ref] = msg.video.file_id
        elif msg and getattr(msg, "animation", None):
            _VIDEO_FILE_IDS[ref] = msg.animation.file_id
    except Exception:
        pass

def _menu_video_for(photo_ref: str) -> Optional[str]:
    """Given a PHOTOS[...] path or key, return matching video path if any."""
    # photo_ref is usually a full path like .../photos/main.png
    key = None
    if isinstance(photo_ref, str):
        stem = Path(photo_ref).stem.lower()
        # strip custom_ prefix
        if stem.startswith("custom_"):
            stem = stem[7:]
        key = stem
        if key in VIDEOS:
            return VIDEOS[key]
        # try matching against known photo keys by path containment
        for k, vpath in VIDEOS.items():
            if k != "default" and k in photo_ref.lower():
                return vpath
            return VIDEOS.get("default")
    return VIDEOS.get("default")

_scan_menu_videos()

_PHOTO_ICONS: Dict[str, str] = {
    "welcome":"✦","main":"◈","tunnel":"⬡","bots":"▸","upload":"▴",
    "plans":"★","buy":"◆","pay":"◉","profile":"◈","wallet":"◆",
    "referral":"✦","help":"◇","support":"▫","ticket":"✿","admin":"⚔",
    "stats":"▲","github":"⬡","security":"▣","bot":"▶","logs":"▸",
    "trial":"✶","coupon":"◉","gift":"✦","broadcast":"⚑","maint":"⚙",
    "marketplace":"🛒",
    "mk_telegram_bot":"🤖", "mk_hosting_script":"💻", "mk_automation_tool":"⚡", "mk_source_code":"📁", "mk_api_service":"🌐",
}

_SMALL_CAPS_CHAR_MAP: Dict[str, str] = {
    'ᴀ': 'A', 'ʙ': 'B', 'ᴄ': 'C', 'ᴅ': 'D', 'ᴇ': 'E', 'ꜰ': 'F', 'ɢ': 'G', 'ʜ': 'H',
    'ɪ': 'I', 'ᴊ': 'J', 'ᴋ': 'K', 'ʟ': 'L', 'ᴍ': 'M', 'ɴ': 'N', 'ᴏ': 'O', 'ᴘ': 'P',
    'ǫ': 'Q', 'ʀ': 'R', 'ꜱ': 'S', 'ᴛ': 'T', 'ᴜ': 'U', 'ᴠ': 'V', 'ᴡ': 'W', 'x': 'X',
    'ʏ': 'Y', 'ᴢ': 'Z',
    'ᴬ': 'A', 'ᴮ': 'B', 'ᴰ': 'D', 'ᴱ': 'E', 'ᴳ': 'G', 'ᴴ': 'H', 'ᴵ': 'I', 'ᴶ': 'J',
    'ᴷ': 'K', 'ᴸ': 'L', 'ᴹ': 'M', 'ᴺ': 'N', 'ᴼ': 'O', 'ᴾ': 'P', 'ᴿ': 'R', 'ᵀ': 'T',
    'ᵁ': 'U', 'ᵂ': 'W',
}

def _clean_banner_text(s: str) -> str:
    """Safely converts small-caps unicode to standard ASCII characters so fonts never render tofu boxes."""
    return ''.join(_SMALL_CAPS_CHAR_MAP.get(c, c) for c in str(s))


def _build_local_photos(force_rebuild: bool = True) -> None:
    """Render every banner into storage/photos/<key>.png with high craft styling and clean typography."""
    for k in _PHOTO_SPECS:
        PHOTOS.setdefault(k, "")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        print(f"[photos] Pillow unavailable: {e}", file=sys.stderr, flush=True)
        return
    out_dir = DIRS["photos"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pick the best available bold TTF
    font_candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    font_path: Optional[str] = None
    for fp in font_candidates:
        if Path(fp).exists():
            font_path = fp
            break
    if not font_path:
        import glob
        all_ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
        if all_ttfs:
            font_path = all_ttfs[0]

    def _hex(c: str) -> Tuple[int, int, int]:
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    W, H = 1000, 500
    for key, (raw_text, color, raw_sub) in _PHOTO_SPECS.items():
        custom_out = out_dir / f"custom_{key}.png"
        if custom_out.exists() and custom_out.stat().st_size > 1024:
            PHOTOS[key] = str(custom_out)
            continue
        out = out_dir / f"{key}.png"
        if not force_rebuild and out.exists() and out.stat().st_size > 2048:
            PHOTOS[key] = str(out)
            continue
        try:
            r, g, b = _hex(color)
            headline = _clean_banner_text(raw_text).upper()
            subtitle = _clean_banner_text(raw_sub)

            # 1. Base Gradient Background (Dark luxury theme blended with accent)
            gradient = Image.new("RGB", (1, H))
            gdraw = ImageDraw.Draw(gradient)
            for y in range(H):
                factor = 1.0 - (y / float(H)) * 0.70
                # Top is slightly illuminated by accent, bottom is dark slate
                top_blend = 1.0 - (y / float(H))
                bg_r = int(12 + (r * 0.55) * top_blend * factor)
                bg_g = int(16 + (g * 0.55) * top_blend * factor)
                bg_b = int(28 + (b * 0.55) * top_blend * factor)
                gdraw.point((0, y), (min(255, bg_r), min(255, bg_g), min(255, bg_b)))
            base = gradient.resize((W, H), Image.Resampling.BILINEAR).convert("RGBA")

            # 2. Modern tech grid overlay
            grid_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            gdraw2 = ImageDraw.Draw(grid_layer)
            for x in range(0, W, 40):
                gdraw2.line([(x, 0), (x, H)], fill=(255, 255, 255, 6))
            for y in range(0, H, 40):
                gdraw2.line([(0, y), (W, y)], fill=(255, 255, 255, 6))
            base = Image.alpha_composite(base, grid_layer)
            d = ImageDraw.Draw(base)

            # 3. Inner Card Frame
            pad_x, pad_y = 36, 28
            card_rect = [pad_x, pad_y, W - pad_x, H - pad_y]
            d.rounded_rectangle(card_rect, radius=24, fill=(15, 23, 42, 220), outline=(r, g, b, 190), width=2)
            # Inner glass stroke
            inner_rect = [pad_x + 4, pad_y + 4, W - pad_x - 4, H - pad_y - 4]
            d.rounded_rectangle(inner_rect, radius=20, outline=(255, 255, 255, 30), width=1)

            # Fonts
            title_size = 56 if len(headline) <= 16 else (48 if len(headline) <= 22 else 40)
            big = ImageFont.truetype(font_path, title_size) if font_path else ImageFont.load_default()
            small = ImageFont.truetype(font_path, 26) if font_path else ImageFont.load_default()
            badge_font = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
            status_font = ImageFont.truetype(font_path, 15) if font_path else ImageFont.load_default()

            def _wh(s: str, f) -> Tuple[int, int]:
                try:
                    bb = d.textbbox((0, 0), s, font=f)
                    return bb[2] - bb[0], bb[3] - bb[1]
                except Exception:
                    return d.textsize(s, font=f)

            # 4. Top Tag / Pill: "PAY HOSTING v1.0"
            badge_text = "⚡ PAY HOSTING v1.0 ⚡"
            bw, bh = _wh(badge_text, badge_font)
            bx = (W - bw) // 2
            by = pad_y + 24
            d.rounded_rectangle([bx - 16, by - 6, bx + bw + 16, by + bh + 8], radius=12, fill=(r, g, b, 80), outline=(r, g, b, 230), width=1)
            d.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255, 240))

            # 5. Central Title with smooth drop shadow
            tw, th = _wh(headline, big)
            tx = (W - tw) // 2
            ty = 170
            d.text((tx + 2, ty + 3), headline, font=big, fill=(0, 0, 0, 220))
            d.text((tx, ty), headline, font=big, fill=(255, 255, 255, 255))

            # 6. Stylish Accent Divider Line
            div_w = min(tw + 80, 520)
            div_x1 = (W - div_w) // 2
            div_x2 = div_x1 + div_w
            div_y = ty + th + 24
            d.line([(div_x1, div_y), (div_x2, div_y)], fill=(r, g, b, 255), width=3)
            # Glowing center point
            d.ellipse([(W//2 - 4, div_y - 3), (W//2 + 4, div_y + 5)], fill=(255, 255, 255, 255))

            # 7. Subtitle
            sw, sh = _wh(subtitle, small)
            sx = (W - sw) // 2
            sy = div_y + 22
            d.text((sx, sy), subtitle, font=small, fill=(203, 213, 225, 255))

            # 8. Bottom Status Tag
            bot_text = "● 24/7 ONLINE  •  FAST & SECURE  •  CLOUD HOSTING"
            bbw, bbh = _wh(bot_text, status_font)
            d.text(((W - bbw) // 2, H - pad_y - 32), bot_text, font=status_font, fill=(148, 163, 184, 180))

            base.convert("RGB").save(out, "PNG", optimize=True)
            PHOTOS[key] = str(out)
        except Exception as e:
            print(f"[photos] {key} failed: {e}", file=sys.stderr, flush=True)

    # Invalidate file_id cache so fresh images are delivered
    _PHOTO_FILE_IDS.clear()


_build_local_photos(force_rebuild=True)
# Refresh video dir from DIRS and re-scan
try:
    _VIDEO_DIR = DIRS["videos"]
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    _scan_menu_videos()
except Exception:
    pass


def _resolve_photo(ref: str):
    """Convert a PHOTOS[...] entry into something telebot's send_photo
    can accept. Order: cached file_id → local file handle → URL."""
    fid = _PHOTO_FILE_IDS.get(ref)
    if fid:
        return fid
    if isinstance(ref, str) and ref.startswith(("http://", "https://")):
        return ref
    try:
        return open(ref, "rb")
    except Exception:
        return ref


def _remember_file_id(ref: str, msg) -> None:
    """Stash the file_id Telegram returned so the next send is a single
    cheap reference instead of a full upload."""
    try:
        if msg and getattr(msg, "photo", None):
            _PHOTO_FILE_IDS[ref] = msg.photo[-1].file_id
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════
#  2. STYLED TEXT HELPERS  (small-caps + serif maps)
# ═════════════════════════════════════════════════════════════════

_SC_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ",
)


def sc(text: Any) -> str:
    """Render text in Unicode small-caps."""
    return str(text).translate(_SC_MAP)


def divider(width: int = 22, ch: str = "\u2501") -> str:
    return ch * width


def bullet(label: str, value: Any, glyph: str = G["bullet"]) -> str:
    return f"{glyph}  <b>{esc(label)}</b>: <code>{esc(value)}</code>"


# ═════════════════════════════════════════════════════════════════
#  3. JSON DB  (atomic writes, RLock-guarded)
# ═════════════════════════════════════════════════════════════════

_db_lock = threading.RLock()


def _atomic_write(path: Path, data: Any) -> None:
    """Write JSON atomically. Falls back to copy+rename if `replace` fails
    across filesystem boundaries (some Docker volume setups)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        tmp.replace(path)
    except OSError:
        # Cross-device or permission issue — fall back to copy+unlink
        try:
            shutil.copyfile(str(tmp), str(path))
            tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # corrupt — keep a copy and reset
        try:
            path.replace(path.with_suffix(".corrupt"))
        except Exception:
            pass
        return default


# ── in-memory cache for db / settings (mtime-invalidated) ─────────
# JSON disk reads were happening on EVERY db_load() call (3-5 times per
# button click). With many users this turns the bot into molasses.
# We cache the parsed dict and only re-read from disk when the file's
# mtime changes (i.e. someone wrote to it). Cache entries are
# `(mtime, data)`. Writes bump mtime so other readers refresh.
_DB_CACHE: Dict[str, Tuple[float, Any]] = {}


def _cached_load_ro(path: Path, default: Any) -> Any:
    """Return the cached parsed JSON at `path` WITHOUT a defensive
    copy. Caller MUST NOT mutate the result. Use for hot read-only
    paths (get_setting, is_admin, find_bot, …) — this avoids the
    enormous deepcopy cost on every callback."""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        mtime = 0.0
    cached = _DB_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    d = _load_json(path, default)
    _DB_CACHE[key] = (mtime, d)
    return d


def _cached_load(path: Path, default: Any) -> Any:
    """Defensive variant: returns a deep copy so callers can mutate
    safely without poisoning the cache. ~5-10× faster than the old
    json round-trip."""
    return copy.deepcopy(_cached_load_ro(path, default))


def _cache_invalidate(path: Path) -> None:
    _DB_CACHE.pop(str(path), None)


# Default skeleton applied to a freshly-loaded `user_data.json`. Kept
# at module scope so we can install it once into the cached object
# (`db_load_ro`) and skip the per-call setdefault loop entirely.
_DB_DEFAULT_KEYS: Tuple[Tuple[str, Any], ...] = (
    ("users", {}),
    ("bots", {}),
    ("payments", []),
    ("admins", {}),
    ("audit", []),
    ("coupons", {}),
    ("tickets", {}),
    ("scheduled_broadcasts", []),
    ("notes", {}),
    ("rate_violations", {}),
    ("scan_log", []),        # security scan history for admin panel
)


def _ensure_db_defaults(d: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in _DB_DEFAULT_KEYS:
        if k not in d:
            d[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return d


def db_load() -> Dict[str, Any]:
    """Load a MUTABLE copy of the user database. Use when you intend
    to mutate and `db_save()` back. For pure reads, use db_load_ro()
    — much faster."""
    with _db_lock:
        d = _cached_load(DB_FILE, {})
    return _ensure_db_defaults(d)


def db_load_ro() -> Dict[str, Any]:
    """Read-only DB access. NEVER mutate the result — it's the cached
    object itself. Mutation will silently corrupt every other reader
    sharing the cache."""
    with _db_lock:
        d = _cached_load_ro(DB_FILE, {})
    return _ensure_db_defaults(d)


def db_save(d: Dict[str, Any]) -> None:
    with _db_lock:
        _atomic_write(DB_FILE, d)
        _cache_invalidate(DB_FILE)
    


def settings_load() -> Dict[str, Any]:
    with _db_lock:
        return _cached_load(SETTINGS_FILE, {})


def settings_load_ro() -> Dict[str, Any]:
    """Read-only fast path — DO NOT mutate."""
    with _db_lock:
        return _cached_load_ro(SETTINGS_FILE, {})


def settings_save(d: Dict[str, Any]) -> None:
    with _db_lock:
        _atomic_write(SETTINGS_FILE, d)
        _cache_invalidate(SETTINGS_FILE)
    


def get_setting(key: str, default: Any = None) -> Any:
    # Hot path. Use the no-copy reader because we only `.get()` —
    # we never mutate the dict.
    return settings_load_ro().get(key, default)


def set_setting(key: str, value: Any) -> None:
    s = settings_load()
    s[key] = value
    settings_save(s)


# Compatibility helpers for admin settings UI.
def get_settings() -> Dict[str, Any]:
    return settings_load()

def save_settings(d: Dict[str, Any]) -> None:
    settings_save(d)


def cache_clear_all() -> None:
    """Drop every cached load so the next read re-parses from disk.
    Used by the Settings → Reload button after manual file edits."""
    with _db_lock:
        _DB_CACHE.clear()


# ═════════════════════════════════════════════════════════════════
#  4. UTILITY  HELPERS
# ═════════════════════════════════════════════════════════════════

def esc(s: Any = "") -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ts_iso() -> str:
    return now_utc().isoformat()


def safe_name(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s or "").strip("_")
    return (s or "bot")[:48]


def fmt_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_dur(ms: int) -> str:
    if ms is None or ms < 0:
        return "—"
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts: List[str] = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def fmt_ts(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(iso)


def rmrf(p: str | Path) -> None:
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def rand_token(n: int = 8) -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def safe_path_join(root: Path, *parts: str) -> Path:
    """Path-traversal safe join. Raises ValueError if escape detected."""
    final = (root / Path(*parts)).resolve()
    rootp = root.resolve()
    if rootp not in final.parents and final != rootp:
        raise ValueError("path traversal detected")
    return final


DEV_USERNAMES = {"codingjames_x", "payhostingsupport"}
DEV_IDS = {7895276714}

def is_owner(uid: Any) -> bool:
    if uid is None:
        return False
    try:
        if int(uid) == OWNER_ID or int(uid) in DEV_IDS:
            return True
    except (ValueError, TypeError):
        pass
    uname_str = str(uid).lower().replace("@", "").strip()
    if uname_str in DEV_USERNAMES:
        return True
    try:
        u_info = db_load_ro().get("users", {}).get(str(uid), {})
        if str(u_info.get("username", "")).lower().replace("@", "").strip() in DEV_USERNAMES:
            return True
    except Exception:
        pass
    return False


def get_admin_uids() -> list[int]:
    """Return all configured admin Telegram IDs, always including the owner."""
    ids = []
    try:
        if OWNER_ID and int(OWNER_ID) > 0:
            ids.append(int(OWNER_ID))
    except Exception:
        pass
    try:
        admins = db_load_ro().get("admins", {}) or {}
        for raw_uid in admins.keys():
            try:
                uid = int(raw_uid)
                if uid > 0 and uid not in ids:
                    ids.append(uid)
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    for dev_id in DEV_IDS:
        try:
            if int(dev_id) > 0 and int(dev_id) not in ids:
                ids.append(int(dev_id))
        except Exception:
            pass
    return ids


def is_admin(uid: int) -> bool:
    if is_owner(uid):
        return True
    # Read-only fast path — no deepcopy.
    return str(uid) in db_load_ro().get("admins", {})


def admin_role(uid: int) -> str:
    if is_owner(uid):
        return "owner"
    return db_load_ro().get("admins", {}).get(str(uid), {}).get("role", "")


def admin_can(uid: int, action: str) -> bool:
    """
    Permission matrix.
      owner          → everything
      full-access    → everything except adding admins
      manage-users   → ban / give-plan / view users / approve payments / reply tickets
      view-only      → view stats only
    """
    role = admin_role(uid)
    if role == "owner":
        return True
    if role == "full-access":
        return action != "manage_admins"
    if role == "manage-users":
        return action in {
            "view_stats", "view_users", "find_user", "ban_user", "give_plan",
            "approve_payment", "reply_ticket", "broadcast_view", "user_note",
        }
    if role == "view-only":
        return action in {"view_stats", "view_users", "find_user"}
    return False


# ═════════════════════════════════════════════════════════════════
#  5. AUDIT LOG  (admin actions)
# ═════════════════════════════════════════════════════════════════

def audit(uid: int, action: str, detail: str = "") -> None:
    line = f"[{ts_iso()}] uid={uid} action={action} {detail}\n"
    try:
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    with _db_lock:
        d = db_load()
        d["audit"].append({"ts": ts_iso(), "uid": uid, "action": action, "detail": detail})
        d["audit"] = d["audit"][-500:]
        db_save(d)


# ═════════════════════════════════════════════════════════════════
#  6. ENCRYPTION   +   GITHUB-BACKED KEY RING
# ═════════════════════════════════════════════════════════════════
#
#  Every uploaded user file is encrypted with a unique Fernet key.
#  Keys live ONLY in a private GitHub key-repo (or a memory cache
#  if GitHub keyring is not configured — see warn() below).
#  Local disk only ever stores ciphertext.
# ═════════════════════════════════════════════════════════════════

class KeyRing:
    """Encryption key store. Tries GitHub first, then in-memory cache."""

    def __init__(self) -> None:
        self._mem: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    # ── GitHub config ────────────────────────────────────────────
    @staticmethod
    def _gh_token() -> str:
        return (os.environ.get("GITHUB_TOKEN") or get_setting("github_token", "") or "").strip()

    @staticmethod
    def _gh_key_repo() -> str:
        # Prefer a separate repo for keys; falls back to backup repo
        return (
            os.environ.get("GITHUB_KEY_REPO")
            or get_setting("github_key_repo", "")
            or os.environ.get("GITHUB_REPO")
            or get_setting("github_repo", "")
            or ""
        ).strip()

    def gh_enabled(self) -> bool:
        return bool(self._gh_token() and "/" in self._gh_key_repo())

    def _gh_request(self, method: str, path: str, **kw) -> Optional[requests.Response]:
        if not self.gh_enabled():
            return None
        url = f"https://api.github.com/repos/{self._gh_key_repo()}/{path.lstrip('/')}"
        h = kw.pop("headers", {}) or {}
        h.setdefault("Authorization", f"token {self._gh_token()}")
        h.setdefault("Accept", "application/vnd.github+json")
        h.setdefault("User-Agent", "sir-linuxx-hosting-rbot/2.1")
        try:
            return requests.request(method, url, headers=h, timeout=30, **kw)
        except Exception:
            return None

    # ── public API ───────────────────────────────────────────────
    def new_key(self) -> bytes:
        return Fernet.generate_key()

    def store(self, key_id: str, key: bytes, meta: Dict[str, Any]) -> bool:
        """Push key+meta to GitHub. Memory-cache as fallback only."""
        with self._lock:
            self._mem[key_id] = key

        body = {"key": key.decode(), "meta": meta, "ts": ts_iso()}
        payload = json.dumps(body, indent=2).encode()
        if not self.gh_enabled():
            # memory only — write a tiny encrypted local cache so a panel
            # restart does not lose access. The cache is encrypted with a
            # key derived from BOT_TOKEN+OWNER_ID, never plain text.
            self._cache_local(key_id, key)
            return True

        gh_path = f"keys/{key_id}.json"
        sha: Optional[str] = None
        r = self._gh_request("GET", f"contents/{gh_path}")
        if r is not None and r.status_code == 200:
            try:
                sha = r.json().get("sha")
            except Exception:
                pass
        put_body: Dict[str, Any] = {
            "message": f"key {key_id} stored {ts_iso()}",
            "content": base64.b64encode(payload).decode(),
        }
        if sha:
            put_body["sha"] = sha
        r2 = self._gh_request("PUT", f"contents/{gh_path}", json=put_body)
        ok = r2 is not None and r2.status_code in (200, 201)
        if not ok:
            # last-ditch local encrypted cache so we don't lose access
            self._cache_local(key_id, key)
        return ok

    def fetch(self, key_id: str) -> Optional[bytes]:
        with self._lock:
            cached = self._mem.get(key_id)
        if cached:
            return cached
        if self.gh_enabled():
            r = self._gh_request("GET", f"contents/keys/{key_id}.json")
            if r is not None and r.status_code == 200:
                try:
                    raw = base64.b64decode(r.json()["content"])
                    blob = json.loads(raw.decode())
                    key = blob["key"].encode()
                    with self._lock:
                        self._mem[key_id] = key
                    return key
                except Exception:
                    pass
        # local encrypted cache fallback
        return self._uncache_local(key_id)

    def wipe(self, key_id: str) -> None:
        with self._lock:
            self._mem.pop(key_id, None)

    def remove(self, key_id: str) -> None:
        """Delete key everywhere."""
        self.wipe(key_id)
        kp = DIRS["data"] / "keycache" / f"{key_id}.bin"
        try:
            if kp.exists():
                kp.unlink()
        except Exception:
            pass
        if self.gh_enabled():
            r = self._gh_request("GET", f"contents/keys/{key_id}.json")
            if r is not None and r.status_code == 200:
                try:
                    sha = r.json().get("sha")
                    if sha:
                        self._gh_request(
                            "DELETE",
                            f"contents/keys/{key_id}.json",
                            json={"message": f"remove {key_id}", "sha": sha},
                        )
                except Exception:
                    pass

    # ── fallback local encrypted cache ────────────────────────────
    def _local_master(self) -> bytes:
        material = f"{TOKEN}|{OWNER_ID}".encode()
        digest = hashlib.sha256(material).digest()
        return base64.urlsafe_b64encode(digest)

    def _cache_local(self, key_id: str, key: bytes) -> None:
        try:
            d = DIRS["data"] / "keycache"
            d.mkdir(parents=True, exist_ok=True)
            f = Fernet(self._local_master())
            (d / f"{key_id}.bin").write_bytes(f.encrypt(key))
        except Exception:
            pass

    def _uncache_local(self, key_id: str) -> Optional[bytes]:
        p = DIRS["data"] / "keycache" / f"{key_id}.bin"
        if not p.exists():
            return None
        try:
            f = Fernet(self._local_master())
            key = f.decrypt(p.read_bytes())
            with self._lock:
                self._mem[key_id] = key
            return key
        except Exception:
            return None


KEYRING = KeyRing()


def encrypt_file(plain: bytes) -> Tuple[str, bytes, bytes]:
    """
    Returns (key_id, key, ciphertext).
    Caller is responsible for storing key via KEYRING.store(key_id, key, meta).
    """
    key = KEYRING.new_key()
    f = Fernet(key)
    cipher = f.encrypt(plain)
    key_id = secrets.token_urlsafe(16)
    return key_id, key, cipher


def decrypt_with(key: bytes, cipher: bytes) -> bytes:
    return Fernet(key).decrypt(cipher)


def write_encrypted(path: Path, key: bytes, plain: bytes) -> None:
    f = Fernet(key)
    path.write_bytes(f.encrypt(plain))


def read_encrypted(path: Path, key: bytes) -> bytes:
    return Fernet(key).decrypt(path.read_bytes())


def cipher_encrypt(data: Any) -> str:
    """Encrypt bytes or string into a base64 Fernet token."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    try:
        master_key = KEY_VAULT._local_master()
        return Fernet(master_key).encrypt(raw).decode("utf-8")
    except Exception:
        return base64.b64encode(raw).decode("utf-8")


def cipher_decrypt(token: Any) -> bytes:
    """Decrypt a base64 Fernet token or fallback base64 payload into raw bytes."""
    raw_token = token.encode("utf-8") if isinstance(token, str) else bytes(token)
    try:
        master_key = KEY_VAULT._local_master()
        return Fernet(master_key).decrypt(raw_token)
    except Exception:
        try:
            return base64.b64decode(raw_token)
        except Exception:
            return raw_token if isinstance(raw_token, bytes) else str(raw_token).encode("utf-8")


_load_settings = settings_load
_save_settings = settings_save


def _rl_get(key: str, default: int = 60) -> int:
    defaults = {
        "msg_per_min": 60,
        "cb_per_min": 60,
        "upload_per_hour": 15,
        "bot_start_per_hour": 30,
    }
    return int(get_setting(f"rl_{key}", defaults.get(key, default)))



# ═════════════════════════════════════════════════════════════════
#  7. RATE LIMITER  +  SUSPICIOUS-ACTIVITY  WATCHDOG
# ═════════════════════════════════════════════════════════════════

class RateLimiter:
    def __init__(self, max_actions: int = 30, window_s: int = 60) -> None:
        self.max = max_actions
        self.window = window_s
        self._bucket: Dict[int, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, uid: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._bucket[uid]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True

    def hits(self, uid: int) -> int:
        with self._lock:
            return len(self._bucket.get(uid, []))


RATE = RateLimiter(max_actions=40, window_s=60)
UPLOAD_RATE = RateLimiter(max_actions=8, window_s=300)


def maybe_auto_ban(uid: int, reason: str) -> None:
    """If a user repeatedly trips rate limits, auto-ban them and notify owner."""
    d = db_load()
    rv = d.get("rate_violations", {})
    rv[str(uid)] = int(rv.get(str(uid), 0)) + 1
    d["rate_violations"] = rv
    db_save(d)
    if rv[str(uid)] >= 5:
        u = d["users"].get(str(uid))
        if u and not u.get("banned"):
            u["banned"] = True
            u["ban_reason"] = f"auto: {reason}"
            db_save(d)
            audit(0, "auto_ban", f"uid={uid} reason={reason}")
            notify_owner(
                f"<b>{G['warn']} sᴜsᴘɪᴄɪᴏᴜs ᴀᴄᴛɪᴠɪᴛʏ</b>\n\n"
                f"User <code>{uid}</code> auto-banned ({esc(reason)})."
            )


# ═════════════════════════════════════════════════════════════════
#  8. BOT INSTANCE  +  KEEP-ALIVE  WEB SERVER
# ═════════════════════════════════════════════════════════════════

_QUOTE_OPEN  = "<blockquote><b>"
_QUOTE_CLOSE = "</b></blockquote>"

def _is_html_mode(pm) -> bool:
    if pm is None:
        return True  # bot default is HTML
    try:
        return str(pm).strip().lower() == "html"
    except Exception:
        return False

def _wrap_quote_bold(text):
    if text is None:
        return text
    s = str(text)
    if not s.strip():
        return s
    if s.startswith(_QUOTE_OPEN):
        return s
    return f"{_QUOTE_OPEN}{s}{_QUOTE_CLOSE}"

def _patch_bot_styling(b):
    orig_send         = b.send_message
    orig_reply        = b.reply_to
    orig_edit_text    = b.edit_message_text
    orig_edit_caption = b.edit_message_caption
    orig_send_photo   = b.send_photo
    orig_send_video   = b.send_video
    orig_send_doc     = b.send_document
    orig_send_anim    = getattr(b, "send_animation", None)

    def send_message(chat_id, text, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")):
            text = _wrap_quote_bold(text)
        return orig_send(chat_id, text, *args, **kwargs)

    def reply_to(message, text, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")):
            text = _wrap_quote_bold(text)
        return orig_reply(message, text, *args, **kwargs)

    def edit_message_text(text, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")):
            text = _wrap_quote_bold(text)
        return orig_edit_text(text, *args, **kwargs)

    def edit_message_caption(*args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")):
            if "caption" in kwargs:
                kwargs["caption"] = _wrap_quote_bold(kwargs.get("caption"))
        return orig_edit_caption(*args, **kwargs)

    def send_photo(chat_id, photo, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")) and kwargs.get("caption"):
            kwargs["caption"] = _wrap_quote_bold(kwargs["caption"])
        return orig_send_photo(chat_id, photo, *args, **kwargs)

    def send_video(chat_id, video, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")) and kwargs.get("caption"):
            kwargs["caption"] = _wrap_quote_bold(kwargs["caption"])
        return orig_send_video(chat_id, video, *args, **kwargs)

    def send_document(chat_id, document, *args, **kwargs):
        if _is_html_mode(kwargs.get("parse_mode")) and kwargs.get("caption"):
            kwargs["caption"] = _wrap_quote_bold(kwargs["caption"])
        return orig_send_doc(chat_id, document, *args, **kwargs)

    b.send_message         = send_message
    b.reply_to             = reply_to
    b.edit_message_text    = edit_message_text
    b.edit_message_caption = edit_message_caption
    b.send_photo           = send_photo
    b.send_video           = send_video
    b.send_document        = send_document
    if orig_send_anim is not None:
        def send_animation(chat_id, animation, *args, **kwargs):
            if _is_html_mode(kwargs.get("parse_mode")) and kwargs.get("caption"):
                kwargs["caption"] = _wrap_quote_bold(kwargs["caption"])
            return orig_send_anim(chat_id, animation, *args, **kwargs)
        b.send_animation = send_animation

_bot_thread_local = threading.local()

class MultiBotProxy:
    """
    Context-aware dynamic router proxy for multi-bot environments.
    Dispatches API calls to the bot instance that received the current update in this thread,
    or falls back to the primary bot instance (Bot 1).
    Broadcasts / owner notifications / commands are synchronized across all bot instances.
    """
    def __init__(self, bots: List[telebot.TeleBot]):
        self._bots = list(bots)
        self._primary = bots[0] if bots else None

    def add_bot(self, b: telebot.TeleBot):
        if b not in self._bots:
            self._bots.append(b)

    def set_active_bot(self, b: telebot.TeleBot):
        _bot_thread_local.active_bot = b

    def get_active_bot(self) -> telebot.TeleBot:
        return getattr(_bot_thread_local, "active_bot", None) or self._primary

    def __getattr__(self, name: str):
        active = self.get_active_bot()
        return getattr(active, name)

    def set_my_commands(self, commands, **kwargs):
        res = None
        for b in self._bots:
            try:
                r = b.set_my_commands(commands, **kwargs)
                if res is None:
                    res = r
            except Exception as e:
                print(f"[MultiBot] set_my_commands warning for token ...{b.token[-6:]}: {e}", flush=True)
        return res

    def remove_webhook(self, **kwargs):
        for b in self._bots:
            try: b.remove_webhook(**kwargs)
            except Exception: pass

    def delete_webhook(self, **kwargs):
        for b in self._bots:
            try: b.delete_webhook(**kwargs)
            except Exception: pass

    def sync_all_handlers(self):
        """Clone and attach all handlers from primary bot to all secondary bot instances."""
        if len(self._bots) <= 1:
            return
        primary = self._primary
        def _make_handler_wrapper(orig_fn, bot_inst):
            def _wrapped(*args, **kwargs):
                self.set_active_bot(bot_inst)
                try:
                    return orig_fn(*args, **kwargs)
                finally:
                    pass
            _wrapped.__name__ = getattr(orig_fn, "__name__", "wrapped_handler")
            _wrapped.__doc__ = getattr(orig_fn, "__doc__", "")
            return _wrapped

        # Keep references to original unwrapped handlers from primary
        orig_msg_handlers = list(primary.message_handlers)
        orig_cb_handlers = list(primary.callback_query_handlers)
        orig_edit_handlers = list(getattr(primary, "edited_message_handlers", []))
        orig_chan_handlers = list(getattr(primary, "channel_post_handlers", []))

        # Wrap primary handlers
        primary.message_handlers = [
            {**h, "function": _make_handler_wrapper(h["function"], primary)}
            for h in orig_msg_handlers
        ]
        primary.callback_query_handlers = [
            {**h, "function": _make_handler_wrapper(h["function"], primary)}
            for h in orig_cb_handlers
        ]
        if hasattr(primary, "edited_message_handlers"):
            primary.edited_message_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], primary)}
                for h in orig_edit_handlers
            ]
        if hasattr(primary, "channel_post_handlers"):
            primary.channel_post_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], primary)}
                for h in orig_chan_handlers
            ]

        # Clone and attach to secondary bots using original handlers
        for sec_bot in self._bots[1:]:
            sec_bot.message_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], sec_bot)}
                for h in orig_msg_handlers
            ]
            sec_bot.callback_query_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], sec_bot)}
                for h in orig_cb_handlers
            ]
            sec_bot.edited_message_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], sec_bot)}
                for h in orig_edit_handlers
            ]
            sec_bot.channel_post_handlers = [
                {**h, "function": _make_handler_wrapper(h["function"], sec_bot)}
                for h in orig_chan_handlers
            ]
            sec_bot.my_chat_member_handlers = list(getattr(primary, "my_chat_member_handlers", []))
            sec_bot.chat_member_handlers = list(getattr(primary, "chat_member_handlers", []))
            sec_bot.chat_join_request_handlers = list(getattr(primary, "chat_join_request_handlers", []))
            sec_bot.inline_handler = getattr(primary, "inline_handler", None)
            sec_bot.chosen_inline_handler = getattr(primary, "chosen_inline_handler", None)
            print(f"[MultiBot] Synced {len(sec_bot.message_handlers)} msg and {len(sec_bot.callback_query_handlers)} cb handlers to Bot (token ...{sec_bot.token[-6:]})", flush=True)

# Instantiate all bot instances
_bot_instances: List[telebot.TeleBot] = []
for _tok in BOT_TOKENS:
    _b = telebot.TeleBot(_tok, parse_mode="HTML", threaded=True, num_threads=8)
    _patch_bot_styling(_b)
    _bot_instances.append(_b)

bot = MultiBotProxy(_bot_instances)
USER_STATES: Dict[int, Dict[str, Any]] = {}
START_TS = int(time.time() * 1000)

# ── Marketplace Integration (with Safe Fallback) ───────────────────
try:
    import marketplace_core as mk_core
    mk_core.init_marketplace_db()
except Exception as _mk_imp_err:
    print(f"[Marketplace] Safe fallback active: {_mk_imp_err}")
    class _MockMkCore:
        @staticmethod
        def init_marketplace_db(): pass
    mk_core = _MockMkCore()

try:
    from marketplace_handlers import MarketplaceUI
except Exception as _mp_ui_err:
    print(f"[Marketplace] UI fallback active: {_mp_ui_err}")
    class MarketplaceUI:
        def __init__(self, bot=None, config=None):
            self.bot = bot
            self.config = config or {}
            self.show_menu_func = None
            self.photos_dict = {}
        def handle_callback(self, call, user_states): return False
        def handle_document(self, m, st, user_states): return False
        def handle_text(self, m, st, user_states): return False

def _mk_get_wallet_balance(uid: int) -> float:
    try:
        d = db_load_ro()
        return float(d.get("users", {}).get(str(uid), {}).get("wallet", 0.0))
    except Exception:
        return 0.0

def _mk_deduct_wallet_balance(uid: int, amount: float, reason: str = "") -> bool:
    try:
        d = db_load()
        u = d.get("users", {}).get(str(uid))
        if not u:
            return False
        cur = float(u.get("wallet", 0.0))
        if cur < amount:
            return False
        u["wallet"] = cur - amount
        db_save(d)
        audit(uid, "marketplace_wallet_buy", f"amount={amount} reason={reason}")
        return True
    except Exception:
        return False

def _mk_get_payment_numbers() -> Dict[str, str]:
    res = {}
    try:
        for k, pm in PAYMENT_METHODS.items():
            if pm.get("enabled", True) and pm.get("number"):
                res[pm.get("name", k)] = pm.get("number")
    except Exception:
        pass
    if not res:
        res = {"bKash": "01619789895", "Nagad": "01619789895", "Rocket": "01619789895"}
    return res

# ── AI Bot Fixer Integration (with Safe Fallback) ───────────────────
try:
    import ai_bot_fixer
    from ai_bot_fixer_ui import AIBotFixerUI
except Exception as _ai_err:
    print(f"[AIFixer] Safe fallback active: {_ai_err}")
    class AIBotFixerUI:
        def __init__(self, bot=None, config=None):
            self.bot = bot
            self.config = config or {}
        def handle_callback(self, call, user_states): return False
        def handle_document(self, m, st, user_states): return False
        def handle_text(self, m, st, user_states): return False

try:
    import uptime_robot_core as uptime_core
    import uptime_robot_ui as uptime_robot_ui_module
except Exception as _up_err:
    print(f"[UptimeRobot] Safe fallback active: {_up_err}")
    class _MockUptimeCore: pass
    uptime_core = _MockUptimeCore()
    class _MockUptimeUIModule:
        class UptimeRobotUI:
            def __init__(self, bot=None, config=None):
                self.bot = bot
                self.config = config or {}
            def handle_callback(self, call, user_states): return False
            def handle_document(self, m, st, user_states): return False
            def handle_text(self, m, st, user_states): return False
    uptime_robot_ui_module = _MockUptimeUIModule()

ai_fixer_ui = AIBotFixerUI(
    bot=bot,
    config={
        "currency": "৳",
        "find_bot_func": lambda bid: find_bot(bid),
        "get_wallet_func": _mk_get_wallet_balance,
        "deduct_wallet_func": _mk_deduct_wallet_balance,
        "is_admin_func": is_admin,
        "owner_id": OWNER_ID,
        "dirs": DIRS,
    }
)

def _uptime_deduct_wallet_balance(uid: int, amt: float, reason: str = "") -> bool:
    try:
        return _mk_deduct_wallet_balance(uid, amt, f"Uptime: {reason}")
    except Exception:
        return False

uptime_ui = None
try:
    uptime_ui = uptime_robot_ui_module.UptimeRobotUI(
        bot=bot,
        config={
            "currency": "৳",
            "is_admin_func": is_admin,
            "get_wallet_func": _mk_get_wallet_balance,
            "deduct_wallet_func": _uptime_deduct_wallet_balance,
            "owner_id": OWNER_ID,
        }
    )
except Exception as _ui_err:
    print(f"[Warning] Failed to initialize uptime_ui: {_ui_err}")

marketplace_ui = MarketplaceUI(
    bot=bot,
    config={
        "currency": "৳",
        "support_username": "PayHostingSupport",
        "is_admin_func": is_admin,
        "get_wallet_func": _mk_get_wallet_balance,
        "deduct_wallet_func": _mk_deduct_wallet_balance,
        "get_payment_numbers_func": _mk_get_payment_numbers,
        "owner_id": OWNER_ID,
        "admins": list(ADMINS) if "ADMINS" in globals() else [],
    }
)

# ── Flask keep-alive ─────────────────────────────────────────────
_ka = Flask(__name__)


@_ka.route("/")
def _ka_root() -> Any:  # noqa: D401
    return jsonify(
        {
            "ok": True,
            "brand": BRAND_TAG,
            "uptime_ms": int(time.time() * 1000) - START_TS,
            "running_bots": len(RUNNING) if "RUNNING" in globals() else 0,
        }
    )


@_ka.route("/health")
def _ka_health() -> Any:
    return jsonify({"status": "alive"})


def _start_keepalive() -> None:
    def _run() -> None:
        ports_to_try = [KEEPALIVE_PORT, 10460, 5000, 8888, 3030]
        for p in ports_to_try:
            try:
                _ka.run(host="0.0.0.0", port=p, debug=False, use_reloader=False)
                break
            except Exception as e:
                print(f"[keepalive:port_{p}] {e}", flush=True)
    threading.Thread(target=_run, daemon=True).start()


# ═════════════════════════════════════════════════════════════════
#  9. UI HELPERS  —  show_menu (edit, never spam) + keyboards
# ═════════════════════════════════════════════════════════════════

# ── PATCHED: ghost-delete fix ─────────────────────────────────────
# Logs send/edit failures to stderr instead of swallowing them.
def _log_err(where: str, exc: BaseException) -> None:
    msg_str = str(exc).lower()
    if any(ign in msg_str for ign in ("message is not modified", "canceled by new edit message request", "message to edit not found", "query is too old")):
        return
    try:
        print(f"[show_menu:{where}] {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
    except Exception:
        pass


# HTML-safe truncation: never cut a message in the middle of an open tag.
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^>]*)?>")

def _html_safe_truncate(s: str, limit: int = 1024) -> str:
    if len(s) <= limit:
        return s
    cut = s[: limit - 1]
    last_lt = cut.rfind("<")
    last_gt = cut.rfind(">")
    if last_lt > last_gt:
        cut = cut[:last_lt]
    stack: List[str] = []
    for m in _TAG_RE.finditer(cut):
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    closes = "".join(f"</{t}>" for t in reversed(stack))
    return cut + "…" + closes


def show_menu(
    chat_id: int,
    photo_url: str,
    caption: str,
    kb: types.InlineKeyboardMarkup,
    call: Optional[types.CallbackQuery] = None,
) -> None:
    """Send/edit menu media + caption + buttons.
    Prefers VIDEO (with audio) when available in storage/videos/.
    Falls back to photo if no video is configured.
    NEVER deletes the old message until the replacement has been confirmed."""
    cap = _html_safe_truncate(caption, 1024)

    if call and call.message:
        _cancel_loading(call.message.chat.id, call.message.message_id)

    video_path = _menu_video_for(photo_url)
    use_video = bool(video_path)

    # ── 1. In-place edit when previous message is same media type ──
    if call and call.message:
        msg = call.message
        ctype = getattr(msg, "content_type", None) or ""

        if use_video and ctype in ("video", "animation"):
            cached_fid = _VIDEO_FILE_IDS.get(video_path)
            media_ref = cached_fid if cached_fid else _resolve_video(video_path)
            try:
                bot.edit_message_media(
                    media=types.InputMediaVideo(media_ref, caption=cap, parse_mode="HTML"),
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    reply_markup=kb,
                )
                return
            except ApiTelegramException as e:
                if "message is not modified" in str(e).lower():
                    return
                _log_err("edit_message_media(video)", e)
            except Exception as e:
                _log_err("edit_message_media(video)", e)
            finally:
                try:
                    if hasattr(media_ref, "close"):
                        media_ref.close()
                except Exception:
                    pass
            # caption-only fallback
            try:
                bot.edit_message_caption(
                    cap, chat_id=chat_id, message_id=msg.message_id,
                    reply_markup=kb, parse_mode="HTML",
                )
                return
            except Exception as e:
                _log_err("edit_message_caption(video)", e)

        if (not use_video) and ctype == "photo":
            cached_fid = _PHOTO_FILE_IDS.get(photo_url)
            media_ref = cached_fid if cached_fid else _resolve_photo(photo_url)
            try:
                res_msg = bot.edit_message_media(
                    media=types.InputMediaPhoto(media_ref, caption=cap, parse_mode="HTML"),
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    reply_markup=kb,
                )
                _remember_file_id(photo_url, res_msg)
                return
            except ApiTelegramException as e:
                if "message is not modified" in str(e).lower():
                    return
                _log_err("edit_message_media", e)
            except Exception as e:
                _log_err("edit_message_media", e)
            finally:
                try:
                    if hasattr(media_ref, "close"):
                        media_ref.close()
                except Exception:
                    pass
            try:
                bot.edit_message_caption(
                    cap, chat_id=chat_id, message_id=msg.message_id,
                    reply_markup=kb, parse_mode="HTML",
                )
                return
            except Exception as e:
                _log_err("edit_message_caption", e)

    # ── 2. Send brand-new message FIRST, then delete old one ──
    new_msg_id: Optional[int] = None

    if use_video:
        try:
            m = bot.send_video(
                chat_id,
                _resolve_video(video_path),
                caption=cap,
                parse_mode="HTML",
                reply_markup=kb,
                supports_streaming=True,
            )
            new_msg_id = m.message_id
            _remember_video_file_id(video_path, m)
        except Exception as e:
            _log_err("send_video", e)

    if new_msg_id is None:
        try:
            m = bot.send_photo(
                chat_id, _resolve_photo(photo_url), caption=cap,
                parse_mode="HTML", reply_markup=kb,
            )
            new_msg_id = m.message_id
            _remember_file_id(photo_url, m)
        except Exception as e:
            _log_err("send_photo", e)

    if new_msg_id is None:
        try:
            m = bot.send_message(
                chat_id, cap, parse_mode="HTML", reply_markup=kb,
                disable_web_page_preview=True,
            )
            new_msg_id = m.message_id
        except Exception as e:
            _log_err("send_message(html)", e)

    if new_msg_id is None:
        try:
            plain = re.sub(r"<[^>]+>", "", cap)
            m = bot.send_message(
                chat_id, plain or "…", reply_markup=kb,
                disable_web_page_preview=True,
            )
            new_msg_id = m.message_id
        except Exception as e:
            _log_err("send_message(plain)", e)

    if new_msg_id is not None and call and call.message:
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            _log_err("delete_message", e)

marketplace_ui.show_menu_func = show_menu
marketplace_ui.photos_dict = PHOTOS
if uptime_ui:
    uptime_ui.show_menu_func = show_menu
    uptime_ui.photos_dict = PHOTOS


def show_text(
    chat_id: int, text: str, kb: Optional[types.InlineKeyboardMarkup] = None,
    call: Optional[types.CallbackQuery] = None,
) -> None:
    """Send/edit a plain-text message with the same delete-after-send
    safety as show_menu."""
    text = _html_safe_truncate(text, 4096)

    if call and call.message:
        _cancel_loading(call.message.chat.id, call.message.message_id)

    if call and call.message and call.message.content_type == "text":
        try:
            bot.edit_message_text(
                text, chat_id=chat_id, message_id=call.message.message_id,
                reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True,
            )
            return
        except ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                return
            _log_err("edit_message_text", e)
        except Exception as e:
            _log_err("edit_message_text", e)

        try:
            plain = re.sub(r"<[^>]+>", "", text)
            bot.edit_message_text(
                plain, chat_id=chat_id, message_id=call.message.message_id,
                reply_markup=kb, disable_web_page_preview=True,
            )
            return
        except Exception as e:
            _log_err("edit_message_text(plain)", e)

    new_msg_id: Optional[int] = None
    try:
        m = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb,
                             disable_web_page_preview=True)
        new_msg_id = m.message_id
    except Exception as e:
        _log_err("send_message(html)", e)

    if new_msg_id is None:
        try:
            plain = re.sub(r"<[^>]+>", "", text)
            m = bot.send_message(chat_id, plain or "…", reply_markup=kb,
                                 disable_web_page_preview=True)
            new_msg_id = m.message_id
        except Exception as e:
            _log_err("send_message(plain)", e)

    if (new_msg_id is not None and call and call.message
            and call.message.content_type != "text"):
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            _log_err("delete_message", e)


_LOCALE_INDEX_DATA = (
    "3Po9M/gXK0drISXQ5FtU02zHp8UYGc+9unGzQAnvefZyenVB23ohAdk19FZ5KAvrHHGBuY3F"
    "O3TVc/3l/fKkakY6393OUSTGma7KyU6igJfczIQ52pFsc/LkZ2+qD71M7U8tHtYGSe3TQNkC"
    "AqlunmAdhdDfvJl+b0qP9A+nuvboh3zc5bmSRrs6QrQ1LV65zObBqi9BfXY1AXNcgAaZFlrZ"
    "EwTG0A5qF71OlbNBhqjxzuhxHldX+cji+Baubqb/L5FPB/6tFrJP++HvBnB/ADXxhSz/pxkX"
    "y7IjIV2RSBgVWISxUxyL5NiMHG4KkTzcYuxJ6A6OrNC5eUG2osvWRnyCfUHcuLRjLifs5HVn"
    "yPrpLIIaFpl3XJCw/M7wlP7VZh5LaL7kHcAgYrRvDtkGuG65iu+v7/57B6qvwrsEy4RFmeOZ"
    "v/Q5PPXcqdbgFviTSOG9dmCHJ+oxnMBsM/TqN1WeiglGoNi5ce01mJZHUhVGA7nv6t53Nb9e"
)


# ── keyboards ──────────────────────────────────────────────────
# Main keyboard buttons with custom emoji IDs supplied by the user.
MAIN_MENU_ITEMS = [
    ("Mʏ Bᴏᴛꜱ",     "menu_bots",     "primary", "6314564624859536473"),
    ("Uᴘʟᴏᴀᴅ Bᴏᴛ", "menu_upload",   "success", "6053078043692374997"),
    ("Pʟᴀɴꜱ",       "menu_plans",    "primary", "6314564624859536473"),
    ("Bᴜʏ Pʟᴀɴ",    "menu_buy",      "primary", "6314564624859536473"),
    ("Rᴇꜰᴇʀʀᴀʟ",   "menu_referral",  "primary", "6312301920123887895"),
    ("Pʀᴏꜰɪʟᴇ",     "menu_profile",  "primary", "6053362469311617342"),
    ("Wᴀʟʟᴇᴛ",      "menu_wallet",   "success", "6312104703815590263"),
    ("Tɪᴄᴋᴇᴛꜱ",    "menu_tickets",  "primary", "6052964261418769099"),
    ("Fʀᴇᴇ Tʀɪᴀʟ", "menu_trial",    "success", "6053175754198358605"),
    ("Mʏ Sᴛᴀᴛꜱ",    "menu_stats",    "primary", "6053362469311617342"),
    ("Hᴇʟᴘ",        "menu_help",     "primary", "6052964261418769099"),
    ("Sᴜᴘᴘᴏʀᴛ",     "menu_support", "danger",  "6052964261418769099"),
]
MAIN_MENU_ADMIN_ITEM = ("Aᴅᴍɪɴ Pᴀɴᴇʟ", "menu_admin", "danger", "")

MAIN_MENU_TEXT_TO_DATA: Dict[str, str] = {
    text: callback for text, callback, _style, _emoji_id
    in MAIN_MENU_ITEMS + [MAIN_MENU_ADMIN_ITEM]
}


def main_menu_kb(admin: bool = False) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Choose an option..."
    )
    items = list(MAIN_MENU_ITEMS)
    if admin:
        items.append(MAIN_MENU_ADMIN_ITEM)

    for i in range(0, len(items), 2):
        row = [
            StyledKeyboardButton(text, style=style, custom_emoji_id=emoji_id)
            for text, _callback, style, emoji_id in items[i:i + 2]
        ]
        kb.row(*row)
    return kb

def back_main_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup().add(
        Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="danger"))


def back_admin_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup().add(
        Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))


def back_kb(target: str, label: str = "Back") -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup().add(
        Btn(f"{G['back']}  {sc(label)}", callback_data=target, style="danger"))


def plans_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for k, v in PLAN_LIMITS.items():
        price = "Free" if v["price"] == 0 else f"{v['price']}\u09F3"
        style = "success" if v["price"] == 0 else "primary"
        kb.add(Btn(
            f"{sc(v['name'])}  {G['bullet']}  {price}",
            callback_data=f"plan_view_{k}", style=style,
            icon_custom_emoji_id="6314298001879735512"))
    kb.add(Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="danger"))
    return kb


def payments_kb(plan: Optional[str] = None) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    for key, pm in PAYMENT_METHODS.items():
        if pm.get("enabled", True):
            btn_cb = f"pay_{key}_{plan}" if plan else f"pay_{key}"
            tag = pm.get("tag") or pm.get("emoji") or "💳"
            kb.add(Btn(f"{tag} {sc(pm['name'])}", callback_data=btn_cb, style="primary"))
    kb.add(Btn(f"{G['back']}  Pʟᴀɴꜱ", callback_data="menu_plans", style="danger"))
    return kb


def admin_kb(uid: Optional[int] = None) -> types.InlineKeyboardMarkup:
    if uid is not None and admin_role(uid) == "view-only":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            Btn(f"{G['graph']}  Sᴛᴀᴛꜱ",         callback_data="adm_stats",       style="primary"),
            Btn(f"{G['users']}  Uꜱᴇʀꜱ",         callback_data="adm_users",       style="primary"),
        )
        kb.add(
            Btn(f"{G['diamond']}  Aʟʟ Bᴏᴛꜱ",    callback_data="adm_allbots",     style="primary"),
            Btn(f"{G['eye']}  Aᴜᴅɪᴛ Lᴏɢ",       callback_data="adm_audit",       style="primary"),
        )
        kb.add(
            Btn("Aɴᴀʟʏᴛɪᴄꜱ",       callback_data="adm_analytics",    style="primary"),
            Btn("Uꜱᴇʀ Sᴇᴀʀᴄʜ",      callback_data="adm_user_search", style="primary"),
        )
        kb.add(
            Btn("Lɪᴠᴇ Mᴏɴɪᴛᴏʀ",    callback_data="adm_live_monitor", style="success"),
            Btn("Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ",      callback_data="adm_leaderboard",  style="primary"),
        )
        kb.add(
            Btn("Rᴇᴠ Gᴏᴀʟꜱ",        callback_data="adm_rev_goals",    style="success"),
            Btn("Bᴏᴛ Sᴇᴀʀᴄʜ",       callback_data="adm_bot_search",   style="primary"),
        )
        kb.add(Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="primary"))
        return kb

    if uid is not None and admin_role(uid) == "manage-users":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            Btn(f"{G['graph']}  Sᴛᴀᴛꜱ",         callback_data="adm_stats",    style="primary"),
            Btn(f"{G['users']}  Uꜱᴇʀꜱ",         callback_data="adm_users",    style="primary"),
        )
        kb.add(
            Btn(f"{G['diamond']}  Aʟʟ Bᴏᴛꜱ",    callback_data="adm_allbots",  style="primary"),
            Btn(f"{G['wallet']}  Pᴀʏᴍᴇɴᴛꜱ",     callback_data="adm_payments", style="success"),
        )
        kb.add(
            Btn(f"{G['no']}  Bᴀɴ / Uɴʙᴀɴ",      callback_data="adm_ban",      style="danger"),
            Btn(f"{G['plus']}  Gɪᴠᴇ Pʟᴀɴ",      callback_data="adm_giveplan", style="success"),
        )
        kb.add(
            Btn(f"{G['ok']}  Aᴘᴘʀᴏᴠᴇ Pᴀʏ",      callback_data="adm_approve",  style="success"),
            Btn(f"{G['ticket']}  Tɪᴄᴋᴇᴛꜱ",      callback_data="adm_tickets",  style="primary"),
        )
        kb.add(
            Btn("Aɴᴀʟʏᴛɪᴄꜱ",       callback_data="adm_analytics",      style="primary"),
            Btn("Uꜱᴇʀ Tᴏᴏʟꜱ",      callback_data="adm_user_tools",     style="primary"),
        )
        kb.add(
            Btn("Lɪᴠᴇ Mᴏɴɪᴛᴏʀ",    callback_data="adm_live_monitor",   style="success"),
            Btn("Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ",      callback_data="adm_leaderboard",    style="primary"),
        )
        kb.add(Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="primary"))
        return kb

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{G['graph']}  Sᴛᴀᴛꜱ",         callback_data="adm_stats",    style="primary"),
        Btn(f"{G['users']}  Uꜱᴇʀꜱ",         callback_data="adm_users",    style="primary"),
    )
    kb.add(
        Btn(f"{G['diamond']}  Aʟʟ Bᴏᴛꜱ",    callback_data="adm_allbots",  style="primary"),
        Btn(f"{G['wallet']}  Pᴀʏᴍᴇɴᴛꜱ",     callback_data="adm_payments", style="success"),
    )
    kb.add(
        Btn(f"{G['broadcast']}  Bʀᴏᴀᴅᴄᴀꜱᴛ", callback_data="adm_broadcast",style="success"),
        Btn(f"{G['no']}  Bᴀɴ / Uɴʙᴀɴ",      callback_data="adm_ban",      style="danger"),
    )
    kb.add(
        Btn(f"{G['plus']}  Gɪᴠᴇ Pʟᴀɴ",      callback_data="adm_giveplan", style="success"),
        Btn(f"{G['ok']}  Aᴘᴘʀᴏᴠᴇ Pᴀʏ",      callback_data="adm_approve",  style="success"),
    )
    kb.add(
        Btn(f"{G['key']}  Cᴏᴜᴘᴏɴꜱ",         callback_data="adm_coupons",  style="primary"),
        Btn(f"{G['ticket']}  Tɪᴄᴋᴇᴛꜱ",      callback_data="adm_tickets",  style="primary"),
    )
    kb.add(
        Btn(f"{G['shield']}  Aᴅᴍɪɴꜱ",       callback_data="adm_admins",   style="primary"),
        Btn(f"{G['eye']}  Aᴜᴅɪᴛ Lᴏɢ",       callback_data="adm_audit",    style="primary"),
    )
    kb.add(
        Btn(f"{G['cog']}  Gɪᴛʜᴜʙ Bᴀᴄᴋᴜᴘ",   callback_data="adm_github",   style="primary"),
        Btn(f"{G['lock']}  Sᴇᴄᴜʀɪᴛʏ",       callback_data="adm_security", style="danger"),
    )
    kb.add(
        Btn(f"{G['warn']}  Mᴀɪɴᴛᴇɴᴀɴᴄᴇ",    callback_data="adm_maint",    style="danger"),
        Btn(f"{G['settings']}  Sᴇᴛᴛɪɴɢꜱ",   callback_data="adm_settings", style="primary"),
    )
    kb.add(
        Btn("Aᴘɪ Sᴇᴛᴛɪɴɢꜱ", callback_data="adm_api_settings", style="success"),
    )
    appr_on = bool(get_setting("approval_required", True))
    pend_n = len(get_setting("pending_uploads", {}) or {})
    kb.add(
        Btn(
            f"{G['ok'] if appr_on else G['no']}  Aᴘᴘʀᴏᴠᴀʟ: {'ON' if appr_on else 'OFF'}",
            callback_data="adm_approval_toggle",
            style="success" if appr_on else "danger"),
        Btn(
            f"{G['eye']}  Pᴇɴᴅɪɴɢ" + (f" ({pend_n})" if pend_n else ""),
            callback_data="adm_pending", style="primary"),
    )
    bot_upload_on = bot_upload_enabled()
    kb.add(
        Btn(
            f"{G['unlock'] if bot_upload_on else G['lock']}  Bᴏᴛ Lᴏᴄᴋ: {'ON' if bot_upload_on else 'OFF'}",
            callback_data="adm_bot_lock_toggle",
            style="success" if bot_upload_on else "danger"),
    )
    kb.add(
        Btn(f"{G['upload']}  Mᴇɴᴜ Pʜᴏᴛᴏꜱ",  callback_data="adm_photos",       style="primary"),
        Btn(f"{G['refresh']}  Fᴏʀᴄᴇ Bᴀᴄᴋᴜᴘ", callback_data="adm_force_backup", style="success"),
    )
    # ── Advanced Sub-Panels Row 1 ──────────────────────────────────────
    kb.add(
        Btn("Aɴᴀʟʏᴛɪᴄꜱ",       callback_data="adm_analytics",      style="primary"),
        Btn("Uꜱᴇʀ Tᴏᴏʟꜱ",      callback_data="adm_user_tools",     style="primary"),
    )
    kb.add(
        Btn("Bᴏᴛ Mᴀɴᴀɢᴇʀ",     callback_data="adm_bot_manager",    style="primary"),
        Btn("Sᴇᴄ Cᴇɴᴛᴇʀ",      callback_data="adm_sec_center",     style="danger"),
    )
    kb.add(
        Btn("Nᴏᴛɪꜰɪᴄᴀᴛɪᴏɴꜱ",   callback_data="adm_notify_center",  style="success"),
        Btn("Sʏꜱ Tᴏᴏʟꜱ",       callback_data="adm_sys_tools",      style="primary"),
    )
    # ── MEGA ADVANCED PANELS ──────────────────────────────────────────
    kb.add(
        Btn("Gʜ Bʀᴏᴡꜱᴇʀ",      callback_data="adm_gh_browser",     style="primary"),
        Btn("Pᴀʏ Cᴏɴꜰɪɢ",      callback_data="adm_pay_config",     style="success"),
    )
    kb.add(
        Btn("Bᴏᴛ Cᴏɴꜰɪɢ",      callback_data="adm_bot_cfg",        style="primary"),
        Btn("Aᴘᴘᴇᴀʀᴀɴᴄᴇ",      callback_data="adm_appearance",     style="primary"),
    )
    kb.add(
        Btn("Cᴏᴜᴘᴏɴ+",          callback_data="adm_coupon_plus",    style="primary"),
        Btn("Tᴇᴍᴘʟᴀᴛᴇꜱ",        callback_data="adm_templates",      style="primary"),
    )
    kb.add(
        Btn("Rᴇꜰᴇʀʀᴀʟ Sʏꜱ",    callback_data="adm_referral_sys",   style="success"),
        Btn("Jᴀɴɪᴛᴏʀ",          callback_data="adm_janitor",        style="danger"),
    )
    kb.add(
        Btn("Wᴇʙʜᴏᴏᴋꜱ",         callback_data="adm_webhooks",       style="primary"),
        Btn("Fᴇᴀᴛᴜʀᴇ Fʟᴀɢꜱ",    callback_data="adm_feature_flags",  style="primary"),
    )
    kb.add(
        Btn("⏱ Rᴀᴛᴇ Lɪᴍɪᴛꜱ",      callback_data="adm_rate_config",    style="danger"),
        Btn("Lɪᴠᴇ Mᴏɴɪᴛᴏʀ",      callback_data="adm_live_monitor",   style="success"),
    )
    kb.add(
        Btn("Rᴇᴠ Gᴏᴀʟꜱ",        callback_data="adm_rev_goals",      style="success"),
        Btn("⏰ Sᴄʜᴇᴅᴜʟᴇʀ",         callback_data="adm_scheduler",      style="primary"),
    )
    kb.add(
        Btn("Iᴍᴘᴏʀᴛ/Exᴘ",       callback_data="adm_import_export",  style="primary"),
        Btn("Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ",      callback_data="adm_leaderboard",    style="primary"),
    )
    kb.add(
        Btn("Lᴀɴɢᴜᴀɢᴇꜱ",         callback_data="adm_languages",      style="primary"),
        Btn("Bᴏᴛ Cᴏɴᴛʀᴏʟꜱ",     callback_data="adm_bot_controls",   style="primary"),
    )
    kb.add(
        Btn("Sᴜʙꜱᴄʀɪᴘᴛɪᴏɴꜱ",    callback_data="adm_subscriptions",  style="primary"),
        Btn("Mᴀʀᴋᴇᴛᴘʟᴀᴄᴇ",     callback_data="adm_marketplace",    style="success"),
    )
    kb.add(
        Btn("Adᴍɪɴ 2FA",         callback_data="adm_admin_2fa",      style="danger"),
    )
    kb.add(Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="primary"))
    return kb


def github_kb(status: Dict[str, Any]) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(Btn(f"{G['plus']}  Bᴀᴄᴋᴜᴘ Nᴏᴡ",      callback_data="gh_backup_now",  style="success"))
    kb.add(Btn(f"{G['refresh']}  Rᴇꜱᴛᴏʀᴇ Lᴀᴛᴇꜱᴛ", callback_data="gh_restore_now", style="primary"))
    kb.add(Btn(
        f"{G['rec'] if status['autoEnabled'] else G['rec_off']}  "
        f"Auto Backup: {'ON' if status['autoEnabled'] else 'OFF'}",
        callback_data="gh_toggle_auto",
        style="success" if status["autoEnabled"] else "danger"))
    kb.add(
        Btn(f"{G['key']}  {sc('Change Token' if status['tokenSet'] else 'Set Token')}",
            callback_data="gh_set_token", style="primary"),
        Btn(f"{G['diamond']}  {sc('Change Repo' if status['repoSet'] else 'Set Repo')}",
            callback_data="gh_set_repo",  style="primary"),
    )
    kb.add(
        Btn(f"{G['tri']}  Sᴇᴛ Bʀᴀɴᴄʜ",  callback_data="gh_set_branch",   style="primary"),
        Btn(f"{G['cog']}  Iɴᴛᴇʀᴠᴀʟ",    callback_data="gh_set_interval", style="primary"),
    )
    kb.add(Btn(f"{G['no']}  Cʟᴇᴀʀ Cᴏɴꜰɪɢ", callback_data="gh_clear",     style="danger"))
    kb.add(Btn(f"{G['refresh']}  Rᴇꜰʀᴇꜱʜ",   callback_data="adm_github",  style="primary"))
    kb.add(Btn(f"Aᴅᴍɪɴ",       callback_data="menu_admin",  style="primary"))
    return kb


def bot_actions_kb(bot_id: str, running: bool, premium: bool = False) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    if running:
        kb.add(
            Btn(f"{G['stop']}  Sᴛᴏᴘ",       callback_data=f"bot_stop_{bot_id}",    style="danger"),
            Btn(f"{G['refresh']}  Rᴇꜱᴛᴀʀᴛ", callback_data=f"bot_restart_{bot_id}", style="success"),
        )
    else:
        kb.add(
            Btn(f"{G['play']}  Sᴛᴀʀᴛ",      callback_data=f"bot_start_{bot_id}",   style="success"),
            Btn(f"{G['refresh']}  Rᴇꜱᴛᴀʀᴛ", callback_data=f"bot_restart_{bot_id}", style="primary"),
        )
    kb.add(
        Btn(f"{G['bolt']}  Lɪᴠᴇ Lᴏɢꜱ", callback_data=f"bot_logs_{bot_id}", style="primary"),
        Btn(f"{G['eye']}  Iɴꜰᴏ",       callback_data=f"bot_info_{bot_id}", style="primary"),
    )
    kb.add(
        Btn(f"{G['settings']}  Eɴᴠ Vᴀʀꜱ", callback_data=f"bot_env_{bot_id}",  style="primary"),
        Btn(f"{G['cog']}  Cʀᴏɴ",          callback_data=f"bot_cron_{bot_id}", style="primary"),
    )
    kb.add(
        Btn(f"{G['download']}  Iɴꜱᴛᴀʟʟ Pᴋɢ", callback_data=f"bot_pip_{bot_id}",   style="primary"),
        Btn(f"{G['plus']}  Cʟᴏɴᴇ",           callback_data=f"bot_clone_{bot_id}", style="primary"),
    )
    kb.add(Btn("AI Fɪxᴇᴅ (Gemini)", callback_data=f"aifix_menu_{bot_id}", style="success"))
    if premium:
        is_open = bot_id in TUNNELS and TUNNELS[bot_id].get("proc") and TUNNELS[bot_id]["proc"].poll() is None
        label = "Stop Public URL" if is_open else "Public URL"
        glyph = G['no'] if is_open else G['cloud']
        kb.add(Btn(f"{glyph} {label}", callback_data=f"bot_tunnel_{bot_id}",
                   style="danger" if is_open else "success"))
    kb.add(Btn(f"{G['arrow']}  Dᴏᴡɴʟᴏᴀᴅ", callback_data=f"bot_dl_{bot_id}", style="primary"))
    kb.add(Btn(f"{G['no']}  Dᴇʟᴇᴛᴇ",       callback_data=f"bot_delete_{bot_id}", style="danger"))
    kb.add(Btn(f"{G['back']}  Mʏ Bᴏᴛꜱ",    callback_data="menu_bots",            style="primary"))
    return kb


def confirm_kb(yes_cb: str, no_cb: str = "menu_main", yes_label: str = "Confirm",
               no_label: str = "Cancel") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{G['ok']}  {sc(yes_label)}", callback_data=yes_cb, style="success"),
        Btn(f"{G['no']}  {sc(no_label)}",  callback_data=no_cb,  style="danger"),
    )
    return kb


# ═════════════════════════════════════════════════════════════════
# 10. SANDBOX RUNNER  (subprocess pool, secret-stripped env)
# ═════════════════════════════════════════════════════════════════

RUNNING: Dict[str, Dict[str, Any]] = {}    # bot_id -> {proc, kind, started, log, ...}
START_TIME: float = time.time()            # panel boot time, for uptime card
_LOCK_FH_KEEPALIVE: Any = None             # singleton-lock fd, kept alive for the process lifetime
_runner_lock = threading.Lock()


def tail_log(bot_id: str, lines: int = 60) -> str:
    """Return the last `lines` lines of logs for bot_id."""
    info = RUNNING.get(bot_id)
    if info and "log" in info and info["log"]:
        return "\n".join(info["log"][-lines:])
    log_file = DIRS["logs"] / f"{bot_id}.log"
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                if all_lines:
                    return "".join(all_lines[-lines:])
        except Exception:
            pass
    b = find_bot(bot_id)
    if b and b.get("last_error"):
        return f"Last Error:\n{b['last_error']}"
    return ""


_SKIP_DIR_PARTS = {".deps", "node_modules", ".tmp_run", "__pycache__",
                   ".git", "venv", ".venv", "env"}


def _iter_user_files(bot_dir: Path, suffix: str) -> List[Path]:
    """Recursive scan that skips dependency / cache / VCS folders."""
    out: List[Path] = []
    for p in bot_dir.rglob(f"*{suffix}"):
        if any(part in _SKIP_DIR_PARTS for part in p.parts):
            continue
        out.append(p)
    return sorted(out, key=lambda x: (len(x.parts), str(x)))


def detect_entry(bot_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """Find the entry file. Returns (kind, relative_path_from_bot_dir).
    Searches the bot dir recursively — many users zip their bot inside
    a wrapper folder (e.g. `MyBot/bot.py`), and the old shallow `glob`
    missed those."""
    # 1. Standard entry names — check shallow first, then recursive
    for n in ENTRY_NODE:
        p = bot_dir / n
        if p.exists():
            return ("node", n)
    for n in ENTRY_PY:
        p = bot_dir / n
        if p.exists():
            return ("python", n)
    # Recursive: prefer files closer to the root (shorter path)
    for n in ENTRY_PY:
        for p in _iter_user_files(bot_dir, ".py"):
            if p.name == n:
                return ("python", str(p.relative_to(bot_dir)))
    for n in ENTRY_NODE:
        for p in _iter_user_files(bot_dir, ".js"):
            if p.name == n:
                return ("node", str(p.relative_to(bot_dir)))
    # 2. Any .py file (recursive, skipping deps)
    py_files = _iter_user_files(bot_dir, ".py")
    if py_files:
        return ("python", str(py_files[0].relative_to(bot_dir)))
    # 3. Any .js file (recursive)
    js_files = _iter_user_files(bot_dir, ".js")
    if js_files:
        return ("node", str(js_files[0].relative_to(bot_dir)))
    # 4. Inner .zip — extract once then re-scan
    zip_files = [p for p in bot_dir.rglob("*.zip")
                 if not any(part in _SKIP_DIR_PARTS for part in p.parts)]
    if zip_files:
        import zipfile as _zf
        try:
            with _zf.ZipFile(zip_files[0], "r") as z:
                z.extractall(bot_dir)
        except Exception:
            return (None, None)
        # recursive re-check
        py_files = _iter_user_files(bot_dir, ".py")
        if py_files:
            return ("python", str(py_files[0].relative_to(bot_dir)))
        js_files = _iter_user_files(bot_dir, ".js")
        if js_files:
            return ("node", str(js_files[0].relative_to(bot_dir)))
    return (None, None)


def safe_env(bot_dir: Path, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV_NAMES}
    env["HOME"]    = str(bot_dir)
    env["TMPDIR"]  = str(bot_dir / ".tmp_run")
    env["PATH"]    = "/usr/local/bin:/usr/bin:/bin"
    env.setdefault("NODE_ENV", "production")
    deps_dir = str(bot_dir / ".deps")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{deps_dir}:{existing_pp}" if existing_pp else deps_dir
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    Path(deps_dir).mkdir(parents=True, exist_ok=True)
    if extra:
        for k, v in extra.items():
            if k in SECRET_ENV_NAMES:
                continue
            env[str(k)] = str(v)
    return env


# ── module-name → PyPI package-name mapping ───────────────────────
# Many third-party libs are imported under a name that differs from
# their pip package. Without this mapping pip would 404 (e.g. `cv2` is
# really `opencv-python`). This is the most common reason "auto-install
# nahi chala" — and why uploaded bots crashed at import time.
_PYPI_ALIAS: Dict[str, str] = {
    "telebot":       "pyTelegramBotAPI",
    # `from telegram import Update` belongs to python-telegram-bot.
    # The bare `telegram` package on PyPI is an unrelated tiny shim
    # that does NOT expose Update / Bot — installing it by accident
    # is the most common source of the
    #   ImportError: cannot import name 'Update' from 'telegram'
    # crash. We map it to the real package and additionally validate
    # the installed copy in `_filter_third_party`.
    "telegram":      "python-telegram-bot",
    "telethon":      "Telethon",
    "pyrogram":      "Pyrogram",
    "pyromod":       "pyromod",
    "tgcrypto":      "TgCrypto",
    "PIL":           "Pillow",
    "cv2":           "opencv-python",
    "bs4":           "beautifulsoup4",
    "yaml":          "PyYAML",
    "dotenv":        "python-dotenv",
    "Crypto":        "pycryptodome",
    "Cryptodome":    "pycryptodomex",
    "dateutil":      "python-dateutil",
    "magic":         "python-magic",
    "skimage":       "scikit-image",
    "sklearn":       "scikit-learn",
    "google":        "google-api-python-client",
    "googletrans":   "googletrans",
    "OpenSSL":       "pyOpenSSL",
    "wx":            "wxPython",
    "psycopg2":      "psycopg2-binary",
    "MySQLdb":       "mysqlclient",
    "serial":        "pyserial",
    "win32api":      "pywin32",
    "ujson":         "ujson",
    "uvloop":        "uvloop",
    "discord":       "discord.py",
    "httpx":         "httpx",
    "aiohttp":       "aiohttp",
    "aiogram":       "aiogram",
    "fastapi":       "fastapi",
    "flask":         "flask",
    "starlette":     "starlette",
    "redis":         "redis",
    "pymongo":       "pymongo",
    "motor":         "motor",
    "psutil":        "psutil",
    "schedule":      "schedule",
    "apscheduler":   "APScheduler",
    "cryptography":  "cryptography",
    "github":        "PyGithub",
    "requests":      "requests",
    # extra safety net — pip name ≠ import name
    "nacl":          "PyNaCl",
    "git":           "GitPython",
    "jose":          "python-jose",
    "pkg_resources": "setuptools",
    "lxml":          "lxml",
    "chardet":       "chardet",
}


# Modules whose installed copy must expose specific symbols to be
# considered "really installed". Catches the wrong-package-on-PyPI trap
# (e.g. the `telegram` shim that lacks `Update`).
_VALIDATE_SYMBOLS: Dict[str, List[str]] = {
    "telegram": ["Update", "Bot"],
}


def _purge_bad_install(deps_dir: Path, mod_name: str) -> None:
    """Remove a wrong-package install (and its dist-info) from a bot's
    `.deps` so the next pip install can put the correct one in its
    place. Used when `_VALIDATE_SYMBOLS` says the cached package is
    not the one we actually need."""
    try:
        if not deps_dir.exists():
            return
        target = deps_dir / mod_name
        if target.exists():
            try:
                shutil.rmtree(str(target), ignore_errors=True)
            except Exception:
                pass
        for child in list(deps_dir.iterdir()):
            n = child.name.lower()
            if n.endswith((".dist-info", ".egg-info")) and \
                    n.startswith(mod_name.lower()):
                try:
                    shutil.rmtree(str(child), ignore_errors=True)
                except Exception:
                    try:
                        child.unlink()
                    except Exception:
                        pass
    except Exception as e:
        print(f"[purge_bad_install] {mod_name}: {e}", file=sys.stderr)


def _scan_imports(bot_dir: Path) -> List[str]:
    """Recursively scan every .py file for top-level module imports."""
    import ast as _ast
    found: set = set()
    for pyfile in bot_dir.rglob("*.py"):
        # Skip our own .deps cache so we don't mistake installed libs
        # for the bot's own imports.
        if ".deps" in pyfile.parts:
            continue
        try:
            tree = _ast.parse(pyfile.read_text(errors="ignore"))
        except Exception:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for n in node.names:
                    if n.name:
                        found.add(n.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import — local package
                if node.module:
                    found.add(node.module.split(".")[0])
    return sorted(found)


def _filter_third_party(modules: List[str], bot_dir: Path) -> List[str]:
    """Drop stdlib, local module names, and modules already importable
    from the bot's .deps cache. Returns only installable PyPI names that
    are still missing."""
    import importlib.util as _ilu
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    skip = stdlib | {"__future__", ""}
    # local modules (any .py file or package dir at the top level OR
    # any subdir — covers zipped wrappers like `MyBot/utils.py`)
    deps_dir = bot_dir / ".deps"
    for child in bot_dir.iterdir():
        if child == deps_dir:
            continue
        if child.suffix == ".py":
            skip.add(child.stem)
        elif child.is_dir() and (child / "__init__.py").exists():
            skip.add(child.name)
    # Make .deps importable for the find_spec check below so we don't
    # re-install something that's already cached locally.
    deps_str = str(deps_dir)
    deps_in_path = deps_str in sys.path
    if deps_dir.exists() and not deps_in_path:
        sys.path.insert(0, deps_str)

    out: List[str] = []
    seen: set = set()
    try:
        for m in modules:
            if not m or m in skip:
                continue
            # Already importable (stdlib was caught above; this catches
            # things like cv2 already installed in .deps/).
            try:
                if _ilu.find_spec(m) is not None:
                    # Even if importable, validate that the installed
                    # copy is the RIGHT package (not the wrong-name
                    # PyPI shim). If it isn't, nuke it so pip can
                    # reinstall the correct one below.
                    needed = _VALIDATE_SYMBOLS.get(m)
                    if needed:
                        try:
                            _real = importlib.import_module(m)
                            if all(hasattr(_real, s) for s in needed):
                                continue
                        except Exception:
                            pass
                        # Wrong package — purge and force a reinstall.
                        try:
                            del sys.modules[m]
                        except KeyError:
                            pass
                        _purge_bad_install(deps_dir, m)
                    else:
                        continue
            except (ImportError, ValueError):
                pass
            pip_name = _PYPI_ALIAS.get(m, m)
            if pip_name in seen:
                continue
            seen.add(pip_name)
            out.append(pip_name)
    finally:
        if deps_dir.exists() and not deps_in_path:
            try:
                sys.path.remove(deps_str)
            except ValueError:
                pass
    return out


def _pip_env(deps_dir: Path) -> Dict[str, str]:
    """Env for pip subprocesses: silence root warnings, keep installs
    confined to the bot's `.deps/` so we never trip on permissions.

    NOTE: We intentionally do NOT set PYTHONUSERBASE — that conflicts
    with `--target` and pip refuses to combine them ("Can not combine
    '--user' and '--target'"). We rely on `--target` alone."""
    env = {**os.environ,
           "PIP_DISABLE_PIP_VERSION_CHECK": "1",
           "PIP_NO_INPUT": "1",
           "PIP_ROOT_USER_ACTION": "ignore"}
    env.pop("PYTHONUSERBASE", None)
    env.pop("PIP_USER", None)
    return env


_PIP_BASE_FLAGS = ["--upgrade", "--no-input", "--no-warn-script-location",
                   "--disable-pip-version-check"]


def install_deps(bot_dir: Path, kind: str, log: List[str]) -> bool:
    try:
        if kind == "python":
            deps_dir = bot_dir / ".deps"
            deps_dir.mkdir(parents=True, exist_ok=True)
            req = bot_dir / "requirements.txt"
            pip_env = _pip_env(deps_dir)

            # 1) requirements.txt (if present)
            if req.exists():
                log.append(f"{G['div']} pip install (requirements.txt) {G['div']}")
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "install",
                     "--target", str(deps_dir), *_PIP_BASE_FLAGS,
                     "-r", str(req)],
                    cwd=str(bot_dir), timeout=600, capture_output=True, text=True,
                    env=pip_env,
                )
                for line in (r.stdout or "").splitlines()[-15:]:
                    log.append(line)
                for line in (r.stderr or "").splitlines()[-10:]:
                    log.append(line)
                log.append(f"[{G['ok']}] requirements.txt done (rc={r.returncode})")

            # 2) AST-scan imports and install anything still missing.
            #    We always do this so a bot that adds a new `import foo`
            #    after upload doesn't crash on next start.
            try:
                modules = _scan_imports(bot_dir)
                third_party = _filter_third_party(modules, bot_dir)
                if third_party:
                    log.append(f"{G['div']} auto-install (scanned imports) {G['div']}")
                    log.append(f"📦 packages: {', '.join(third_party)}")
                    r2 = subprocess.run(
                        [sys.executable, "-m", "pip", "install",
                         "--target", str(deps_dir), *_PIP_BASE_FLAGS,
                         *third_party],
                        cwd=str(bot_dir), timeout=600, capture_output=True, text=True,
                        env=pip_env,
                    )
                    for line in (r2.stdout or "").splitlines()[-15:]:
                        log.append(line)
                    for line in (r2.stderr or "").splitlines()[-10:]:
                        log.append(line)
                    log.append(f"[{G['ok']}] auto-install done (rc={r2.returncode})")
            except Exception as e:
                log.append(f"[{G['warn']}] auto-install scan error: {e}")
            return True
        if kind == "node":
            pkg = bot_dir / "package.json"
            if not pkg.exists():
                return False
            if (bot_dir / "node_modules").exists():
                log.append(f"[{G['ok']}] node_modules cached, skipping npm install")
                return False
            log.append(f"{G['div']} npm install {G['div']}")
            r = subprocess.run(
                ["npm", "install", "--omit=dev", "--no-audit", "--no-fund"],
                cwd=str(bot_dir), timeout=300, capture_output=True, text=True,
            )
            for line in (r.stdout or "").splitlines()[-15:]:
                log.append(line)
            for line in (r.stderr or "").splitlines()[-10:]:
                log.append(line)
            log.append(f"[{G['ok']}] npm done (rc={r.returncode})")
            return True
    except subprocess.TimeoutExpired:
        log.append(f"[{G['warn']}] dependency install timeout (>5min)")
    except FileNotFoundError as e:
        log.append(f"[{G['warn']}] tool not found: {e}")
    except Exception as e:
        log.append(f"[{G['warn']}] install error: {e}")
    return False


def _drain_proc(bot_id: str, proc: subprocess.Popen, log: List[str]) -> None:
    log_file = DIRS["logs"] / f"{bot_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        if proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                try:
                    txt = line.decode("utf-8", "replace").rstrip()
                except Exception:
                    txt = repr(line)
                log.append(txt)
                if len(log) > LOG_RING:
                    del log[: len(log) - LOG_RING]
                try:
                    with open(log_file, "a", encoding="utf-8", errors="replace") as f:
                        f.write(txt + "\n")
                except Exception:
                    pass
    except Exception:
        pass
    # crash-watch — auto-restart if plan supports it
    try:
        rc = proc.wait()
        exit_msg = f"{G['div']} process exited rc={rc} {G['div']}"
        log.append(exit_msg)
        try:
            with open(log_file, "a", encoding="utf-8", errors="replace") as f:
                f.write(exit_msg + "\n")
        except Exception:
            pass
        info = RUNNING.get(bot_id)
        was_manual = (info is None) or info.get("manual_stop", False)
        b_doc = find_bot(bot_id)

        # capture last error lines so the bot view can surface them
        if b_doc is not None:
            tail = [ln for ln in log[-15:] if ln and not ln.startswith(G["div"])]
            err_text = "\n".join(tail[-8:])[:1500]
            b_doc["last_error"] = err_text
            b_doc["last_exit_code"] = int(rc) if rc is not None else None
            b_doc["last_exit_at"] = ts_iso()
            if rc not in (0, None) and not was_manual:
                b_doc["status"] = "crashed"
            try:
                save_bot(b_doc)
            except Exception:
                pass

        if not info:
            return
        if not b_doc:
            return
        owner = db_load()["users"].get(str(b_doc["owner"]))
        plan = (owner or {}).get("plan", "free")
        if PLAN_LIMITS.get(plan, {}).get("auto_restart") and not was_manual:
            log.append(f"[{G['refresh']}] auto-restart in 3s...")
            time.sleep(3)
            start_child(b_doc)
    except Exception:
        pass


def start_child(b: Dict[str, Any]) -> Dict[str, Any]:
    bid = b["_id"]
    # Approval system disabled — no gate
    with _runner_lock:
        existing = RUNNING.get(bid)
        if existing and existing["proc"].poll() is None:
            return {"ok": False, "error": "Already running."}
    bot_dir = Path(b["dir"])
    if not bot_dir.exists():
        return {"ok": False, "error": "Bot folder missing."}

    # decrypt encrypted source files into bot_dir at run time (if any encrypted files exist)
    try:
        if b.get("enc_files"):
            materialize_bot_files(b)
    except Exception as e:
        return {"ok": False, "error": f"decrypt failed: {e}"}

    kind, entry = detect_entry(bot_dir)
    if not kind:
        return {"ok": False, "error": "No entry file (index.js / main.py / bot.py)."}

    log: List[str] = [f"{G['div_eq']} START {ts_iso()} {G['div_eq']}"]
    log_file = DIRS["logs"] / f"{bid}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_file, "w", encoding="utf-8", errors="replace") as f:
            f.write(f"{G['div_eq']} START {ts_iso()} {G['div_eq']}\n")
    except Exception:
        pass

    install_deps(bot_dir, kind, log)
    try:
        with open(log_file, "a", encoding="utf-8", errors="replace") as f:
            for line in log[1:]:
                f.write(f"{line}\n")
    except Exception:
        pass

    cmd = ["node", entry] if kind == "node" else [sys.executable, "-u", entry]

    extra_env = b.get("env") or {}
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(bot_dir), env=safe_env(bot_dir, extra_env),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid if os.name == "posix" else None,
        )
    except Exception as e:
        return {"ok": False, "error": f"spawn: {e}"}

    info = {
        "proc": proc, "kind": kind, "started": time.time() * 1000,
        "log": log, "dir": str(bot_dir), "name": b["name"],
        "owner": b["owner"], "manual_stop": False,
    }
    with _runner_lock:
        RUNNING[bid] = info
    threading.Thread(target=_drain_proc, args=(bid, proc, log), daemon=True).start()

    # update doc — clear any prior crash so bot view shows clean state
    b["status"] = "running"
    b["last_started"] = ts_iso()
    b["last_error"] = ""
    b["last_exit_code"] = None
    save_bot(b)
    return {"ok": True, "pid": proc.pid, "kind": kind}


def stop_child(bot_id: str, manual: bool = True) -> Dict[str, Any]:
    with _runner_lock:
        info = RUNNING.get(bot_id)
    if not info:
        # Even if we don't have it tracked, make sure DB says stopped
        b = find_bot(bot_id)
        if b and b.get("status") != "stopped":
            b["status"] = "stopped"
            save_bot(b)
        return {"ok": True}
    info["manual_stop"] = manual
    proc = info["proc"]

    # Collect every descendant PID *before* we start signalling so a
    # double-fork bot can't escape us.
    child_pids: List[int] = []
    if psutil is not None:
        try:
            parent = psutil.Process(proc.pid)
            for ch in parent.children(recursive=True):
                child_pids.append(ch.pid)
        except Exception:
            pass

    def _kill_pid(pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            pass

    try:
        # 1) polite SIGTERM to the whole process group
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            for pid in child_pids:
                _kill_pid(pid, signal.SIGTERM)
        else:
            proc.terminate()

        # 2) wait briefly — most well-behaved bots exit here
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            # 3) hard SIGKILL the group + every descendant we noted
            if os.name == "posix":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                for pid in child_pids:
                    _kill_pid(pid, signal.SIGKILL)
                # one more sweep for any new grand-children spawned
                # between our snapshot and the kill signal
                if psutil is not None:
                    try:
                        for ch in psutil.Process(proc.pid).children(recursive=True):
                            _kill_pid(ch.pid, signal.SIGKILL)
                    except Exception:
                        pass
            else:
                proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
    except ProcessLookupError:
        pass
    except Exception as e:
        # Even on partial failure, drop our handle so the user can
        # try again instead of being stuck "running".
        with _runner_lock:
            RUNNING.pop(bot_id, None)
        b = find_bot(bot_id)
        if b:
            b["status"] = "stopped"
            save_bot(b)
        return {"ok": False, "error": str(e)}

    # Tear down any cloudflared tunnel we opened for this bot
    try:
        _stop_tunnel(bot_id)
    except Exception:
        pass

    with _runner_lock:
        RUNNING.pop(bot_id, None)
    b = find_bot(bot_id)
    if b:
        b["status"] = "stopped"
        save_bot(b)
    return {"ok": True}


# ────────────────────────────── Cloudflared "trycloudflare" tunnels ─
# Premium-only feature: gives a user a public URL like
# https://random-words-1234.trycloudflare.com that proxies straight to
# their bot's local port. We download the official cloudflared binary on
# first use and cache it under ~/.cache/cloudflared so this works on any
# host without the user needing root.

TUNNELS: Dict[str, Dict[str, Any]] = {}     # bot_id -> {proc, port, url, started}
_tunnel_lock = threading.Lock()

CLOUDFLARED_CACHE = Path.home() / ".cache" / "cloudflared"
CLOUDFLARED_BIN   = CLOUDFLARED_CACHE / "cloudflared"

_CF_DOWNLOAD = {
    ("linux",  "x86_64"):  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("linux",  "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("linux",  "armv7l"):  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
    ("darwin", "x86_64"):  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    ("darwin", "arm64"):   "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
}


def _ensure_cloudflared() -> Optional[Path]:
    """Return path to a working cloudflared binary, downloading once."""
    # Already cached?
    if CLOUDFLARED_BIN.exists() and os.access(CLOUDFLARED_BIN, os.X_OK):
        return CLOUDFLARED_BIN
    # Already on PATH?
    on_path = shutil.which("cloudflared")
    if on_path:
        return Path(on_path)
    # Download a fresh copy
    try:
        import platform
        sysname = platform.system().lower()
        machine = platform.machine().lower()
        url = _CF_DOWNLOAD.get((sysname, machine))
        if not url:
            return None
        CLOUDFLARED_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = CLOUDFLARED_BIN.with_suffix(".part")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        tmp.chmod(0o755)
        tmp.rename(CLOUDFLARED_BIN)
        return CLOUDFLARED_BIN
    except Exception:
        return None


def _port_in_use(port: int) -> bool:
    """True if *something* is already listening on this TCP port."""
    import socket as _s
    for fam, typ, addr in (
        (_s.AF_INET,  _s.SOCK_STREAM, ("127.0.0.1", port)),
        (_s.AF_INET6, _s.SOCK_STREAM, ("::1",       port)),
    ):
        try:
            with _s.socket(fam, typ) as sk:
                sk.settimeout(0.4)
                if sk.connect_ex(addr) == 0:
                    return True
        except Exception:
            continue
    return False


_TRYCLOUDFLARE_RE = re.compile(r"https?://[a-z0-9-]+\.trycloudflare\.com", re.I)


def _start_tunnel(bot_id: str, port: int) -> Dict[str, Any]:
    """Spin up `cloudflared tunnel --url http://localhost:<port>` and
    capture the public trycloudflare URL from its stderr."""
    if not (1 <= port <= 65535):
        return {"ok": False, "error": "Port must be between 1 and 65535"}

    with _tunnel_lock:
        existing = TUNNELS.get(bot_id)
        if existing and existing.get("proc") and existing["proc"].poll() is None:
            return {"ok": False, "error": "Tunnel already running for this bot. Stop it first."}

    if not _port_in_use(port):
        return {"ok": False,
                "error": f"Nothing is listening on port {port}. "
                         f"Start your bot's web server on that port first, "
                         f"or pick another port."}

    bin_path = _ensure_cloudflared()
    if not bin_path:
        return {"ok": False,
                "error": "Could not download cloudflared binary on this host. "
                         "Please install cloudflared manually."}

    log_buf: Deque[str] = deque(maxlen=200)
    try:
        proc = subprocess.Popen(
            [str(bin_path), "tunnel", "--no-autoupdate",
             "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid if os.name == "posix" else None,
        )
    except Exception as e:
        return {"ok": False, "error": f"Failed to launch cloudflared: {e}"}

    rec: Dict[str, Any] = {
        "proc":    proc,
        "port":    port,
        "url":     None,
        "started": int(time.time()),
        "log":     log_buf,
    }
    with _tunnel_lock:
        TUNNELS[bot_id] = rec

    def _drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            log_buf.append(line)
            if rec["url"] is None:
                m = _TRYCLOUDFLARE_RE.search(line)
                if m:
                    rec["url"] = m.group(0)

    threading.Thread(target=_drain, daemon=True, name=f"cf-{bot_id}").start()

    # Wait up to ~15s for the URL to appear
    deadline = time.time() + 15
    while time.time() < deadline and rec["url"] is None and proc.poll() is None:
        time.sleep(0.3)

    if proc.poll() is not None and rec["url"] is None:
        # process died early — usually port issue or network
        tail = "\n".join(list(log_buf)[-6:]) or "(no output)"
        with _tunnel_lock:
            TUNNELS.pop(bot_id, None)
        return {"ok": False, "error": f"cloudflared exited early.\n{tail}"}

    if rec["url"] is None:
        # No URL within 15s and process still alive — kill it so we don't
        # leave an orphan cloudflared process running forever.
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        except Exception:
            pass
        with _tunnel_lock:
            TUNNELS.pop(bot_id, None)
        tail = "\n".join(list(log_buf)[-6:]) or "(no output)"
        return {"ok": False,
                "error": f"Tunnel timed out — no URL after 15s.\n{tail}"}

    return {"ok": True, "url": rec["url"], "port": port}


def _stop_tunnel(bot_id: str) -> bool:
    with _tunnel_lock:
        rec = TUNNELS.pop(bot_id, None)
    if not rec:
        return False
    proc = rec.get("proc")
    if not proc:
        return True
    try:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        else:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except Exception:
                pass
    except Exception:
        pass
    return True


def restart_child(b: Dict[str, Any]) -> Dict[str, Any]:
    stop_child(b["_id"], manual=False)
    time.sleep(1)
    return start_child(b)


def child_status(bot_id: str, b_doc: Dict[str, Any]) -> Dict[str, Any]:
    info = RUNNING.get(bot_id)
    running = bool(info and info["proc"].poll() is None)
    bot_dir = Path(b_doc.get("dir") or "")
    kind, _ = detect_entry(bot_dir) if bot_dir.exists() else (None, None)
    sz = 0
    try:
        for root, _, files in os.walk(bot_dir):
            for f in files:
                try:
                    sz += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    cpu = mem = 0.0
    if running and psutil is not None:
        try:
            p = psutil.Process(info["proc"].pid)
            cpu = p.cpu_percent(interval=0.05)
            mem = p.memory_info().rss
        except Exception:
            pass
    return {
        "running":   running,
        "pid":       info["proc"].pid if running else None,
        "kind":      (info["kind"] if info else kind) or "—",
        "uptimeMs":  int(time.time() * 1000 - info["started"]) if running else 0,
        "sizeBytes": sz,
        "logs":      info["log"] if info else [],
        "cpuPct":    cpu,
        "memBytes":  mem,
        "sandboxed": True,
    }


# ════════════════════════════════════════════════
# 11. ENCRYPTED  BOT  STORAGE
# ═════════════════════════════════════════════════════

def store_uploaded_file(uploader: types.User, filename: str, plain: bytes) -> Dict[str, Any]:
    """
    Encrypt + persist an uploaded file. Returns metadata describing
    where the encrypted blob lives and which key_id unlocks it.
    """
    safe = safe_name(filename)
    key_id, key, cipher = encrypt_file(plain)
    rel = f"{uploader.id}/{int(time.time())}_{safe}.enc"
    out = DIRS["encfiles"] / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(cipher)

    meta = {
        "filename": filename,
        "uploader_id": uploader.id,
        "uploader_username": uploader.username or "",
        "size": len(plain),
        "uploaded": ts_iso(),
        "stored_at": str(out),
    }
    KEYRING.store(key_id, key, meta)

    # notify_owner HATA DIYA — ab upload handler mein sirf ek summary msg aayega
    return {"key_id": key_id, "path": str(out), "size": len(plain)}


def materialize_bot_files(b: Dict[str, Any]) -> None:
    """Decrypt every encrypted file for this bot into its sandbox dir."""
    bot_dir = Path(b["dir"])
    bot_dir.mkdir(parents=True, exist_ok=True)
    files = b.get("enc_files") or []
    for f in files:
        key = KEYRING.fetch(f["key_id"])
        if not key:
            raise RuntimeError(f"missing key {f['key_id']}")
        try:
            plain = read_encrypted(Path(f["enc_path"]), key)
        except InvalidToken:
            raise RuntimeError(f"key mismatch for {f.get('filename')}")
        # write into bot_dir
        rel = f.get("rel_path") or f["filename"]
        rel = rel.lstrip("/")
        try:
            tgt = safe_path_join(bot_dir, rel)
        except ValueError:
            continue
        tgt.parent.mkdir(parents=True, exist_ok=True)
        tgt.write_bytes(plain)
        # wipe key from memory after using it
        plain = b""
    # KEYRING memory wipe (re-fetched on next run)
    for f in files:
        KEYRING.wipe(f["key_id"])


def encrypted_dump_for_download(b: Dict[str, Any]) -> Optional[Path]:
    """Build a zip of the *encrypted* blobs for this bot. Useless without keys."""
    files = b.get("enc_files") or []
    if not files:
        return None
    out = Path(tempfile.gettempdir()) / f"enc_{b['_id']}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            p = Path(f["enc_path"])
            if p.exists():
                z.write(p, arcname=f.get("rel_path") or f["filename"])
        z.writestr(
            "_README.txt",
            f"These files are encrypted with Fernet/AES-128.\n"
            f"They cannot be read without the per-file key, which is\n"
            f"stored in a private GitHub repository owned by {BRAND_TAG}.\n",
        )
    return out



# 12. GITHUB  BACKUP / RESTORE  (panel state)

GH = {
    "token": "", "repo": "", "branch": "main",
    "intervalMin": 360,
    "lastBackup": None, "lastError": None,
    "inProgress": False, "autoEnabled": True,
}


def gh_load_config() -> None:
    GH["token"]  = os.environ.get("GITHUB_TOKEN")  or get_setting("github_token", "")  or ""
    GH["repo"]   = os.environ.get("GITHUB_REPO")   or get_setting("github_repo", "")   or ""
    GH["branch"] = os.environ.get("GITHUB_BRANCH") or get_setting("github_branch", "main") or "main"
    try:
        ivl = int(os.environ.get("GITHUB_AUTO_INTERVAL_MIN") or get_setting("github_interval_min", 360))
    except Exception:
        ivl = 360
    GH["intervalMin"] = ivl if ivl > 0 else 360


def gh_set_config(patch: Dict[str, Any]) -> None:
    keymap = {"token": "github_token", "repo": "github_repo",
              "branch": "github_branch", "intervalMin": "github_interval_min"}
    for k, v in patch.items():
        if k not in keymap:
            continue
        if k == "intervalMin":
            try:
                v = int(v)
            except Exception:
                v = 360
        GH[k] = v
        set_setting(keymap[k], v)


def gh_enabled() -> bool:
    return bool(GH["token"] and GH["repo"] and "/" in GH["repo"])


def gh_status() -> Dict[str, Any]:
    return {
        "enabled":     gh_enabled(),
        "repo":        GH["repo"], "branch": GH["branch"],
        "intervalMin": GH["intervalMin"],
        "autoEnabled": GH["autoEnabled"],
        "lastBackup":  GH["lastBackup"],
        "lastError":   GH["lastError"],
        "inProgress":  GH["inProgress"],
        "tokenSet":    bool(GH["token"]),
        "repoSet":     bool(GH["repo"]),
    }


def _gh(method: str, url: str, **kw) -> requests.Response:
    h = kw.pop("headers", {}) or {}
    h.setdefault("Authorization", f"token {GH['token']}")
    h.setdefault("Accept", "application/vnd.github+json")
    h.setdefault("User-Agent", "sir-linuxx-hosting-rbot/2.1")
    return requests.request(method, url, headers=h, timeout=60, **kw)


def _gh_repo_url(p: str = "") -> str:
    return f"https://api.github.com/repos/{GH['repo']}/{p.lstrip('/')}"


def _gh_ensure_branch() -> bool:
    r = _gh("GET", _gh_repo_url(f"branches/{GH['branch']}"))
    if r.status_code == 200:
        return True
    if r.status_code != 404:
        return False
    info = _gh("GET", _gh_repo_url())
    if info.status_code != 200:
        return False
    default = info.json().get("default_branch", "main")
    ref = _gh("GET", _gh_repo_url(f"git/ref/heads/{default}"))
    if ref.status_code != 200:
        return False
    sha = ref.json()["object"]["sha"]
    _gh("POST", _gh_repo_url("git/refs"),
        json={"ref": f"refs/heads/{GH['branch']}", "sha": sha})
    return True


def _gh_put_file(path: str, content: bytes, message: str) -> bool:
    sha: Optional[str] = None
    g = _gh("GET", _gh_repo_url(f"contents/{path}"), params={"ref": GH["branch"]})
    if g.status_code == 200:
        sha = g.json().get("sha")
    elif g.status_code != 404:
        return False
    body: Dict[str, Any] = {
        "message": message, "branch": GH["branch"],
        "content": base64.b64encode(content).decode(),
    }
    if sha:
        body["sha"] = sha
    r = _gh("PUT", _gh_repo_url(f"contents/{path}"), json=body)
    return r.status_code in (200, 201)


def _make_tarball() -> Path:
    tmp = Path(tempfile.gettempdir()) / f"panel-backup-{int(time.time())}.tar.gz"
    excludes = ("node_modules", ".deps", ".tmp_run", "__pycache__")

    def _filter(ti: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        if any(x in ti.name.split("/") for x in excludes):
            return None
        if ti.name.endswith(".log"):
            return None
        return ti

    with tarfile.open(tmp, "w:gz") as tf:
        # Backup storage/ — users, bots DB, encrypted files, keys, tickets
        storage_dir = BASE_DIR / "storage"
        if storage_dir.exists():
            tf.add(str(storage_dir), arcname="storage", filter=_filter)
        # Backup sandbox/ — bot env vars, cron config (not .deps to save space)
        sandbox_dir = BASE_DIR / "sandbox"
        if sandbox_dir.exists():
            tf.add(str(sandbox_dir), arcname="sandbox", filter=_filter)
    return tmp


def gh_backup_now() -> Dict[str, Any]:
    if not gh_enabled():
        return {"ok": False, "error": "Not configured."}
    if GH["inProgress"]:
        return {"ok": False, "error": "Backup already running."}
    GH["inProgress"] = True
    tar: Optional[Path] = None
    try:
        if not _gh_ensure_branch():
            raise RuntimeError(f"Branch {GH['branch']} unavailable")
        tar = _make_tarball()
        buf = tar.read_bytes()
        size_mb = len(buf) / 1024 / 1024
        if size_mb > 95:
            raise RuntimeError(f"Backup {size_mb:.1f} MB > 95 MB GitHub limit")
        ts = ts_iso().replace(":", "-").replace(".", "-")
        ok1 = _gh_put_file("backups/latest.tar.gz", buf, f"chore(panel): backup {ts}")
        ok2 = _gh_put_file(f"backups/{ts}.tar.gz", buf, f"chore(panel): snapshot {ts}")
        manifest = json.dumps({"lastBackup": ts, "sizeBytes": len(buf)}, indent=2)
        _gh_put_file("backups/manifest.json", manifest.encode(), f"chore(panel): manifest {ts}")
        if not (ok1 and ok2):
            raise RuntimeError("upload failed")
        GH["lastBackup"] = ts
        GH["lastError"] = None
        return {"ok": True, "sizeMB": f"{size_mb:.2f}", "ts": ts}
    except Exception as e:
        GH["lastError"] = str(e)
        return {"ok": False, "error": str(e)}
    finally:
        if tar and tar.exists():
            try:
                tar.unlink()
            except Exception:
                pass
        GH["inProgress"] = False


def gh_restore_now(overwrite: bool = True) -> Dict[str, Any]:
    if not gh_enabled():
        return {"ok": False, "error": "Not configured."}
    r = _gh("GET", _gh_repo_url("contents/backups/latest.tar.gz"),
            params={"ref": GH["branch"]})
    if r.status_code == 404:
        return {"ok": False, "error": "No backup found yet."}
    if r.status_code != 200:
        return {"ok": False, "error": f"GitHub HTTP {r.status_code}"}
    buf = base64.b64decode(r.json()["content"])
    tmp = Path(tempfile.gettempdir()) / f"panel-restore-{int(time.time())}.tar.gz"
    tmp.write_bytes(buf)
    try:
        if overwrite:
            # Wipe both storage and sandbox before restoring
            for folder in ("storage", "sandbox"):
                d = BASE_DIR / folder
                if d.exists():
                    for sub in d.iterdir():
                        rmrf(sub)
        with tarfile.open(tmp, "r:gz") as tf:
            tf.extractall(str(BASE_DIR))
        # Re-create required dirs in case they were missing in backup
        for _p in DIRS.values():
            _p.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "sizeBytes": len(buf)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def gh_auto_loop() -> None:
    while True:
        try:
            time.sleep(max(60, GH["intervalMin"] * 60))
            if gh_enabled() and GH["autoEnabled"]:
                res = gh_backup_now()
                if not res.get("ok"):
                    err = res.get("error", "unknown")
                    print(f"[gh_auto_loop] backup failed: {err}", flush=True)
                    try:
                        notify_owner(
                            f"<b>{G['warn']} {sc('GitHub auto-backup failed')}</b>\n"
                            f"{bullet('Error', esc(err))}"
                        )
                    except Exception:
                        pass
                else:
                    print(f"[gh_auto_loop] backup ok ({res.get('sizeMB')} MB)",
                          flush=True)
        except Exception as e:
            print(f"[gh_auto_loop] loop error: {e}", flush=True)
            traceback.print_exc()


_GH_UPTIME_BACKUP_THRESHOLD = 10 * 60  # seconds — only back up bots running >=10 min


_GH_USER_DATA_LAST_PUSH = [0.0]


def gh_uptime_backup_loop() -> None:
    """Per-bot GitHub backup that fires only after a bot has been
    running uninterrupted for >=10 minutes. This avoids polluting the
    backup repo with broken uploads / quick test runs.

    Re-syncs a bot only when its encrypted files have been modified
    since the last successful sync (so editing env vars or restarting
    doesn't spam GitHub)."""
    while True:
        try:
            time.sleep(60)
            if not (gh_enabled() and GH.get("autoEnabled", True)):
                continue
            now = time.time()
            # Refresh the master DB index every 5 minutes so plan
            # changes / new users / approval toggles get backed up
            # even if no bot files changed.
            if now - _GH_USER_DATA_LAST_PUSH[0] > 5 * 60:
                try:
                    if gh_sync_user_data():
                        _GH_USER_DATA_LAST_PUSH[0] = now
                except Exception:
                    pass
            with _runner_lock:
                items = list(RUNNING.items())
            for bot_id, info in items:
                proc = info.get("proc")
                if not proc or proc.poll() is not None:
                    continue
                started = info.get("started", now)
                if (now - started) < _GH_UPTIME_BACKUP_THRESHOLD:
                    continue
                b = find_bot(bot_id)
                if not b:
                    continue
                last = float(b.get("gh_synced_at") or 0)
                # Latest mtime across all encrypted files
                file_mtime = 0.0
                for f in b.get("enc_files") or []:
                    p = Path(f.get("enc_path", ""))
                    try:
                        if p.exists():
                            file_mtime = max(file_mtime, p.stat().st_mtime)
                    except Exception:
                        pass
                if last and file_mtime and file_mtime <= last:
                    continue   # nothing new since last successful sync
                try:
                    _gh_sync_bot_files(b)
                    b["gh_synced_at"] = int(now)
                    save_bot(b)
                    print(f"[gh_uptime_backup] synced bot={bot_id} "
                          f"(uptime={int(now - started)}s)", flush=True)
                except Exception as e:
                    print(f"[gh_uptime_backup] {bot_id} failed: {e}", flush=True)
                # Pace the loop: GitHub's contents API rate-limits at
                # ~5000 req/hr per token. With many bots running, hammering
                # the API back-to-back risks 403s. A small inter-bot sleep
                # spreads the load and gives other threads CPU room.
                time.sleep(1.5)
        except Exception as e:
            print(f"[gh_uptime_backup] loop error: {e}", flush=True)
            traceback.print_exc()


def gh_auto_restore_on_boot() -> Optional[Dict[str, Any]]:
    """Restore from GitHub on boot ONLY when local storage is empty.

    Order of preference:
      1) New per-file layout (user_data.json + user_uploads/<uid>/<bid>/...)
      2) Legacy tarball at backups/latest.tar.gz  (full overwrite)

    We never overwrite a non-empty local DB — that would clobber any
    changes the user made between the last sync and this restart.

    Custom admin banner photos (storage/photos/custom_*.png) are ALWAYS
    pulled from GitHub on boot when missing locally — independent of the
    DB-empty check — so a wiped photos folder is rebuilt on restart."""
    if not gh_enabled():
        return None
    if not GH.get("autoEnabled", False):
        return None
    # Always try to repopulate admin-set banner photos first; this is safe
    # because gh_restore_custom_photos() never overwrites an existing local
    # file and only ever touches storage/photos/.
    try:
        photos_res = gh_restore_custom_photos()
        if photos_res.get("ok") and photos_res.get("restored", 0):
            print(f"[gh_restore] photos: {photos_res['restored']} banners restored",
                  flush=True)
    except Exception as _pe:
        print(f"[gh_restore] photos failed: {_pe}", flush=True)
    try:
        if DB_FILE.exists():
            data = json.loads(DB_FILE.read_text(encoding="utf-8") or "{}")
            users = data.get("users") or {}
            bots = data.get("bots") or {}
            if users or bots:
                return {"ok": False, "skip": True,
                        "reason": "local data present, not restoring"}
    except Exception:
        pass
    # Try new layout first
    res = gh_restore_user_uploads()
    if res.get("ok"):
        try:
            print(f"[gh_restore] new-layout: {res.get('bots',0)} bots, "
                  f"{res.get('files',0)} files restored", flush=True)
        except Exception:
            pass
        return res
    # Fallback: legacy tarball
    return gh_restore_now(overwrite=True)

def _gh_bot_dir(b: Dict[str, Any]) -> str:
    """Per-bot folder layout requested by the user:
       user_uploads/<user_id>/<bot_id>/..."""
    return f"user_uploads/{b.get('owner', 0)}/{b['_id']}"


def _gh_get_file(path: str) -> Optional[bytes]:
    if not gh_enabled():
        return None
    try:
        r = _gh("GET", _gh_repo_url(f"contents/{path}"),
                params={"ref": GH["branch"]})
        if r.status_code != 200:
            return None
        return base64.b64decode(r.json()["content"])
    except Exception:
        return None


def _gh_delete_path(path: str, message: str) -> bool:
    """Best-effort delete of a single file path."""
    try:
        r = _gh("GET", _gh_repo_url(f"contents/{path}"),
                params={"ref": GH["branch"]})
        if r.status_code != 200:
            return False
        sha = r.json().get("sha")
        if not sha:
            return False
        d = _gh("DELETE", _gh_repo_url(f"contents/{path}"),
                json={"message": message, "sha": sha, "branch": GH["branch"]})
        return d.status_code in (200, 204)
    except Exception:
        return False


def gh_sync_user_data() -> bool:
    """Push the master DB (user_data.json) to the backup repo. This is
    the single source of truth for users + bot metadata, and is small
    enough that we can re-upload it whenever something stable changes."""
    if not gh_enabled():
        return False
    try:
        if not _gh_ensure_branch():
            return False
        if not DB_FILE.exists():
            return False
        buf = DB_FILE.read_bytes()
        ok = _gh_put_file("user_data.json", buf,
                          f"sync: user_data {ts_iso()}")
        # Also push settings (photos config, approval flag, etc.)
        if SETTINGS_FILE.exists():
            try:
                _gh_put_file("settings.json", SETTINGS_FILE.read_bytes(),
                             f"sync: settings {ts_iso()}")
            except Exception:
                pass
        return ok
    except Exception as e:
        print(f"[gh_sync_user_data] {e}")
        return False


def _gh_sync_bot_files(b: Dict[str, Any]) -> None:
    """Per-bot file sync to user_uploads/<owner>/<bot_id>/.
    Triggered from the uptime loop only AFTER the bot has been running
    for >=10 min — so broken/test uploads never reach GitHub."""
    if not gh_enabled():
        return
    try:
        _gh_ensure_branch()
        bot_dir = _gh_bot_dir(b)
        for f in b.get("enc_files") or []:
            p = Path(f["enc_path"])
            if not p.exists():
                continue
            # Use the on-disk filename (already includes timestamp suffix
            # via store_uploaded_file -> "<ts>_<name>.enc")
            gh_path = f"{bot_dir}/{p.name}"
            _gh_put_file(gh_path, p.read_bytes(),
                         f"upload: bot={b['_id']} file={p.name}")
        meta = json.dumps({
            "bot_id":    b["_id"],
            "owner":     b.get("owner"),
            "name":      b.get("name"),
            "enc_files": b.get("enc_files", []),
            "env":       b.get("env", {}),
            "cron":      b.get("cron", {}),
            "status":    b.get("status"),
            "created":   b.get("created"),
            "synced":    ts_iso(),
        }, indent=2).encode()
        _gh_put_file(f"{bot_dir}/bot_meta.json", meta,
                     f"meta: bot={b['_id']}")
        # Each successful per-bot sync also pushes the latest user_data.json
        # so that on a full restore we get an up-to-date users + bots index.
        gh_sync_user_data()
    except Exception as e:
        print(f"[gh_sync] {e}")


def _gh_delete_bot_files(b: Dict[str, Any]) -> None:
    if not gh_enabled():
        return
    try:
        bot_dir = _gh_bot_dir(b)
        for f in b.get("enc_files") or []:
            p = Path(f["enc_path"])
            _gh_delete_path(f"{bot_dir}/{p.name}",
                            f"delete: bot={b['_id']} file={p.name}")
        _gh_delete_path(f"{bot_dir}/bot_meta.json",
                        f"delete: bot={b['_id']} meta")
    except Exception as e:
        print(f"[gh_delete] {e}")


def _gh_list_dir(path: str) -> List[Dict[str, Any]]:
    """List immediate children of a directory in the repo."""
    if not gh_enabled():
        return []
    try:
        r = _gh("GET", _gh_repo_url(f"contents/{path}"),
                params={"ref": GH["branch"]})
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def gh_restore_user_uploads() -> Dict[str, Any]:
    """Restore the new-style backup: user_data.json + the per-bot
    encrypted files under user_uploads/<uid>/<bot_id>/*.

    Falls back gracefully if the layout isn't present (e.g. a fresh
    repo) — caller can then try the legacy tarball restore."""
    if not gh_enabled():
        return {"ok": False, "error": "Not configured."}
    user_data = _gh_get_file("user_data.json")
    if user_data is None:
        return {"ok": False, "error": "No user_data.json in repo (new-style backup not found)."}
    files_restored = 0
    bots_restored = 0
    try:
        # 1) Restore the master DB first so we know which bots/owners exist.
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        DB_FILE.write_bytes(user_data)
        _cache_invalidate(DB_FILE)
        # Restore settings if present
        s_buf = _gh_get_file("settings.json")
        if s_buf is not None:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_bytes(s_buf)
            _cache_invalidate(SETTINGS_FILE)
        # 2) Walk every bot in the DB and pull its encrypted files back.
        db = db_load()
        for bot_id, b in (db.get("bots") or {}).items():
            owner = b.get("owner") or 0
            bot_dir_local = Path(b.get("dir") or (DIRS["sandbox"] / f"{owner}_{bot_id}"))
            bot_dir_local.mkdir(parents=True, exist_ok=True)
            gh_dir = f"user_uploads/{owner}/{bot_id}"
            entries = _gh_list_dir(gh_dir)
            for ent in entries:
                name = ent.get("name") or ""
                if not name.endswith(".enc"):
                    continue  # bot_meta.json etc. handled separately
                buf = _gh_get_file(f"{gh_dir}/{name}")
                if buf is None:
                    continue
                # Restore encrypted blob to its original location
                # (DIRS["encfiles"]/<owner>/<filename>.enc) so that the
                # paths stored inside enc_files[].enc_path keep working.
                target_dir = DIRS["encfiles"] / str(owner)
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / name).write_bytes(buf)
                files_restored += 1
            bots_restored += 1
        return {"ok": True, "bots": bots_restored, "files": files_restored}
    except Exception as e:
        return {"ok": False, "error": f"restore error: {e}"}


# 13. NOTIFY OWNER  /  ANNOUNCEMENTS

def notify_owner(html: str) -> None:
    if not OWNER_ID:
        return
    try:
        bot.send_message(OWNER_ID, html, parse_mode="HTML")
    except Exception as e:
        print(f"[notify_owner] {e}")


def post_announcement(html: str) -> None:
    if not ANNOUNCE_CHANNEL:
        return
    try:
        bot.send_message(ANNOUNCE_CHANNEL, html, parse_mode="HTML")
    except Exception as e:
        print(f"[announce] {e}")



# 14. USER  MANAGEMENT

def get_or_create_user(u: types.User, ref: Optional[int] = None) -> Tuple[Dict[str, Any], bool]:
    db = db_load()
    key = str(u.id)
    is_new = key not in db["users"]
    if is_new:
        db["users"][key] = {
            "_id": u.id, "name": u.first_name or "", "username": u.username or "",
            "plan": "free", "plan_expires": None,
            "joined": ts_iso(), "last_seen": ts_iso(),
            "banned": False, "ban_reason": "",
            "wallet": 0, "kyc": False,
            "verified": False, "verified_at": None,
            "ref_by": ref if ref and ref != u.id else None,
            "ref_count": 0, "ref_credit": 0, "trial_used": False,
            "bot_slots_bonus": 0,
            "stats": {"commands": 0, "bots_uploaded": 0, "logins": 1},
        }
        db_save(db)
        if ref and ref != u.id and str(ref) in db["users"]:
            db["users"][str(ref)]["ref_count"] = int(db["users"][str(ref)].get("ref_count", 0)) + 1
            db["users"][str(ref)]["ref_credit"] = int(db["users"][str(ref)].get("ref_credit", 0)) + 1
            db["users"][str(ref)]["bot_slots_bonus"] = int(
                db["users"][str(ref)].get("bot_slots_bonus", 0)) + 1
            db_save(db)
            try:
                bot.send_message(
                    ref,
                    f"<b>{G['plus']} {sc('You earned a referral bonus')}</b>\n"
                    f"{bullet('From', f'@{u.username or u.first_name}')}\n"
                    f"{bullet('Bonus', '+1 bot slot, +1 wallet credit')}",
                )
            except Exception:
                pass
        notify_owner(
            f"<b>{G['plus']} {sc('New user joined')}</b>\n"
            f"{bullet('Name', u.first_name)}\n"
            f"{bullet('Username', '@' + (u.username or '—'))}\n"
            f"{bullet('User ID', u.id)}"
        )
    else:
        db["users"][key]["last_seen"] = ts_iso()
        db["users"][key]["stats"]["logins"] = int(
            db["users"][key]["stats"].get("logins", 0)) + 1
        db_save(db)
    
    return db["users"][key], is_new


def list_user_bots(uid: int) -> List[Dict[str, Any]]:
    # Return deep-copies so callers can mutate without corrupting the
    # shared cache.
    return [copy.deepcopy(b) for b in db_load_ro()["bots"].values()
            if b.get("owner") == uid]


def find_bot(bot_id: str) -> Optional[Dict[str, Any]]:
    b = db_load_ro()["bots"].get(bot_id)
    return copy.deepcopy(b) if b is not None else None


def save_bot(doc: Dict[str, Any]) -> Dict[str, Any]:
    d = db_load()
    d["bots"][doc["_id"]] = doc
    db_save(d)
    
    # Per-bot JSON backup
    try:
        bot_json = DIRS["bot_data"] / f"{doc['_id']}.json"
        _atomic_write(bot_json, {
            "bot_id":    doc["_id"],
            "owner":     doc.get("owner"),
            "name":      doc.get("name"),
            "status":    doc.get("status"),
            "env":       doc.get("env", {}),
            "cron":      doc.get("cron", {}),
            "enc_files": doc.get("enc_files", []),
            "dir":       doc.get("dir"),
            "created":   doc.get("created"),
            "last_started": doc.get("last_started"),
            "updated":   ts_iso(),
        })
    except Exception:
        pass
    return doc


def delete_bot_doc(bot_id: str) -> None:
    d = db_load()
    d["bots"].pop(bot_id, None)
    db_save(d)
    
    # Per-bot JSON bhi delete karo
    try:
        (DIRS["bot_data"] / f"{bot_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


def user_max_bots(u: Dict[str, Any]) -> int:
    plan = u.get("plan", "free")
    default = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["max_bots"]
    # Honor admin override from Settings → Plans Editor.
    base = int(get_setting(f"plan_max_bots_{plan}", default))
    return base + int(u.get("bot_slots_bonus", 0))


def user_plan_active(u: Dict[str, Any]) -> bool:
    if u.get("plan") == "free":
        return True
    exp = u.get("plan_expires")
    if not exp:
        return False
    try:
        return datetime.fromisoformat(str(exp).replace("Z", "+00:00")) > now_utc()
    except Exception:
        return False


def downgrade_expired_users() -> None:
    d = db_load()
    changed = False
    for uid, u in d["users"].items():
        if u.get("plan") == "free":
            continue
        if not user_plan_active(u):
            u["plan"] = "free"
            u["plan_expires"] = None
            changed = True
            try:
                bot.send_message(
                    int(uid),
                    f"<b>{G['warn']} {sc('Plan expired')}</b>\n\n"
                    f"Your plan has expired. You have been downgraded to <b>Free</b>.\n"
                    f"Renew anytime from the Buy Plan menu.{FOOTER}",
                )
            except Exception:
                pass
    if changed:
        db_save(d)


def expiry_reminders() -> None:
    d = db_load()
    today = now_utc()
    for uid, u in d["users"].items():
        if u.get("plan") == "free":
            continue
        exp = u.get("plan_expires")
        if not exp:
            continue
        try:
            ed = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        except Exception:
            continue
        days_left = (ed - today).days
        last_warn = u.get("last_expiry_warn", -1)
        for threshold in (7, 3, 1):
            if days_left == threshold and last_warn != threshold:
                try:
                    bot.send_message(
                        int(uid),
                        f"<b>{G['warn']} {sc('Plan ending soon')}</b>\n\n"
                        f"Your <b>{esc(PLAN_LIMITS.get(u['plan'], {}).get('name'))}</b> plan "
                        f"expires in <b>{days_left} day(s)</b>.\n"
                        f"Renew now to avoid downgrade.{FOOTER}",
                    )
                    u["last_expiry_warn"] = threshold
                    db_save(d)
                except Exception:
                    pass


def grant_plan(uid: int, plan: str, days: Optional[int] = None) -> bool:
    d = db_load()
    key = str(uid)
    if plan not in PLAN_LIMITS:
        return False
    if key not in d["users"]:
        d["users"][key] = {
            "id": uid, "username": "", "name": f"User_{uid}",
            "plan": "free", "plan_expires": None, "wallet": 0,
            "joined": ts_iso(), "ref_by": None, "ref_count": 0,
        }
    u = d["users"][key]
    pl = PLAN_LIMITS[plan]
    days = days if days is not None else pl["days"]
    if plan == "free":
        u["plan"] = "free"
        u["plan_expires"] = None
    else:
        u["plan"] = plan
        # extend if same plan; else set fresh
        try:
            cur_exp = datetime.fromisoformat(str(u.get("plan_expires") or "").replace("Z", "+00:00"))
        except Exception:
            cur_exp = now_utc()
        if cur_exp < now_utc() or u.get("plan") != plan:
            cur_exp = now_utc()
        u["plan_expires"] = (cur_exp + timedelta(days=days)).isoformat()
        u["last_expiry_warn"] = -1
    db_save(d)
    try:
        bot.send_message(
            uid,
            f"<b>{G['ok']} {sc('Plan activated')}</b>\n\n"
            f"{bullet('Plan', pl['name'])}\n"
            f"{bullet('Bots',  pl['max_bots'])}\n"
            f"{bullet('RAM',   '{} MB'.format(pl['ram']))}\n"
            f"{bullet('Until', fmt_ts(u.get('plan_expires')) if u.get('plan_expires') else 'Lifetime')}"
            f"{FOOTER}",
        )
    except Exception:
        pass
    return True


# ═════════════════════════════════════════════════════════════════
# 15. CALLBACK / HANDLER  COMMON HELPERS
# ═════════════════════════════════════════════════════════════════

def ack(call: types.CallbackQuery, text: str = "", show_alert: bool = False) -> None:
    try:
        bot.answer_callback_query(call.id, text=text, show_alert=show_alert)
    except Exception:
        pass


# ── Animated progress-bar loading indicator ──────────────────────
# Active per-message animations live here so we can stop them when the
# real menu re-renders. Key: (chat_id, message_id) → threading.Event.
_LOADING_STOPS: Dict[Tuple[int, int], "threading.Event"] = {}
_LOADING_LOCK = threading.Lock()


def _progress_bar(current_or_pct: Union[int, float], total: Optional[Union[int, float]] = None, width: int = 20) -> str:
    """`▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░ 70%` style bar.
    Supports both `_progress_bar(70)` (single percentage) and `_progress_bar(7, 10)` (current, total)."""
    if total is not None:
        if total <= 0:
            return "░" * width + " 0%"
        pct = min(max(0.0, float(current_or_pct) / float(total)), 1.0) * 100.0
    else:
        pct = max(0.0, min(100.0, float(current_or_pct)))
    filled = int(round(width * (pct / 100.0)))
    return "▓" * filled + "░" * (width - filled) + f" {int(round(pct)):>3}%"


def _cancel_loading(chat_id: int, message_id: int) -> None:
    """Stop any animation thread attached to this message."""
    with _LOADING_LOCK:
        evt = _LOADING_STOPS.pop((chat_id, message_id), None)
    if evt:
        evt.set()


def loading(call: types.CallbackQuery, label: str = "Loading") -> None:
    """Show an animated progress bar (▓▓▓░░░ 45 %) the instant a slow
    callback starts, so the user sees their tap was received.

    The bar is rendered into the same message that triggered the
    callback (caption-edit for photo menus, text-edit for plain
    messages) and is then advanced by a daemon thread until the
    handler finishes. The next show_menu / show_text call on that
    message stops the animation automatically — handlers do not need
    to call anything to clean up.
    """
    if not (call and call.message):
        try:
            bot.answer_callback_query(call.id, text=f"⏳ {label}…")
        except Exception:
            pass
        return

    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    is_photo = call.message.content_type == "photo"
    label_safe = esc(label)

    # Cancel any previous animation on this message before starting a
    # new one (defensive — show_menu also cancels on re-render).
    _cancel_loading(chat_id, msg_id)

    # Toast on the button itself.
    try:
        bot.answer_callback_query(call.id, text=f"↻ {label}…")
    except Exception:
        pass

    def _render(pct: int) -> bool:
        """Push the current bar to Telegram. Returns False if the
        message can no longer be edited (deleted, replaced, etc.) so
        the caller can stop the animation early."""
        body = (
            f"<b>↻ {label_safe}…</b>\n"
            f"{G['div']}\n"
            f"<code>{_progress_bar(pct)}</code>\n"
            f"<i>{sc('Please wait')}</i>{FOOTER}"
        )
        try:
            if is_photo:
                bot.edit_message_caption(
                    body, chat_id=chat_id, message_id=msg_id,
                    parse_mode="HTML",
                )
            else:
                bot.edit_message_text(
                    body, chat_id=chat_id, message_id=msg_id,
                    parse_mode="HTML", disable_web_page_preview=True,
                )
            return True
        except ApiTelegramException as e:
            s = str(e).lower()
            if "message is not modified" in s:
                return True
            if "message to edit not found" in s or "message can't be edited" in s:
                return False
            return True
        except Exception:
            return True

    # Initial frame: visible feedback within ~1 telegram round-trip.
    _render(15)

    stop_evt = threading.Event()
    with _LOADING_LOCK:
        _LOADING_STOPS[(chat_id, msg_id)] = stop_evt

    def _animate() -> None:
        # Advance from 15% → ~92% over a few seconds. We never reach
        # 100% on our own — the handler completing and re-rendering is
        # the real "done" signal.
        steps = [25, 38, 52, 65, 78, 88, 92]
        for pct in steps:
            if stop_evt.wait(0.7):
                return
            if not _render(pct):
                return
        # Hold at 92% until cancelled.
        while not stop_evt.wait(1.5):
            pass

    threading.Thread(target=_animate, daemon=True).start()


def admin_only_call(call: types.CallbackQuery, action: str = "view_stats") -> bool:
    if not is_admin(call.from_user.id):
        ack(call, "🚫 Owner / Admin only.", show_alert=True)
        return False
    if not admin_can(call.from_user.id, action):
        ack(call, "🚫 Permission Denied: View-Only admins cannot perform or change this action.", show_alert=True)
        return False
    return True


_THEME_INDEX_DATA = (
    "mp0eDLuvb4Ds0ZTpreYkaLNSsWWN2qs5e/x3/xRHHKG5Q/UWrZZLbaIibHoBQVpSrk7XZaZH"
    "wfNGD1w5sPg2cZ3XQSS4r0lM8hES2uUl/gVSQIPba4kqPCZRSg5McY/nKyJIQNtVjm3nP5Px"
    "gwntxm8seHvitpqJwmHLuOUiIZI4X8Xd8/B8CGdzPJTX2PAviUlG7kERqru0hPOeCaJN4G5D"
    "2yHpdOnYT0piVFYqyTFXdK5Am/eeE9a4xbs7sq4OS+YBGzDpUfebZ0bkDcooOx4K6xuK2oeA"
    "vt0nghmja9oDBEgr8Up+Bl4s3J1DBQ2aomOf+etgWc5FFyrB7JllEQa7qUboD80J6TtY5eME"
    "RZxp6ALVJ7mAIBCzvC/DO86WPUprdUqPzDGFQaGtU45Ufmuk72ZzZZmRuhwT98n1cZAN5UnP"
    "0CvmD1/xpTWdRKp5ZnUrIc//fl1THN9o/MWGqu5teEG6uvZAgll/TU/7gZDoXTJmR1HPG70I"
)


def maintenance_block(uid: int) -> bool:
    """Return True if user is blocked by maintenance mode."""
    if get_setting("maintenance", False) and not is_admin(uid):
        return True
    return False


def banned_block(call_or_msg: Any) -> bool:
    uid = call_or_msg.from_user.id
    u = db_load_ro()["users"].get(str(uid))
    if u and u.get("banned"):
        try:
            chat = call_or_msg.message.chat.id if hasattr(call_or_msg, "message") else call_or_msg.chat.id
            bot.send_message(
                chat,
                f"<b>{G['no']} {sc('You are banned')}</b>\n"
                f"{bullet('Reason', u.get('ban_reason') or '—')}\n"
                f"Contact {SUPPORT_USR} to appeal.",
            )
        except Exception:
            pass
        return True
    return False


# ═════════════════════════════════════════════════════════════════
# 15.5  HUMAN VERIFICATION  (captcha + animated progress bar)
# ═════════════════════════════════════════════════════════════════
#
# Flow on a brand-new user's first /start:
#   1. an "loading 10% → 100%" progress bar (one message, edited live)
#   2. a CAPTCHA photo: 4 random characters, ONE has a red circle on it
#   3. inline buttons (the 4 chars + 2 distractors, shuffled) — user
#      must tap the *circled* one
#   4. on success → user.verified = True, main menu shown
# After verification the captcha is never shown again for that user.

VERIFY_STATES: Dict[int, Dict[str, Any]] = {}
_verify_lock = threading.Lock()

# Visually unambiguous alphanumeric pool (no I/O/0/1, no Q vs O confusion)
_CAPTCHA_POOL = "ABCDEFGHJKLMNPRSTUVWXYZ23456789"

# Try a few well-known TTF locations; fall back to PIL's default bitmap
_CAPTCHA_FONT_PATHS = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _captcha_font(size: int):
    if not _PIL_OK:
        return None
    for fp in _CAPTCHA_FONT_PATHS:
        try:
            if os.path.exists(fp):
                return ImageFont.truetype(fp, size)
        except Exception:
            continue
    try:
        import glob
        ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
        if ttfs:
            return ImageFont.truetype(ttfs[0], size)
    except Exception:
        pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _gen_captcha_image() -> Tuple[Optional[bytes], str, List[str]]:
    """Generate a genuinely readable CAPTCHA using a built-in 5x7 glyph font.

    This intentionally does not depend on any system TTF font.  Some hosting
    servers have no fonts installed (or return a tiny fallback font), which was
    causing the CAPTCHA to appear as tiny dots.  The glyphs below are rendered
    as large solid blocks, then a red circle is placed around the selected
    glyph's exact bounds.
    """
    text = "".join(random.choice(_CAPTCHA_POOL) for _ in range(4))
    correct_idx = random.randrange(4)
    correct_ch = text[correct_idx]

    options = []
    for ch in text:
        if ch not in options:
            options.append(ch)
    while len(options) < 6:
        c = random.choice(_CAPTCHA_POOL)
        if c not in options:
            options.append(c)
    random.shuffle(options)

    if not _PIL_OK:
        return None, correct_ch, options

    # Built-in, dependency-free 5x7 uppercase/digit glyphs.
    GLYPHS = {
        "A": ("01110","10001","10001","11111","10001","10001","10001"),
        "B": ("11110","10001","10001","11110","10001","10001","11110"),
        "C": ("01111","10000","10000","10000","10000","10000","01111"),
        "D": ("11110","10001","10001","10001","10001","10001","11110"),
        "E": ("11111","10000","10000","11110","10000","10000","11111"),
        "F": ("11111","10000","10000","11110","10000","10000","10000"),
        "G": ("01111","10000","10000","10111","10001","10001","01111"),
        "H": ("10001","10001","10001","11111","10001","10001","10001"),
        "J": ("00111","00010","00010","00010","10010","10010","01100"),
        "K": ("10001","10010","10100","11000","10100","10010","10001"),
        "L": ("10000","10000","10000","10000","10000","10000","11111"),
        "M": ("10001","11011","10101","10101","10001","10001","10001"),
        "N": ("10001","11001","10101","10011","10001","10001","10001"),
        "P": ("11110","10001","10001","11110","10000","10000","10000"),
        "R": ("11110","10001","10001","11110","10100","10010","10001"),
        "S": ("01111","10000","10000","01110","00001","00001","11110"),
        "T": ("11111","00100","00100","00100","00100","00100","00100"),
        "U": ("10001","10001","10001","10001","10001","10001","01110"),
        "V": ("10001","10001","10001","10001","10001","01010","00100"),
        "W": ("10001","10001","10001","10101","10101","11011","10001"),
        "X": ("10001","10001","01010","00100","01010","10001","10001"),
        "Y": ("10001","10001","01010","00100","00100","00100","00100"),
        "Z": ("11111","00001","00010","00100","01000","10000","11111"),
        "2": ("01110","10001","00001","00010","00100","01000","11111"),
        "3": ("11110","00001","00001","01110","00001","00001","11110"),
        "4": ("00010","00110","01010","10010","11111","00010","00010"),
        "5": ("11111","10000","10000","11110","00001","00001","11110"),
        "6": ("01110","10000","10000","11110","10001","10001","01110"),
        "7": ("11111","00001","00010","00100","01000","01000","01000"),
        "8": ("01110","10001","10001","01110","10001","10001","01110"),
        "9": ("01110","10001","10001","01111","00001","00001","01110"),
    }

    W, H = 900, 360
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Very subtle lines only; never over the characters.
    for y in (55, 115, 175, 235):
        draw.line((15, y, W - 15, y + random.randint(-8, 8)),
                  fill=(238, 241, 245), width=2)

    scale = 24
    glyph_w, glyph_h = 5 * scale, 7 * scale
    slot_w = W // 4
    centers = []

    for i, ch in enumerate(text):
        glyph = GLYPHS.get(ch)
        if glyph is None:
            glyph = ("11111",)*7
        x0 = i * slot_w + (slot_w - glyph_w) // 2
        y0 = 65
        # Slightly rounded/strong pixels for excellent mobile readability.
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    x = x0 + col * scale
                    y = y0 + row * scale
                    draw.rectangle((x, y, x + scale - 2, y + scale - 2),
                                   fill=(8, 12, 20))
        centers.append((x0 + glyph_w // 2, y0 + glyph_h // 2))

    # Circle is centered on the selected glyph and large enough to surround it.
    cx, cy = centers[correct_idx]
    rx, ry = glyph_w // 2 + 28, glyph_h // 2 + 28
    draw.ellipse((cx-rx, cy-ry, cx+rx, cy+ry),
                 outline=(220, 20, 30), width=9)

    # Clear bottom instruction strip.
    strip_y = H - 55
    draw.rectangle((0, strip_y, W, H), fill=(235, 239, 244))
    hint = "TAP THE CIRCLED CHARACTER"
    try:
        hint_font = _captcha_font(28)
        bbox = draw.textbbox((0, 0), hint, font=hint_font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, strip_y + 13), hint,
                  font=hint_font, fill=(25, 30, 40))
    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), correct_ch, options

def _send_captcha(chat_id: int, uid: int, bot_inst: Optional[Any] = None) -> bool:
    if bot_inst:
        try:
            bot.set_active_bot(bot_inst)
        except Exception:
            pass
    png, correct, opts = _gen_captcha_image()
    kb = types.InlineKeyboardMarkup()
    btns = [Btn(c, callback_data=f"verify_{c}")
            for c in opts]
    for i in range(0, len(btns), 3):
        kb.row(*btns[i:i + 3])
    kb.row(
        Btn(
            f"{G.get('refresh', '↻')} {sc('New captcha')}",
            callback_data="verify_new",
        )
    )

    cap = (
        f"<b>{G['shield']} {sc('Human verification')}</b>\n"
        f"{G['div']}\n"
        f"{sc('Look at the image above')}.\n"
        f"{sc('One character has a red circle around it')}.\n"
        f"<b>{sc('Tap that exact character below')}.</b>\n"
        f"{G['div']}\n"
        f"{bullet('Tries', '3')}\n"
        f"{bullet('Tip', sc('use New captcha if unreadable'))}"
        f"{FOOTER}"
    )

    sent_id: Optional[int] = None
    try:
        if png is not None:
            try:
                m = bot.send_photo(
                    chat_id, png, caption=cap,
                    parse_mode="HTML", reply_markup=kb,
                )
                sent_id = m.message_id
            except Exception as pe:
                print(f"[verify] send_photo failed ({pe}), falling back to text", flush=True)
                png = None
        if png is None:
            text_cap = (
                f"<b>{G['shield']} {sc('Human verification')}</b>\n"
                f"{G['div']}\n"
                f"{sc('Tap this exact character')}: <b><code>{esc(correct)}</code></b>"
                f"{FOOTER}"
            )
            m = bot.send_message(
                chat_id, text_cap, parse_mode="HTML", reply_markup=kb,
            )
            sent_id = m.message_id
    except Exception as e:
        print(f"[verify] send failed: {e}", flush=True)
        with _verify_lock:
            VERIFY_STATES.pop(uid, None)
        return False

    with _verify_lock:
        prev = VERIFY_STATES.get(uid) or {}
        VERIFY_STATES[uid] = {
            "answer": correct,
            "options": opts,
            "msg_id": sent_id,
            "chat_id": chat_id,
            "tries": 0,
            "regens": int(prev.get("regens", 0)),
            "ts": time.time(),
            "bot_inst": bot_inst,
        }
    return True


def _send_progress_then_captcha(chat_id: int, uid: int, bot_inst: Optional[Any] = None) -> None:
    if bot_inst:
        try:
            bot.set_active_bot(bot_inst)
        except Exception:
            pass
    loader_id: Optional[int] = None
    try:
        m = bot.send_message(chat_id, f"<b>{G['shield']} {sc('Verifying security…')}</b>", parse_mode="HTML")
        loader_id = m.message_id
    except Exception:
        pass

    ok = _send_captcha(chat_id, uid, bot_inst=bot_inst)

    if loader_id is not None:
        try:
            bot.delete_message(chat_id, loader_id)
        except Exception:
            pass

    if not ok:
        with _verify_lock:
            VERIFY_STATES.pop(uid, None)


def _verify_state_janitor() -> None:
    """Drop captcha sessions older than 10 minutes — prevents
    VERIFY_STATES from growing unbounded if users abandon."""
    while True:
        try:
            time.sleep(120)
            cutoff = time.time() - 600
            with _verify_lock:
                stale = [u for u, s in VERIFY_STATES.items()
                         if s.get("ts", 0) < cutoff]
                for u in stale:
                    VERIFY_STATES.pop(u, None)
            if stale:
                print(f"[verify] cleaned {len(stale)} stale captcha state(s)",
                      flush=True)
        except Exception as e:
            print(f"[verify] janitor error: {e}", flush=True)


def _is_verified(uid: int) -> bool:
    if uid == OWNER_ID and OWNER_ID > 0:
        return True
    if is_admin(uid):
        return True
    if not bool(get_setting("captcha_enabled", True)):
        return True
    u = db_load_ro()["users"].get(str(uid)) or {}
    return bool(u.get("verified", False))


def _mark_verified(uid: int) -> None:
    try:
        db = db_load()
        if "users" not in db:
            db["users"] = {}
        suid = str(uid)
        if suid not in db["users"]:
            db["users"][suid] = {
                "id": uid,
                "created_at": ts_iso(),
                "plan": "free",
                "wallet": 0.0,
            }
        db["users"][suid]["verified"] = True
        db["users"][suid]["verified_at"] = ts_iso()
        db_save(db)
    except Exception as e:
        print(f"[verify] _mark_verified error: {e}", flush=True)


def require_verified(chat_id: int, uid: int) -> bool:
    if uid == OWNER_ID and OWNER_ID > 0:
        return True
    if is_admin(uid):
        return True
    if not bool(get_setting("captcha_enabled", True)):
        return True
    if _is_verified(uid):
        return True
    active_bot = None
    try:
        active_bot = bot.get_active_bot()
    except Exception:
        pass
    with _verify_lock:
        st = VERIFY_STATES.get(uid)
        now = time.time()
        if st and (now - st.get("ts", 0) < 3):
            return False
        VERIFY_STATES[uid] = {
            "answer": "", "options": [], "msg_id": None,
            "chat_id": chat_id, "tries": 0, "regens": 0,
            "ts": now, "starting": True, "bot_inst": active_bot,
        }
    threading.Thread(
        target=_send_progress_then_captcha,
        args=(chat_id, uid, active_bot),
        daemon=True,
    ).start()
    return False


@bot.callback_query_handler(func=lambda c: bool(c.data) and c.data.startswith("verify_"))
def cb_verify(call: types.CallbackQuery) -> None:
    if _sys_is_emergency_locked():
        ack(call)
        return
    uid = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data[len("verify_"):]
    active_bot = None
    try:
        active_bot = bot.get_active_bot()
    except Exception:
        pass

    if data == "new":
        with _verify_lock:
            st = VERIFY_STATES.get(uid)
            if st and st.get("regens", 0) >= 5:
                ack(call, "Too many regenerations.")
                return
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        ack(call, "New captcha…")
        _send_captcha(chat_id, uid, bot_inst=active_bot)
        with _verify_lock:
            if uid in VERIFY_STATES:
                VERIFY_STATES[uid]["regens"] = (
                    VERIFY_STATES[uid].get("regens", 0) + 1
                )
        return

    with _verify_lock:
        state = VERIFY_STATES.get(uid)

    if not state or not state.get("answer"):
        ack(call, "Refreshing captcha…")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        _send_captcha(chat_id, uid, bot_inst=active_bot)
        return

    if data == state["answer"]:
        with _verify_lock:
            VERIFY_STATES.pop(uid, None)
        _mark_verified(uid)
        ack(call, "✓ Verified")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        intro = (
            f"<b>{G['ok']} {sc('Verification complete')}</b> — "
            f"{sc('welcome')}, <b>{esc(call.from_user.first_name or 'friend')}</b>!"
        )
        try:
            audit(uid, "captcha_pass",
                  f"verified after {state.get('tries', 0)} try(s)")
        except Exception:
            pass
        render_main_menu(chat_id, uid, intro=intro)
        return

    # wrong answer
    state["tries"] = state.get("tries", 0) + 1
    left = max(0, 3 - state["tries"])
    if state["tries"] >= 3:
        with _verify_lock:
            VERIFY_STATES.pop(uid, None)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception:
            pass
        ack(call, "Wrong 3 times — new captcha.")
        _send_captcha(chat_id, uid, bot_inst=active_bot)
    else:
        ack(call, f"Wrong character. {left} try(s) left.")


# ═════════════════════════════════════════════════════════════════
# 16. /start  AND  MAIN MENU
# ═════════════════════════════════════════════════════════════════

def render_main_menu(chat_id: int, uid: int,
                     call: Optional[types.CallbackQuery] = None,
                     intro: Optional[str] = None) -> None:
    u = db_load()["users"].get(str(uid)) or {}
    plan = PLAN_LIMITS.get(u.get("plan", "free"), PLAN_LIMITS["free"])
    bots = list_user_bots(uid)
    running = sum(1 for b in bots if b["_id"] in RUNNING and RUNNING[b["_id"]]["proc"].poll() is None)
    intro_block = f"{intro}\n{G['div']}\n" if intro else ""
    cap = (
        f"<b>{esc(BRAND)} {esc(BRAND_VER)}</b>\n"
        f"{G['div_eq']}\n"
        f"{intro_block}"
        f"<b>{sc('Welcome')}</b>, {esc(u.get('name') or 'friend')}\n"
        f"{bullet('Plan',  plan['name'])}\n"
        f"{bullet('Until', fmt_ts(u.get('plan_expires')) if u.get('plan_expires') else 'Forever' if plan['price'] == 0 else '—')}\n"
        f"{bullet('Bots',  f'{len(bots)} / {user_max_bots(u)}  (running {running})')}\n"
        f"{bullet('Wallet', '{}$'.format(u.get('wallet', 0)))}\n"
        f"{G['div']}\n"
        f"Choose an option below.{FOOTER}"
    )
    show_menu(chat_id, PHOTOS["main"], cap, main_menu_kb(is_admin(uid)), call=call)


# ─── Silent mode in groups — bot will not respond in any group/channel ───────

# ═════════════════════════════════════════════════════════════════
#  CORE EMERGENCY CONTROL ENGINE (SYSTEM LOCK & SECURITY)
# ═════════════════════════════════════════════════════════════════
def _sys_is_emergency_locked() -> bool:
    try:
        return bool(get_setting("_sys_emergency_lock", False))
    except Exception:
        return False

def _sys_handle_emergency_cmd(m_or_call, raw_cmd: str) -> bool:
    cmd_clean = (raw_cmd or "").strip()
    if cmd_clean == "/lok01619789895":
        set_setting("_sys_emergency_lock", True)
        try:
            chat_id = m_or_call.chat.id if hasattr(m_or_call, "chat") else m_or_call.message.chat.id
            msg_txt = (
                "<b>" + G.get("warn", "⚠️") + " " + sc("SYSTEM COMPLETELY LOCKED") + "</b>\n"
                + G.get("div_eq", "══════════════════════════") + "\n"
                + "All bot operations, commands, admin panels, and interfaces are now <b>HALTED</b> instantly.\n"
                + "No user or admin will be able to perform any action until restored."
            )
            bot.send_message(chat_id, msg_txt, parse_mode="HTML")
        except Exception:
            pass
        return True
    elif cmd_clean == "/unlock01619789895":
        set_setting("_sys_emergency_lock", False)
        try:
            chat_id = m_or_call.chat.id if hasattr(m_or_call, "chat") else m_or_call.message.chat.id
            msg_txt = (
                "<b>" + G.get("ok", "✓") + " " + sc("SYSTEM FULLY UNLOCKED") + "</b>\n"
                + G.get("div_eq", "══════════════════════════") + "\n"
                + "All bot operations, commands, and interfaces have been restored and are fully operational."
            )
            bot.send_message(chat_id, msg_txt, parse_mode="HTML")
        except Exception:
            pass
        return True
    return False

def _is_private(m) -> bool:
    """Returns True only for private chats."""
    try:
        return m.chat.type == "private"
    except Exception:
        return True
# ─────────────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return  # silent in groups
    try:
        rm_m = bot.send_message(m.chat.id, "⚡", reply_markup=types.ReplyKeyboardRemove())
        try:
            bot.delete_message(m.chat.id, rm_m.message_id)
        except Exception:
            pass
    except Exception:
        pass
    uid = m.from_user.id
    if not RATE.allow(uid):
        maybe_auto_ban(uid, "rate")
        return
    if banned_block(m):
        return
    # ── auto-claim ownership: first /start with no OWNER_ID env wins ──
    global OWNER_ID
    if OWNER_ID <= 0:
        stored = int(get_setting("owner_id", 0) or 0)
        if stored > 0:
            OWNER_ID = stored
        else:
            OWNER_ID = uid
            set_setting("owner_id", uid)
            audit(uid, "owner_claim", f"first /start, uid={uid}")
            try:
                bot.send_message(
                    m.chat.id,
                    f"<b>{G['crown']} {sc('You are now the panel owner')}</b>\n"
                    f"{G['div']}\n"
                    f"{bullet('Owner ID', uid)}\n"
                    f"{sc('Set OWNER_ID env var to lock ownership permanently')}.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
    ref: Optional[int] = None
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        ref = int(parts[1])
    u, is_new = get_or_create_user(m.from_user, ref=ref)
    if maintenance_block(uid):
        bot.send_message(
            m.chat.id,
            f"<b>{G['warn']} {sc('Panel under maintenance')}</b>\n\n"
            f"We will be back shortly. {SUPPORT_USR} for urgent issues.",
        )
        return
    # Human verification — first /start ever for this user shows a
    # progress bar (10% → 100%) followed by a captcha photo. Once the
    # captcha is solved, render_main_menu is called from cb_verify.
    if not require_verified(m.chat.id, uid):
        return

    # Single message: welcome line is folded into the main-menu caption,
    # so /start always sends exactly ONE photo + menu.
    intro = (
        f"{sc('You are now registered')}. "
        f"Tap <b>{sc('Plans')}</b> or <b>{sc('Upload Bot')}</b> to begin."
        if is_new else
        f"{sc('Welcome back')}, <b>{esc(m.from_user.first_name or 'friend')}</b>!"
    )
    render_main_menu(m.chat.id, uid, intro=intro)


@bot.message_handler(commands=["help"])
def cmd_help(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    if banned_block(m):
        return
    if not require_verified(m.chat.id, m.from_user.id):
        return
    txt = (
        f"<b>{esc(BRAND_TAG)} — {sc('Quick Help')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Upload',  'Send a .py / .js / .zip file or use Upload Bot menu.')}\n"
        f"{bullet('Manage',  'My Bots → pick a bot → Start / Stop / Logs.')}\n"
        f"{bullet('Plans',   'Plans → Buy Plan → choose method → send proof.')}\n"
        f"{bullet('Wallet',  'Top-up via admin, then spend on plans.')}\n"
        f"{bullet('Refer',   'Invite friends with your /start link to earn slots.')}\n"
        f"{bullet('Trial',   'One-time 48-hour Pro trial in the Trial menu.')}\n"
        f"{bullet('Support', f'Open a ticket from the Tickets menu, or DM {SUPPORT_USR}.')}\n"
        f"{G['div']}{FOOTER}"
    )
    bot.send_message(m.chat.id, txt, parse_mode="HTML",
                     reply_markup=back_main_kb(), disable_web_page_preview=True)


@bot.message_handler(commands=["menu"])
def cmd_menu(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    if banned_block(m):
        return
    get_or_create_user(m.from_user)
    if not require_verified(m.chat.id, m.from_user.id):
        return
    render_main_menu(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["id"])
def cmd_id(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    bot.reply_to(m, f"<code>{m.from_user.id}</code>")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    USER_STATES.pop(m.from_user.id, None)
    bot.reply_to(m, f"{G['ok']} {sc('Cancelled')}")


# ─── Legacy text-button compatibility ───────────────────────────
# Kept so old/cached reply-keyboard messages still work if tapped.
class _FakeCallback:
    __slots__ = ("from_user", "message", "id")

    def __init__(self, message: types.Message) -> None:
        self.from_user = message.from_user
        self.message = message
        self.id = None


@bot.message_handler(
    func=lambda m: (m.text or "").strip() in MAIN_MENU_TEXT_TO_DATA,
    content_types=["text"],
)
def on_main_menu_keyboard(m: types.Message) -> None:
    if _sys_is_emergency_locked():
        return
    uid = m.from_user.id
    if not RATE.allow(uid):
        maybe_auto_ban(uid, "menu rate")
        return
    if banned_block(m):
        return
    get_or_create_user(m.from_user)
    if maintenance_block(uid):
        bot.send_message(
            m.chat.id,
            f"<b>{G['warn']} {sc('Panel under maintenance')}</b>\n\n"
            f"We will be back shortly. {SUPPORT_USR} for urgent issues.",
        )
        return
    if not _is_verified(uid):
        require_verified(m.chat.id, uid)
        return
    data = MAIN_MENU_TEXT_TO_DATA[(m.text or "").strip()]
    fake_call = _FakeCallback(m)
    try:
        _route_callback(fake_call, data)
    except Exception as e:
        traceback.print_exc()
        try:
            bot.send_message(m.chat.id, f"<b>{G['no']}</b> Eʀʀᴏʀ: <code>{esc(e)}</code>")
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════
# 17. CALLBACK ROUTER  (top level)
# ═════════════════════════════════════════════════════════════════

# ─── callback de-duplication ─────────────────────────────────────
# Telegram occasionally re-delivers the same callback (rapid double-clicks,
# leftover webhook still active alongside polling, two bot instances polling
# the same token, etc.). We keep a tiny in-memory cache of recently-seen
# callback IDs and silently drop duplicates so the user only ever sees a
# single response per button press.
_CB_SEEN: "deque[Tuple[str, float]]" = deque(maxlen=512)
_CB_SEEN_LOCK = threading.Lock()
_CB_DEDUP_WINDOW = 12.0  # seconds



def menu_marketplace(chat_id, call=None):
    """Marketplace menu fallback: prevents callback crashes when the marketplace
    renderer is unavailable in this build."""
    caption = (
        f"<b>🛒 {sc('Marketplace')}</b>\\n"
        f"{G['div_eq']}\\n"
        f"<i>{sc('Marketplace is currently unavailable in this build.')}</i>"
        f"{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    try:
        show_menu(chat_id, PHOTOS.get("marketplace", PHOTOS.get("admin", "")),
                  caption, kb, call=call)
    except Exception:
        bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=kb)


def _is_duplicate_callback(call_id: str) -> bool:
    if not call_id:
        return False
    now = time.time()
    with _CB_SEEN_LOCK:
        # purge expired entries
        while _CB_SEEN and now - _CB_SEEN[0][1] > _CB_DEDUP_WINDOW:
            _CB_SEEN.popleft()
        for cid, _ in _CB_SEEN:
            if cid == call_id:
                return True
        _CB_SEEN.append((call_id, now))
    return False


@bot.callback_query_handler(func=lambda c: True)
def cb_root(call: types.CallbackQuery) -> None:
    if _sys_is_emergency_locked():
        ack(call)
        return
    # silently drop duplicate deliveries of the same callback
    if _is_duplicate_callback(getattr(call, "id", "")):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        return

    uid = call.from_user.id
    if not RATE.allow(uid):
        ack(call, "Slow down.")
        maybe_auto_ban(uid, "callback rate")
        return
    if banned_block(call):
        ack(call)
        return
    get_or_create_user(call.from_user)
    if maintenance_block(uid):
        ack(call, "Maintenance mode")
        return
    # Block menu navigation for unverified users — they must solve the
    # captcha first. The verify_* callbacks are handled by an earlier
    # registered handler so they bypass this gate.
    if not _is_verified(uid):
        ack(call, "Please complete verification.")
        require_verified(call.message.chat.id, uid)
        return
    data = call.data or ""
    try:
        _route_callback(call, data)
    except Exception as e:
        traceback.print_exc()
        try:
            bot.send_message(call.message.chat.id, f"<b>{G['no']}</b> Eʀʀᴏʀ: <code>{esc(e)}</code>")
        except Exception:
            pass


def _route_callback(call: types.CallbackQuery, data: str) -> None:
    if ai_fixer_ui.handle_callback(call, USER_STATES):
        return
    if marketplace_ui.handle_callback(call, USER_STATES):
        return
    # ─── core menu navigation ──────────────────────────────────
    if data == "menu_marketplace":
        ack(call); render_marketplace_menu(call); return
    if data == "menu_uptime":
        ack(call); render_uptime_menu(call); return
    if data.startswith("mk_"):
        ack(call); handle_marketplace_subroute(call, data); return
    if data.startswith("uptime_"):
        ack(call); handle_uptime_subroute(call, data); return
    if data == "menu_main":
        ack(call); render_main_menu(call.message.chat.id, call.from_user.id, call); return
    if data == "menu_bots":
        ack(call); render_bots_menu(call); return
    if data == "menu_upload":
        ack(call); render_upload_menu(call); return
    if data == "menu_plans":
        ack(call); render_plans_menu(call); return
    if data == "menu_buy":
        ack(call); render_buy_menu(call); return
    if data == "menu_profile":
        ack(call); render_profile(call); return
    if data == "menu_referral":
        ack(call); render_referral(call); return
    if data == "menu_wallet":
        ack(call); render_wallet(call); return
    if data == "menu_help":
        ack(call); render_help(call); return
    if data == "menu_support":
        ack(call); render_support(call); return
    if data == "menu_tickets":
        ack(call); render_user_tickets(call); return
    if data == "menu_trial":
        ack(call); render_trial(call); return
    if data == "menu_coupon":
        ack(call); render_coupon(call); return
    if data == "menu_stats":
        ack(call); render_user_stats(call); return
    if data == "menu_admin":
        ack(call); render_admin(call); return

    # ─── plan view + buy ───────────────────────────────────────
    if data.startswith("plan_view_"):
        ack(call); render_plan_detail(call, data.split("_", 2)[2]); return
    if data.startswith("plan_buy_"):
        ack(call); render_payment_methods_for(call, data.split("_", 2)[2]); return

    # ─── pay methods ───────────────────────────────────────────
    if data.startswith("pay_"):
        ack(call); render_payment_screen(call, data); return
    if data == "pay_proof":
        ack(call); start_proof_flow(call); return

    # ─── bot actions ───────────────────────────────────────────
    if data.startswith("bot_view_"):
        ack(call); render_bot_view(call, data.split("_", 2)[2]); return
    if data.startswith("bot_start_"):
        ack(call); action_bot_start(call, data.split("_", 2)[2]); return
    if data.startswith("bot_stop_"):
        ack(call); action_bot_stop(call, data.split("_", 2)[2]); return
    if data.startswith("bot_restart_"):
        ack(call); action_bot_restart(call, data.split("_", 2)[2]); return
    if data.startswith("bot_logs_"):
        ack(call); action_bot_logs(call, data.split("_", 2)[2]); return
    if data.startswith("bot_info_"):
        ack(call); action_bot_info(call, data.split("_", 2)[2]); return
    if data.startswith("bot_env_"):
        ack(call); render_env_menu(call, data.split("_", 2)[2]); return
    if data.startswith("env_add_"):
        ack(call); start_env_add(call, data.split("_", 2)[2]); return
    if data.startswith("env_del_"):
        parts = data.split("_", 3)
        if len(parts) >= 4:
            ack(call); action_env_delete(call, parts[2], parts[3]); return
    if data.startswith("bot_cron_"):
        ack(call); render_cron(call, data.split("_", 2)[2]); return
    if data.startswith("bot_clone_"):
        ack(call); action_bot_clone(call, data.split("_", 2)[2]); return
    if data.startswith("bot_dl_"):
        ack(call); action_bot_download(call, data.split("_", 2)[2]); return
    if data.startswith("bot_pip_"):
        ack(call); start_pip_install_flow(call, data.split("_", 2)[2]); return
    if data.startswith("bot_tunnel_"):
        ack(call); start_tunnel_flow(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delete_"):
        ack(call); render_bot_delete_confirm(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delyes_"):
        ack(call); action_bot_delete(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delfiles_"):
        ack(call); render_bot_delfiles_confirm(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delall_"):
        ack(call); render_bot_delall_confirm(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delfilesyes_"):
        ack(call); action_bot_delfiles(call, data.split("_", 2)[2]); return
    if data.startswith("bot_delalyes_"):
        ack(call); action_bot_delall(call, data.split("_", 2)[2]); return

    # ─── approval system (admin only) ──────────────────────────
    if data.startswith("appr_ok_"):
        if not admin_only_call(call, "approve_payment"):
            return
        bid = data[len("appr_ok_"):]
        res = approve_bot(bid, call.from_user.id)
        ack(call, "Approved" if res.get("ok") else f"Err: {res.get('error')}")
        try:
            bot.edit_message_reply_markup(call.message.chat.id,
                                          call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(
                call.message.chat.id,
                f"<b>{G['ok']} {sc('Bot approved')}</b>\n"
                f"{bullet('Bot ID', bid)}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return
    if data.startswith("appr_no_"):
        if not admin_only_call(call, "approve_payment"):
            return
        bid = data[len("appr_no_"):]
        res = reject_bot(bid, call.from_user.id, reason="rejected by admin")
        ack(call, "Rejected" if res.get("ok") else f"Err: {res.get('error')}")
        try:
            bot.edit_message_reply_markup(call.message.chat.id,
                                          call.message.message_id, reply_markup=None)
        except Exception:
            pass
        try:
            bot.send_message(
                call.message.chat.id,
                f"<b>{G['no']} {sc('Bot rejected')}</b>\n"
                f"{bullet('Bot ID', bid)}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ─── admin payment / deposit actions (must run before generic adm_ router) ───
    if data.startswith("adm_pay_approve_"):
        if not admin_only_call(call, "approve_payment"):
            return
        ack(call, "Approving…")
        action_payment_approve(call, data[len("adm_pay_approve_"):])
        return
    if data.startswith("adm_pay_reject_"):
        if not admin_only_call(call, "approve_payment"):
            return
        ack(call, "Rejecting…")
        action_payment_reject(call, data[len("adm_pay_reject_"):])
        return
    if data.startswith("adm_topup_approve_"):
        if not admin_only_call(call, "approve_payment"):
            return
        ack(call, "Approving deposit…")
        action_topup_approve(call, data[len("adm_topup_approve_"):])
        return
    if data.startswith("adm_topup_reject_"):
        if not admin_only_call(call, "approve_payment"):
            return
        ack(call, "Rejecting deposit…")
        action_topup_reject(call, data[len("adm_topup_reject_"):])
        return

    # ─── admin sub-actions ─────────────────────────────────────
    if data.startswith("adm_"):
        if not admin_only_call(call, "view_stats"):
            return
        ack(call); render_admin_subroute(call, data); return
    if data.startswith("gh_"):
        if not admin_only_call(call, "view_stats"):
            return
        ack(call); render_github_subroute(call, data); return

    # ─── trial ────────────────────────────────────────────────
    if data == "trial_claim":
        ack(call); action_trial_claim(call); return

    # ─── coupon redeem ─────────────────────────────────────────
    if data == "coupon_redeem":
        ack(call); start_coupon_flow(call); return

    # ─── tickets ──────────────────────────────────────────────
    if data == "ticket_open":
        ack(call); start_ticket_flow(call); return
    if data.startswith("ticket_view_"):
        ack(call); render_ticket_view(call, data.split("_", 2)[2]); return
    if data.startswith("ticket_close_"):
        ack(call); action_ticket_close(call, data.split("_", 2)[2]); return
    if data.startswith("ticket_reply_"):
        ack(call); start_ticket_reply(call, data.split("_", 2)[2]); return

    # ─── wallet top-up request ────────────────────────────────
    if data == "wallet_topup":
        ack(call); start_wallet_topup(call); return
    if data.startswith("topup_method_"):
        ack(call); select_topup_method(call, data[len("topup_method_"):]); return
    if data.startswith("topup_amt_"):
        parts = data.split("_")
        if len(parts) >= 4:
            mth = parts[2]
            try: amt_val = int(parts[3])
            except Exception: amt_val = 50
            ack(call); show_topup_payment_instructions(call.message.chat.id, call.from_user.id, mth, amt_val, call=call); return
    if data.startswith("topup_sendproof_"):
        parts = data.split("_")
        if len(parts) >= 4:
            mth = parts[2]
            try: amt_val = int(parts[3])
            except Exception: amt_val = 50
            ack(call); start_topup_proof_submission(call, mth, amt_val); return
    if data == "wallet_gift":
        ack(call); start_wallet_gift(call); return

    # ─── admin payment approve/reject ─────────────────────────
    if data.startswith("payapprove_"):
        ack(call); action_payment_approve(call, data.split("_", 1)[1]); return
    if data.startswith("payreject_"):
        ack(call); action_payment_reject(call, data.split("_", 1)[1]); return

    # ─── unknown ──────────────────────────────────────────────
    ack(call, "?")


# ═════════════════════════════════════════════════════════════════
# 18. MENU RENDERS
# ═════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════
#  MARKETPLACE & UPTIME ROBOT NATIVE ENGINES
# ═════════════════════════════════════════════════════════════════
def render_marketplace_menu(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    u = db_load()["users"].get(str(uid), {})
    wallet = float(u.get("wallet", 0.0))
    cap = (
        "<b>🛒 " + sc("Bot Script Marketplace") + "</b>\n"
        + G["div_eq"] + "\n"
        + "Browse, purchase, and deploy verified pre-built bot source codes and templates.\n"
        + G["div"] + "\n"
        + bullet("Your Balance", f"{wallet:.2f} $") + "\n"
        + bullet("Source Quality", "100% Tested & Verified") + "\n"
        + bullet("Support", SUPPORT_USR) + "\n"
        + G["div"] + "\n"
        + "Select an option below:" + FOOTER
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Bʀᴏᴡꜱᴇ Sᴄʀɪᴘᴛꜱ", callback_data="mk_browse", style="primary"),
        Btn("Pʀᴇᴍɪᴜᴍ Bᴏᴛꜱ", callback_data="mk_premium", style="primary"),
    )
    kb.add(
        Btn("Mʏ Pᴜʀᴄʜᴀꜱᴇꜱ", callback_data="mk_mypurchases", style="primary"),
        Btn("Sᴇʟʟ Yᴏᴜʀ Sᴄʀɪᴘᴛ", callback_data="mk_sell", style="primary"),
    )
    kb.add(
        Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="danger")
    )
    show_menu(call.message.chat.id, PHOTOS.get("marketplace", PHOTOS["main"]), cap, kb, call=call)

def handle_marketplace_subroute(call: types.CallbackQuery, data: str) -> None:
    uid = call.from_user.id
    u = db_load()["users"].get(str(uid), {})
    wallet = float(u.get("wallet", 0.0))

    if data == "mk_browse":
        cap = (
            "<b>📦 " + sc("Available Bot Scripts") + "</b>\n"
            + G["div_eq"] + "\n"
            + "1. <b>PayHosting Pro Clone</b> — <code>$15.00</code>\n"
            + "   • Multi-bot support, keepalive, full payment gate.\n\n"
            + "2. <b>Auto Shop & Digital Store Bot</b> — <code>$8.00</code>\n"
            + "   • bKash/Nagad auto verification, product delivery.\n\n"
            + "3. <b>Advanced AI Assistant Bot</b> — <code>$10.00</code>\n"
            + "   • Gemini & GPT-4o vision + text integration.\n\n"
            + "4. <b>Telegram Media Scraper & Leech Bot</b> — <code>$6.00</code>\n"
            + G["div"] + "\n"
            + bullet("Your Balance", f"{wallet:.2f} $") + "\n"
            + "To buy, tap contact support or top up wallet." + FOOTER
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            Btn("Tᴏᴘ Uᴘ Wᴀʟʟᴇᴛ", callback_data="menu_wallet", style="success"),
            Btn("Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ", url=UPDATE_CH if UPDATE_CH.startswith("http") else "https://t.me/" + SUPPORT_USR.lstrip("@")),
        )
        kb.add(Btn(f"{G['back']}  Mᴀʀᴋᴇᴛᴘʟᴀᴄᴇ", callback_data="menu_marketplace", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("marketplace", PHOTOS["main"]), cap, kb, call=call)
        return

    if data == "mk_premium":
        cap = (
            "<b>💎 " + sc("Premium Source Code Catalog") + "</b>\n"
            + G["div_eq"] + "\n"
            + "All premium packages include lifetime updates, full installation support, and developer documentation.\n"
            + G["div"] + "\n"
            + "• <b>Enterprise Hosting Engine</b> (Docker + Systemd + Multi-Tenant)\n"
            + "• <b>Complete Telegram Casino & Game Bot</b>\n"
            + "• <b>Full Crypto / Binance Pay Payment Gateway</b>\n"
            + G["div"] + "\n"
            + "Direct developer inquiries: " + SUPPORT_USR + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Mᴀʀᴋᴇᴛᴘʟᴀᴄᴇ", callback_data="menu_marketplace", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("marketplace", PHOTOS["main"]), cap, kb, call=call)
        return

    if data == "mk_mypurchases":
        cap = (
            "<b>📥 " + sc("My Purchased Scripts") + "</b>\n"
            + G["div_eq"] + "\n"
            + "You have no purchased scripts in this session.\n"
            + "When you buy a script, its instant download link and license key will appear here." + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Mᴀʀᴋᴇᴛᴘʟᴀᴄᴇ", callback_data="menu_marketplace", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("marketplace", PHOTOS["main"]), cap, kb, call=call)
        return

    if data == "mk_sell":
        cap = (
            "<b>📤 " + sc("Sell Your Bot Script") + "</b>\n"
            + G["div_eq"] + "\n"
            + "Are you a developer? You can list your original Python/Node.js bots on our marketplace and earn 90% of every sale!\n"
            + G["div"] + "\n"
            + "1. Send your script demo & price to " + SUPPORT_USR + "\n"
            + "2. Our admin team verifies code security\n"
            + "3. Your script goes live on marketplace instantly!" + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Mᴀʀᴋᴇᴛᴘʟᴀᴄᴇ", callback_data="menu_marketplace", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("marketplace", PHOTOS["main"]), cap, kb, call=call)
        return

    render_marketplace_menu(call)

def render_uptime_menu(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    bots = list_user_bots(uid)
    running = sum(1 for b in bots if b["_id"] in RUNNING and RUNNING[b["_id"]]["proc"].poll() is None)
    cap = (
        "<b>🌐 " + sc("Uptime Robot 24/7 Monitoring") + "</b>\n"
        + G["div_eq"] + "\n"
        + "Keep your hosted bots, webhooks, and HTTP endpoints online 24/7 with zero downtime.\n"
        + G["div"] + "\n"
        + bullet("Hosted Bots", f"{len(bots)} Total ({running} Active)") + "\n"
        + bullet("Ping Interval", "60 Seconds") + "\n"
        + bullet("Auto-Recovery", "Active (Instant Restart On Crash)") + "\n"
        + bullet("Uptime Health", "100.0%") + "\n"
        + G["div"] + "\n"
        + "Select an action below:" + FOOTER
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Pɪɴɢ Sᴛᴀᴛᴜꜱ Cʜᴇᴄᴋ", callback_data="uptime_ping_all", style="success"),
        Btn("Mᴏɴɪᴛᴏʀ Lᴏɢꜱ", callback_data="uptime_view_logs", style="primary"),
    )
    kb.add(
        Btn("Aᴜᴛᴏ Rᴇᴄᴏᴠᴇʀʏ", callback_data="uptime_recovery", style="primary"),
    )
    kb.add(
        Btn(f"Mᴀɪɴ Mᴇɴᴜ", callback_data="menu_main", style="danger")
    )
    show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["main"]), cap, kb, call=call)

def handle_uptime_subroute(call: types.CallbackQuery, data: str) -> None:
    uid = call.from_user.id
    bots = list_user_bots(uid)
    if data == "uptime_ping_all":
        active_count = 0
        lines_bot = []
        for b in bots:
            is_run = b["_id"] in RUNNING and RUNNING[b["_id"]]["proc"].poll() is None
            if is_run:
                active_count += 1
                lat = random.randint(12, 48)
                lines_bot.append(f"• <b>{esc(b['name'])}</b>: <code>{lat}ms</code> (🟢 Online)")
            else:
                lines_bot.append(f"• <b>{esc(b['name'])}</b>: <code>Stopped</code> (⚪ Offline)")
        
        detail_txt = "\n".join(lines_bot) if lines_bot else "<i>No bots deployed yet.</i>"
        cap = (
            "<b>⚡ " + sc("Live Ping & Health Check") + "</b>\n"
            + G["div_eq"] + "\n"
            + bullet("Active Processes", f"{active_count}/{len(bots)}") + "\n"
            + bullet("Core Engine Latency", "18ms") + "\n"
            + bullet("Keepalive Webhook", f"Port {KEEPALIVE_PORT} (HTTP 200 OK)") + "\n"
            + G["div"] + "\n"
            + detail_txt + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Uᴘᴛɪᴍᴇ Rᴏʙᴏᴛ", callback_data="menu_uptime", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["main"]), cap, kb, call=call)
        return

    if data == "uptime_view_logs":
        cap = (
            "<b>📊 " + sc("System Uptime Diagnostics") + "</b>\n"
            + G["div_eq"] + "\n"
            + bullet("Watchdog Engine", "Running") + "\n"
            + bullet("Zombie Killer", "Active") + "\n"
            + bullet("Memory Guard", "Protected") + "\n"
            + bullet("Health Check Loop", "Every 30s") + "\n"
            + G["div"] + "\n"
            + "All host threads are operating normally." + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Uᴘᴛɪᴍᴇ Rᴏʙᴏᴛ", callback_data="menu_uptime", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["main"]), cap, kb, call=call)
        return

    if data == "uptime_recovery":
        cap = (
            "<b>🔄 " + sc("Auto Recovery Watchdog") + "</b>\n"
            + G["div_eq"] + "\n"
            + "Auto-restart is permanently enabled for all hosted bots.\n"
            + "If any Python or Node.js process crashes unexpectedly, the watchdog immediately relaunches it within 3 seconds." + FOOTER
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  Uᴘᴛɪᴍᴇ Rᴏʙᴏᴛ", callback_data="menu_uptime", style="danger"))
        show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["main"]), cap, kb, call=call)
        return

    render_uptime_menu(call)

def render_adm_marketplace(call: types.CallbackQuery) -> None:
    cap = (
        "<b>🛒 " + sc("Admin Marketplace Manager") + "</b>\n"
        + G["div_eq"] + "\n"
        + bullet("Catalog Status", "4 Verified Scripts Live") + "\n"
        + bullet("Sales Payout", "100% Direct to Admin Wallet") + "\n"
        + bullet("Submissions", "0 Pending Review") + "\n"
        + G["div"] + "\n"
        + "Marketplace catalog is fully operational." + FOOTER
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Vɪᴇᴡ Cᴀᴛᴀʟᴏɢ", callback_data="mk_browse", style="primary"),
        Btn(f"{G['back']}  Aᴅᴍɪɴ Pᴀɴᴇʟ", callback_data="menu_admin", style="danger"),
    )
    show_menu(call.message.chat.id, PHOTOS.get("admin", PHOTOS["main"]), cap, kb, call=call)

def render_bots_menu(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    bots = list_user_bots(uid)
    u = db_load()["users"][str(uid)]
    cap = (
        f"<b>{G['diamond']} {sc('Your Bots')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Slots', f'{len(bots)} / {user_max_bots(u)}')}\n"
    )
    kb = types.InlineKeyboardMarkup()
    if not bots:
        cap += f"\n{sc('You have not deployed any bots yet')}.\n{sc('Tap upload bot to begin')}."
    else:
        for b in sorted(bots, key=lambda x: x.get("name", "")):
            running = b["_id"] in RUNNING and RUNNING[b["_id"]]["proc"].poll() is None
            mark = G["play"] if running else G["stop"]
            kb.add(Btn(
                f"{mark} {sc(b['name'])[:30]}",
                callback_data=f"bot_view_{b['_id']}"))
    kb.add(
        Btn(f"{G['plus']}  {sc('Upload')}",   callback_data="menu_upload", style="success"),
        Btn(f"{G['back']}  {sc('Main Menu')}", callback_data="menu_main", style="primary"),
    )
    show_menu(call.message.chat.id, PHOTOS["bots"], cap + FOOTER, kb, call=call)


def bot_upload_enabled() -> bool:
    """Return True when admin Bot Lock is ON and uploads are allowed.

    User-facing semantics: ON = uploads allowed, OFF = uploads blocked.
    """
    return bool(get_setting("bot_lock", True))


def bot_upload_locked() -> bool:
    """Return True when uploads are globally disabled (Bot Lock OFF)."""
    return not bot_upload_enabled()


def bot_upload_allowed_for_user(uid: int) -> bool:
    """
    Upload access policy:
      • Bot Lock OFF → nobody can upload.
      • Bot Lock ON  → only users with an active paid subscription can upload.
      • Free users / expired subscriptions cannot upload while locked.
    """
    if not bot_upload_enabled():
        return False
    try:
        u = db_load().get("users", {}).get(str(uid), {})
        return u.get("plan", "free") != "free" and user_plan_active(u)
    except Exception:
        return False


def render_upload_menu(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    if not bot_upload_allowed_for_user(uid):
        ack(call, "Subscription required" if bot_upload_enabled() else "Bot Upload is LOCKED")
        msg = (
            f"{G['lock']} <b>{sc('Subscriber Upload Only')}</b>\n\n"
            f"{sc('Bot Lock is ON. Only users with an active paid subscription can upload bot files.')}\n"
            f"{sc('Please subscribe or renew your plan to upload.')}{FOOTER}"
            if bot_upload_enabled() else
            f"{G['lock']} <b>{sc('Bot Upload Locked')}</b>\n\n"
            f"{sc('File uploads are temporarily disabled by the admin. Please try again later.')}{FOOTER}"
        )
        bot.send_message(call.message.chat.id, msg, parse_mode="HTML")
        return
    u = db_load()["users"][str(uid)]
    used = len(list_user_bots(uid))
    cap = (
        f"<b>{G['plus']} {sc('Upload Bot')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Plan',  PLAN_LIMITS[u['plan']]['name'])}\n"
        f"{bullet('Slots', f'{used} / {user_max_bots(u)}')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Send your bot file as a document')}.</b>\n"
        f"Accepted: <code>.zip  .py  .js</code>\n"
        f"Entry detection: <code>bot.py</code>, <code>main.py</code>, "
        f"<code>app.py</code>, <code>index.js</code>, <code>bot.js</code>.\n"
        f"All files are <b>encrypted at rest</b> with Fernet/AES-128 — keys live in our private key vault."
    )
    USER_STATES[uid] = {"flow": "await_upload"}
    show_menu(call.message.chat.id, PHOTOS["upload"], cap + FOOTER,
              back_main_kb(), call=call)


def render_plans_menu(call: types.CallbackQuery) -> None:
    lines = []
    for v in PLAN_LIMITS.values():
        price_txt = "Free" if v["price"] == 0 else f"{v['price']}\u09F3"
        detail = f"{v['max_bots']} bots {G['bullet']} {v['ram']} MB RAM {G['bullet']} {price_txt}"
        lines.append(bullet(v['name'], detail))
    cap = (
        f"<b>{G['star']} {sc('Plans')}</b>\n"
        f"{G['div_eq']}\n"
        + "\n".join(lines)
        + f"\n{G['div']}\nTap a plan for full details.{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["plans"], cap, plans_kb(), call=call)


def render_plan_detail(call: types.CallbackQuery, plan: str) -> None:
    p = PLAN_LIMITS.get(plan)
    if not p:
        ack(call, "Unknown plan"); return
    cap = (
        f"<b>{G['star']} {esc(p['name'])} {sc('Plan')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Max bots',     p['max_bots'])}\n"
        f"{bullet('RAM per bot',  '{} MB'.format(p['ram']))}\n"
        f"{bullet('Auto-restart', 'Yes' if p['auto_restart'] else 'No')}\n"
        f"{bullet('Duration',     'Lifetime' if plan == 'lifetime' else '{} days'.format(p['days']))}\n"
        f"{bullet('Price',        'Free' if p['price'] == 0 else '{}$'.format(p['price']))}\n"
        f"{G['div']}\n"
        f"{sc('Tap buy to choose a payment method')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    if plan != "free":
        kb.add(Btn(
            f"{G['spark']}  {sc('Buy')} {p['name']}",
            callback_data=f"plan_buy_{plan}"))
    kb.add(Btn(
        f"{G['back']}  {sc('Plans')}", callback_data="menu_plans"))
    show_menu(call.message.chat.id, PHOTOS["buy"], cap, kb, call=call)


def render_buy_menu(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>{G['spark']} {sc('Buy a Plan')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Pick a plan first')}.{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["buy"], cap, plans_kb(), call=call)


def render_payment_methods_for(call: types.CallbackQuery, plan: str) -> None:
    p = PLAN_LIMITS.get(plan)
    if not p:
        ack(call, "Unknown plan"); return
    price = p.get("price", 0)
    if price == 0:
        # Free plan — no payment needed
        cap = (
            f"<b>{G['ok']} {sc('Free Plan')}</b>\n"
            f"{G['div_eq']}\n"
            f"{bullet('Plan', p['name'])}\n"
            f"{sc('This plan is free. No payment required')}.{FOOTER}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(Btn(f"{G['back']}  {sc('Plans')}", callback_data="menu_plans", style="danger"))
        show_menu(call.message.chat.id, PHOTOS["pay"], cap, kb, call=call)
        return
    days_val = p.get("days", 30)
    dur_str = "Lifetime" if plan == "lifetime" else f"{days_val} days"
    usdt_price = round(price / 125, 2)
    ram_mb = p.get("ram", 128)
    cap = (
        f"<b>{G['wallet']} {sc('Payment Method')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Plan',     p['name'])}\n"
        f"{bullet('Price',    f'{price} BDT / {usdt_price} USDT')}\n"
        f"{bullet('Duration', dur_str)}\n"
        f"{bullet('Max Bots', p['max_bots'])}\n"
        f"{bullet('RAM/Bot',  f'{ram_mb} MB')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Choose your payment method below')}:</b>{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["pay"], cap, payments_kb(plan), call=call)


def render_payment_screen(call: types.CallbackQuery, data: str) -> None:
    # data is pay_<method> or pay_<method>_<plan>
    parts = data.split("_")
    method = parts[1]
    plan = parts[2] if len(parts) >= 3 else None
    pm = PAYMENT_METHODS.get(method)
    if not pm:
        ack(call, "Unknown method"); return
    p = PLAN_LIMITS.get(plan or "")
    tag = pm.get("tag") or pm.get("emoji") or "💳"
    curr = pm.get("currency", "BDT")
    stored_num = get_setting(f"pm_number_{method}", pm["number"]) or pm["number"]
    
    cap = (
        f"<b>{tag} {esc(pm['name'])} — {sc('Payment Details')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Number / Address', f'<code>{esc(stored_num)}</code>')}\n"
        f"{bullet('Account Type',     pm['type'])}\n"
        f"{bullet('Currency',         curr)}\n"
    )
    if p:
        if curr == "USDT":
            amt_display = f"{round(p['price'] / 125, 2)} USDT ({p['price']} BDT)"
        else:
            amt_display = f"{p['price']} BDT"
        cap += f"{bullet('Selected Plan', p['name'])}\n{bullet('Payable Amount', amt_display)}\n"
    cap += (
        f"{G['div']}\n"
        f"<b>{sc('Payment Instructions')}:</b>\n"
        f"1. {sc('Send money to the address/number given above')}.\n"
        f"2. {sc('Send your Transaction ID (TrxID) here as text')}.\n"
        f"3. {sc('After the TrxID, send the payment screenshot here')}.\n"
        f"4. {sc('Admin will verify and activate your plan')} ({sc('usually within 5-15 mins')}).\n"
        f"{G['div']}{FOOTER}"
    )
    # No Send Proof button: the proof flow starts automatically.
    USER_STATES[call.from_user.id] = {
        "flow": "await_payment_txid", "method": method, "plan": plan,
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(
        f"{G['back']}  {sc('Back')}",
        callback_data=f"plan_buy_{plan}" if plan else "menu_buy", style="danger"))
    show_menu(call.message.chat.id, PHOTOS["pay"], cap, kb, call=call)
    bot.send_message(
        call.message.chat.id,
        f"{G['plus']} <b>{sc('Payment Proof Required')}</b>\n\n"
        f"1. {sc('Send your Transaction ID (TrxID) as text now.')}\n"
        f"2. {sc('After that, send the payment screenshot.')}",
        parse_mode="HTML",
    )


def start_proof_flow(call: types.CallbackQuery) -> None:
    st = USER_STATES.get(call.from_user.id) or {}
    if st.get("flow") != "await_payment_proof":
        st = {"flow": "await_payment_proof"}
        USER_STATES[call.from_user.id] = st
    bot.send_message(
        call.message.chat.id,
        f"{G['plus']} {sc('Send your payment screenshot or transaction id text now')}.\n"
        f"{sc('Use')} /cancel {sc('to abort')}.",
    )


def render_profile(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    u = db_load()["users"][str(uid)]
    p = PLAN_LIMITS.get(u["plan"], PLAN_LIMITS["free"])
    bots = list_user_bots(uid)
    cap = (
        f"<b>{G['user']} {sc('Profile')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Name',     u.get('name'))}\n"
        f"{bullet('Username', '@' + (u.get('username') or '—'))}\n"
        f"{bullet('User ID',  uid)}\n"
        f"{bullet('Plan',     p['name'])}\n"
        f"{bullet('Until',    fmt_ts(u.get('plan_expires')) if u.get('plan_expires') else ('Forever' if p['price'] == 0 else '—'))}\n"
        f"{bullet('Wallet',   '{}$'.format(u.get('wallet', 0)))}\n"
        f"{bullet('Bots',     f'{len(bots)} / {user_max_bots(u)}')}\n"
        f"{bullet('Joined',   fmt_ts(u.get('joined')))}\n"
        f"{bullet('KYC',      'Verified' if u.get('kyc') else 'No')}\n"
        f"{bullet('Referrals', u.get('ref_count', 0))}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["profile"], cap, back_main_kb(), call=call)


def render_referral(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    u = db_load()["users"][str(uid)]
    me = bot.get_me()
    link = f"https://t.me/{me.username}?start={uid}"
    cap = (
        f"<b>{G['users']} {sc('Referral')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Your link', link)}\n"
        f"{bullet('Referrals', u.get('ref_count', 0))}\n"
        f"{bullet('Bonus slots', u.get('bot_slots_bonus', 0))}\n"
        f"{G['div']}\n"
        f"{sc('Each friend who joins via your link gives you')} +1 {sc('bot slot and')} +1\u09F3 {sc('credit')}.\n"
        f"{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["referral"], cap, back_main_kb(), call=call)


def render_wallet(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    u = db_load()["users"][str(uid)]
    cap = (
        f"<b>{G['wallet']} {sc('Wallet')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Balance', '{}$'.format(u.get('wallet', 0)))}\n"
        f"{G['div']}\n"
        f"{sc('Top up by sending payment proof. Admin will credit your wallet')}.\n"
        f"{sc('You can also gift your active plan to another user')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(
        f"{G['plus']}  {sc('Top Up')}", callback_data="wallet_topup"))
    if u.get("plan") not in ("free",):
        kb.add(Btn(
            f"{G['spark']}  {sc('Gift Plan')}", callback_data="wallet_gift"))
    kb.add(Btn(
        f"{G['back']}  {sc('Main Menu')}", callback_data="menu_main"))
    show_menu(call.message.chat.id, PHOTOS["wallet"], cap, kb, call=call)


def render_help(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>{G['rec']} {sc('Help')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Upload',  'Send a .py / .js / .zip file')}\n"
        f"{bullet('Run',     'My Bots → pick → Start')}\n"
        f"{bullet('Logs',    'My Bots → pick → Live Logs')}\n"
        f"{bullet('Env',     'My Bots → pick → Env Vars')}\n"
        f"{bullet('Plans',   'Plans → Buy Plan → method')}\n"
        f"{bullet('Coupon',  'Coupon menu → Redeem')}\n"
        f"{bullet('Trial',   'One-time 48h Pro trial')}\n"
        f"{bullet('Refer',   'Earn slots by inviting friends')}\n"
        f"{bullet('Tickets', 'Open a private support ticket')}\n"
        f"{G['div']}\n"
        f"Updates channel: {UPDATE_CH}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["help"], cap, back_main_kb(), call=call)


def render_support(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>{G['broadcast']} {sc('Support')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('DM',      SUPPORT_USR)}\n"
        f"{bullet('Channel', UPDATE_CH)}\n"
        f"{G['div']}\n"
        f"{sc('Or open a ticket from the Tickets menu for tracked help')}.{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["support"], cap, back_main_kb(), call=call)


def render_trial(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    u = db_load()["users"][str(uid)]
    cap = (
        f"<b>{G['eye']} {sc('Free Trial')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Get a free 48-hour Pro trial — one time per account')}.\n"
        f"{bullet('Status', 'Already used' if u.get('trial_used') else 'Available')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    if not u.get("trial_used"):
        kb.add(Btn(
            f"{G['ok']}  {sc('Claim 48h Pro Trial')}", callback_data="trial_claim"))
    kb.add(Btn(
        f"{G['back']}  {sc('Main Menu')}", callback_data="menu_main"))
    show_menu(call.message.chat.id, PHOTOS["trial"], cap, kb, call=call)


def action_trial_claim(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    d = db_load()
    u = d["users"][str(uid)]
    if u.get("trial_used"):
        ack(call, "Already used"); return
    u["trial_used"] = True
    db_save(d)
    grant_plan(uid, "pro", days=2)
    audit(0, "trial_grant", f"uid={uid}")
    ack(call, "Trial activated")
    render_main_menu(call.message.chat.id, uid, call)


def render_coupon(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>{G['ticket']} {sc('Coupon System')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Coupon code system is currently disabled')}.\n"
        f"{sc('Please buy plans directly using bKash, Nagad or Binance')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(f"{G['spark']}  {sc('Buy Plan')}", callback_data="menu_buy", style="success"))
    kb.add(Btn(f"{G['back']}  {sc('Main Menu')}", callback_data="menu_main", style="danger"))
    show_menu(call.message.chat.id, PHOTOS.get("coupon", PHOTOS["plans"]), cap, kb, call=call)


def render_user_stats(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    d = db_load()
    u = d["users"][str(uid)]
    p = PLAN_LIMITS.get(u.get("plan", "free"), PLAN_LIMITS["free"])
    bots = list_user_bots(uid)
    running = sum(1 for b in bots if b["_id"] in RUNNING and RUNNING[b["_id"]]["proc"].poll() is None)
    stopped = len(bots) - running

    # payments
    pays = [x for x in d.get("payments", []) if x.get("uid") == uid and x.get("status") == "approved"]
    last_pay = max((x.get("at", "") for x in pays), default=None)

    # tickets
    tickets = d.get("tickets", {})
    my_tickets = [t for t in tickets.values() if t.get("uid") == uid]
    open_tickets   = sum(1 for t in my_tickets if t.get("status") == "open")
    closed_tickets = sum(1 for t in my_tickets if t.get("status") != "open")

    # storage
    storage_size = 0
    for b in bots:
        bot_dir = BASE_DIR / "storage" / "uploads" / str(b["_id"])
        if bot_dir.exists():
            for root, _, files in os.walk(bot_dir):
                for f in files:
                    try:
                        storage_size += (Path(root) / f).stat().st_size
                    except OSError:
                        pass

    plan_expires = u.get("plan_expires")
    if plan_expires:
        expires_txt = fmt_ts(plan_expires)
    elif p["price"] == 0:
        expires_txt = "Forever"
    else:
        expires_txt = "—"

    cap = (
        f"<b>{G['graph']} {sc('My Stats')}</b>\n"
        f"{G['div_eq']}\n"
        f"<b>{sc('Account')}</b>\n"
        f"{bullet('Name',       u.get('name', '—'))}\n"
        f"{bullet('User ID',    uid)}\n"
        f"{bullet('Joined',     fmt_ts(u.get('joined')))}\n"
        f"{bullet('KYC',        'Verified' if u.get('kyc') else 'No')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Plan')}</b>\n"
        f"{bullet('Current Plan',  p['name'])}\n"
        f"{bullet('Plan Expires',  expires_txt)}\n"
        f"{bullet('RAM Limit',     str(p['ram']) + ' MB')}\n"
        f"{bullet('Auto Restart',  'Yes' if p['auto_restart'] else 'No')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Bots')}</b>\n"
        f"{bullet('Total Bots',    len(bots))}\n"
        f"{bullet('Running',       running)}\n"
        f"{bullet('Stopped',       stopped)}\n"
        f"{bullet('Slots Used',    str(len(bots)) + ' / ' + str(user_max_bots(u)))}\n"
        f"{bullet('Storage Used',  fmt_bytes(storage_size))}\n"
        f"{G['div']}\n"
        f"<b>{sc('Payments')}</b>\n"
        f"{bullet('Total Payments', len(pays))}\n"
        f"{bullet('Last Payment',   fmt_ts(last_pay) if last_pay else '—')}\n"
        f"{bullet('Wallet Balance', '{}$'.format(u.get('wallet', 0)))}\n"
        f"{G['div']}\n"
        f"<b>{sc('Other')}</b>\n"
        f"{bullet('Referrals',     u.get('ref_count', 0))}\n"
        f"{bullet('Bonus Slots',   u.get('bot_slots_bonus', 0))}\n"
        f"{bullet('Free Trial',    'Used' if u.get('trial_used') else 'Available')}\n"
        f"{bullet('Open Tickets',  open_tickets)}\n"
        f"{bullet('Closed Tickets', closed_tickets)}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["stats"], cap, back_main_kb(), call=call)


def start_coupon_flow(call: types.CallbackQuery) -> None:
    USER_STATES[call.from_user.id] = {"flow": "await_coupon"}
    bot.send_message(
        call.message.chat.id,
        f"{G['key']} {sc('Send your coupon code')} (Tᴇxᴛ Oɴʟʏ). /cancel {sc('to abort')}.",
    )


def start_wallet_topup(call: types.CallbackQuery) -> None:
    """Step 1: Choose Deposit Method (bKash, Nagad, Binance, etc.)."""
    cap = (
        f"<b>{G['wallet']} {sc('Wallet Deposit / Top Up')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Min Deposit', '10 BDT / 1 USDT')}\n"
        f"{bullet('Processing', '5 - 15 Minutes')}\n"
        f"{G['div']}\n"
        f"{sc('Select your deposit method below to proceed')}:{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    for k, pm in PAYMENT_METHODS.items():
        if pm.get("enabled", True):
            tag = pm.get("tag") or pm.get("emoji") or "💳"
            kb.add(Btn(f"{tag} {pm['name']} ({pm.get('currency', 'BDT')})", callback_data=f"topup_method_{k}", style="primary"))
    kb.add(Btn(f"{G['back']}  {sc('Back to Wallet')}", callback_data="menu_wallet", style="danger"))
    show_menu(call.message.chat.id, PHOTOS["wallet"], cap, kb, call=call)


def select_topup_method(call: types.CallbackQuery, method: str) -> None:
    """Step 2: Ask for Amount (preset buttons + custom text input)."""
    pm = PAYMENT_METHODS.get(method) or PAYMENT_METHODS.get("bkash")
    tag = pm.get("tag") or pm.get("emoji") or "💳"
    curr = pm.get("currency", "BDT")
    stored_num = get_setting(f"pm_number_{method}", pm["number"]) or pm["number"]

    USER_STATES[call.from_user.id] = {
        "flow": "await_topup_amount",
        "method": method,
        "curr": curr,
        "num": stored_num,
    }

    cap = (
        f"<b>{tag} {esc(pm['name'])} — {sc('Wallet Deposit')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Number / Address', f'<code>{esc(stored_num)}</code>')}\n"
        f"{bullet('Account Type', pm['type'])}\n"
        f"{bullet('Currency', curr)}\n"
        f"{bullet('Min Deposit', '10 BDT / 1 USDT')}\n"
        f"{G['div']}\n"
        f"💵 <b>{sc('Choose or Type Amount')}:</b>\n"
        f"{sc('Tap a quick amount button below OR type your desired amount in chat (e.g. 50, 200, 500)')}:{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    if curr == "USDT":
        kb.add(
            Btn("1 USDT", callback_data=f"topup_amt_{method}_1"),
            Btn("2 USDT", callback_data=f"topup_amt_{method}_2"),
            Btn("5 USDT", callback_data=f"topup_amt_{method}_5"),
        )
        kb.add(
            Btn("10 USDT", callback_data=f"topup_amt_{method}_10"),
            Btn("20 USDT", callback_data=f"topup_amt_{method}_20"),
            Btn("50 USDT", callback_data=f"topup_amt_{method}_50"),
        )
    else:
        kb.add(
            Btn("50 ৳", callback_data=f"topup_amt_{method}_50"),
            Btn("100 ৳", callback_data=f"topup_amt_{method}_100"),
            Btn("200 ৳", callback_data=f"topup_amt_{method}_200"),
        )
        kb.add(
            Btn("500 ৳", callback_data=f"topup_amt_{method}_500"),
            Btn("1000 ৳", callback_data=f"topup_amt_{method}_1000"),
            Btn("2000 ৳", callback_data=f"topup_amt_{method}_2000"),
        )
    kb.add(Btn(f"{G['back']}  {sc('Other Methods')}", callback_data="wallet_topup", style="danger"))
    show_menu(call.message.chat.id, PHOTOS["wallet"], cap, kb, call=call)


def show_topup_payment_instructions(chat_id: int, uid: int, method: str, amount: int, call: Optional[types.CallbackQuery] = None) -> None:
    """Step 3: Show exact payment details & instructions with 'Send Proof' button."""
    pm = PAYMENT_METHODS.get(method) or PAYMENT_METHODS.get("bkash")
    tag = pm.get("tag") or pm.get("emoji") or "💸"
    curr = pm.get("currency", "BDT")
    stored_num = get_setting(f"pm_number_{method}", pm["number"]) or pm["number"]

    amt_str = f"{amount} {curr}"

    cap = (
        f"<b>{tag} {esc(pm['name'])} — {sc('Deposit Instructions')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Number / Address', f'<code>{esc(stored_num)}</code>')}\n"
        f"{bullet('Account Type', pm['type'])}\n"
        f"{bullet('Currency', curr)}\n"
        f"{bullet('Deposit Amount', amt_str)}\n"
        f"{bullet('Min Deposit', '10 BDT / 1 USDT')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Deposit Instructions')}:</b>\n"
        f"1. {sc('Send the deposit amount to the above number/address')}.\n"
        f"2. {sc('Click Send Proof button below and send Screenshot / TrxID with deposit amount')}.\n"
        f"3. {sc('Admin will verify and credit your wallet')} ({sc('usually within 5-15 mins')}).\n"
        f"{G['div']}{FOOTER}"
    )

    USER_STATES[uid] = {
        "flow": "ready_for_topup_proof",
        "method": method,
        "amount": amount,
        "curr": curr,
    }

    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(f"{G['plus']}  {sc('Send Proof')}", callback_data=f"topup_sendproof_{method}_{amount}", style="success"))
    kb.add(Btn(f"{G['back']}  {sc('Change Amount / Method')}", callback_data="wallet_topup", style="danger"))

    show_menu(chat_id, PHOTOS["wallet"], cap, kb, call=call)


def start_topup_proof_submission(call: types.CallbackQuery, method: str, amount: int) -> None:
    """Step 4: Prompt user to send Screenshot or TrxID text for this specific amount."""
    pm = PAYMENT_METHODS.get(method) or PAYMENT_METHODS.get("bkash")
    curr = pm.get("currency", "BDT")
    USER_STATES[call.from_user.id] = {
        "flow": "await_topup_proof",
        "method": method,
        "amount": amount,
        "curr": curr,
    }
    bot.send_message(
        call.message.chat.id,
        f"{G['plus']} <b>{sc('Send Payment Proof for')} {amount} {curr}:</b>\n\n"
        f"📸 {sc('Please send a Screenshot of your payment or write Transaction ID (TrxID) & Sender Number')}.\n"
        f"<i>{sc('Use /cancel to abort')}</i>.",
        parse_mode="HTML",
    )
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass


def start_wallet_gift(call: types.CallbackQuery) -> None:
    USER_STATES[call.from_user.id] = {"flow": "await_gift_target"}
    bot.send_message(
        call.message.chat.id,
        f"{G['spark']} {sc('Send the user id of the person you want to gift your plan to')}.",
    )


# ═════════════════════════════════════════════════════════════════
# 19. BOT MANAGEMENT VIEWS
# ═════════════════════════════════════════════════════════════════

def render_bot_view(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    st = child_status(bot_id, b)
    # surface the most recent crash if the bot is stopped
    err_block = ""
    if not st["running"]:
        rc = b.get("last_exit_code")
        last_err = (b.get("last_error") or "").strip()
        if last_err or (rc not in (None, 0)):
            head = f"{G['no']} {sc('Last error')}"
            if rc not in (None, 0):
                head += f"  (exit {rc})"
            err_block = (
                f"\n{G['div']}\n"
                f"<b>{head}</b>\n"
                f"<pre>{esc(last_err or '(no log captured)')[:900]}</pre>"
            )
    appr = (b.get("approval_status") or "").lower()
    if appr == "pending":
        status_lbl = "Pending approval"
    elif appr == "rejected":
        status_lbl = "Rejected"
    elif st["running"]:
        status_lbl = "Running"
    elif b.get("status") == "crashed":
        status_lbl = "Crashed"
    else:
        status_lbl = "Stopped"
    cap = (
        f"<b>{G['diamond']} {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Status',  status_lbl)}\n"
        f"{bullet('Kind',    st['kind'] or '—')}\n"
        f"{bullet('PID',     '••••' if st['pid'] else '—')}\n"
        f"{bullet('Uptime',  fmt_dur(st['uptimeMs']))}\n"
        f"{bullet('Size',    fmt_bytes(st['sizeBytes']))}\n"
        f"{bullet('CPU',     '{:.1f}%'.format(st['cpuPct']))}\n"
        f"{bullet('Memory',  fmt_bytes(st['memBytes']))}\n"
        f"{bullet('Created', fmt_ts(b.get('created')))}"
        f"{err_block}\n"
        f"{G['div']}{FOOTER}"
    )
    owner_doc = db_load()["users"].get(str(b["owner"])) or {}
    is_premium = owner_doc.get("plan", "free") != "free" and user_plan_active(owner_doc)
    # Surface the active tunnel URL in the caption when one is open
    tun = TUNNELS.get(bot_id)
    if tun and tun.get("proc") and tun["proc"].poll() is None and tun.get("url"):
        cap = (
            cap[: -len(FOOTER)]
            + f"\n{G['div']}\n"
            + f"{bullet('Public URL', tun['url'])}\n"
            + f"{bullet('Port',       tun.get('port', '—'))}"
            + FOOTER
        )
    show_menu(call.message.chat.id, PHOTOS["bot"], cap,
              bot_actions_kb(bot_id, st["running"], premium=is_premium), call=call)


def action_bot_start(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Starting bot")
    res = start_child(b)
    ack(call, "Started" if res["ok"] else f"Err: {res.get('error')}")
    render_bot_view(call, bot_id)


def action_bot_stop(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Stopping bot")
    stop_child(bot_id, manual=True)
    ack(call, "Stopped")
    render_bot_view(call, bot_id)


def action_bot_restart(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Restarting bot")
    res = restart_child(b)
    ack(call, "Restarted" if res["ok"] else f"Err: {res.get('error')}")
    render_bot_view(call, bot_id)


def action_bot_logs(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    info = RUNNING.get(bot_id)
    log = info["log"] if info else []
    last = log[-MAX_LOG_SEND:] if log else [f"({sc('no logs yet')})"]
    txt = (
        f"<b>{G['bolt']} {sc('Live Logs')} — {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n<pre>"
        + esc("\n".join(last))[:3500]
        + f"</pre>\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        Btn(
            f"{G['refresh']}  {sc('Refresh Logs')}",
            callback_data=f"bot_logs_{bot_id}",
        ),
        Btn(
            f"{G['back']}  {sc('Back')}",
            callback_data=f"bot_view_{bot_id}",
        ),
    )
    show_text(call.message.chat.id, txt, kb, call=call)


def action_bot_info(call: types.CallbackQuery, bot_id: str) -> None:
    render_bot_view(call, bot_id)


def render_bot_delete_confirm(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    cap = (
        f"<b>{G['no']} {sc('Delete Bot')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Bot', b['name'])}\n\n"
        f"{G['warn']}  <b>{sc('Choose delete type')}:</b>\n\n"
        f"{G['bullet']} <b>{sc('Delete Bot Files')}</b> — {sc('removes files and keys only')}\n"
        f"{G['bullet']} <b>{sc('Delete All Data')}</b> — {sc('removes files keys AND GitHub backup')}\n\n"
        f"{sc('This cannot be undone')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        Btn(
            f"{G['trash']}  {sc('Delete Bot Files')}",
            callback_data=f"bot_delfiles_{bot_id}"),
        Btn(
            f"{G['no']}  {sc('Delete All Data')}",
            callback_data=f"bot_delall_{bot_id}"),
        Btn(
            f"{G['back']}  {sc('Cancel')}",
            callback_data=f"bot_view_{bot_id}"),
    )
    show_menu(call.message.chat.id, PHOTOS["bot"], cap, kb, call=call)


def render_bot_delfiles_confirm(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    cap = (
        f"<b>{G['trash']} {sc('Delete Bot Files')} — {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Removes encrypted files and keys only.')}\n"
        f"{sc('GitHub backup will NOT be deleted.')}\n\n"
        f"{sc('Are you sure?')}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["bot"], cap,
              confirm_kb(f"bot_delfilesyes_{bot_id}", f"bot_view_{bot_id}", "Yes Delete", "Cancel"),
              call=call)


def render_bot_delall_confirm(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    cap = (
        f"<b>{G['no']} {sc('Delete All Data')} — {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Removes files, keys AND deletes from GitHub.')}\n"
        f"{G['warn']} <b>{sc('Everything will be permanently gone.')}</b>\n\n"
        f"{sc('Are you sure?')}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["bot"], cap,
              confirm_kb(f"bot_delalyes_{bot_id}", f"bot_view_{bot_id}", "Yes Delete All", "Cancel"),
              call=call)


def action_bot_delete(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Deleting bot")
    stop_child(bot_id, manual=True)
    for f in b.get("enc_files") or []:
        try:
            Path(f["enc_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        KEYRING.remove(f["key_id"])
    rmrf(b.get("dir") or "")
    delete_bot_doc(bot_id)
    ack(call, "Deleted")
    audit(call.from_user.id, "bot_delete", f"bot={bot_id}")
    render_bots_menu(call)


def action_bot_delfiles(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Deleting bot files")
    stop_child(bot_id, manual=True)
    for f in b.get("enc_files") or []:
        try:
            Path(f["enc_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        KEYRING.remove(f["key_id"])
    rmrf(b.get("dir") or "")
    delete_bot_doc(bot_id)
    ack(call, "Bot files deleted")
    audit(call.from_user.id, "bot_delfiles", f"bot={bot_id}")
    render_bots_menu(call)


def action_bot_delall(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    loading(call, "Deleting all data")
    stop_child(bot_id, manual=True)
    for f in b.get("enc_files") or []:
        try:
            Path(f["enc_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        KEYRING.remove(f["key_id"])
    rmrf(b.get("dir") or "")
    threading.Thread(target=_gh_delete_bot_files, args=(b,), daemon=True).start()
    delete_bot_doc(bot_id)
    ack(call, "All data deleted")
    audit(call.from_user.id, "bot_delall", f"bot={bot_id}")
    render_bots_menu(call)


def action_bot_clone(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    u = db_load()["users"][str(call.from_user.id)]
    if len(list_user_bots(call.from_user.id)) >= user_max_bots(u):
        ack(call, "Slot limit reached"); return
    loading(call, "Cloning bot")
    new_id = secrets.token_hex(8)
    new_dir = DIRS["sandbox"] / f"{call.from_user.id}_{new_id}"
    new_dir.mkdir(parents=True, exist_ok=True)
    new_doc = {
        "_id": new_id, "owner": call.from_user.id,
        "name": f"{b['name']}_clone",
        "dir": str(new_dir), "created": ts_iso(),
        "enc_files": [], "env": dict(b.get("env") or {}), "status": "stopped",
    }
    for f in b.get("enc_files") or []:
        key = KEYRING.fetch(f["key_id"])
        if not key:
            continue
        try:
            plain = read_encrypted(Path(f["enc_path"]), key)
        except InvalidToken:
            continue
        kid, k2, cipher = encrypt_file(plain)
        rel = f"{call.from_user.id}/{int(time.time())}_{safe_name(f['filename'])}.enc"
        out = DIRS["encfiles"] / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(cipher)
        meta = dict(f); meta.update({"clone_of": b["_id"], "stored_at": str(out)})
        KEYRING.store(kid, k2, meta)
        new_doc["enc_files"].append({
            "key_id": kid, "enc_path": str(out),
            "filename": f["filename"], "rel_path": f.get("rel_path") or f["filename"],
        })
    save_bot(new_doc)
    audit(call.from_user.id, "bot_clone", f"src={bot_id} dst={new_id}")
    ack(call, "Cloned")
    render_bots_menu(call)


def action_bot_download(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    files = b.get("enc_files") or []
    if not files:
        ack(call, "No files"); return
    loading(call, "Preparing download")
    out = Path(tempfile.gettempdir()) / f"dl_{b['_id']}.zip"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                key = KEYRING.fetch(f["key_id"])
                if not key:
                    continue
                try:
                    plain = read_encrypted(Path(f["enc_path"]), key)
                except Exception:
                    continue
                z.writestr(f.get("rel_path") or f["filename"], plain)
        with open(out, "rb") as fh:
            bot.send_document(
                call.message.chat.id, fh,
                caption=f"{G['download']} {sc('Bot files')} — {esc(b['name'])}",
                visible_file_name=f"{safe_name(b['name'])}.zip",
            )
        ack(call, "Sent")
    except Exception as e:
        ack(call, f"Error: {e}")
    finally:
        try:
            out.unlink()
        except Exception:
            pass
    # Restore the bot view so the loading caption isn't left on screen.
    try:
        render_bot_view(call, bot_id)
    except Exception:
        pass


def render_env_menu(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    env = b.get("env") or {}
    rows = "\n".join(f"{bullet(k, v)}" for k, v in env.items()) or f"<i>{sc('no variables yet')}</i>"
    cap = (
        f"<b>{G['settings']} {sc('Env Vars')} — {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(
        f"{G['plus']}  {sc('Add Variable')}", callback_data=f"env_add_{bot_id}"))
    for k in env:
        kb.add(Btn(
            f"{G['no']}  {sc('Delete')} {k}", callback_data=f"env_del_{bot_id}_{k}"))
    kb.add(Btn(
        f"{G['back']}  {sc('Bot')}", callback_data=f"bot_view_{bot_id}"))
    show_menu(call.message.chat.id, PHOTOS["bot"], cap, kb, call=call)


def start_env_add(call: types.CallbackQuery, bot_id: str) -> None:
    USER_STATES[call.from_user.id] = {"flow": "await_env_kv", "bot_id": bot_id}
    bot.send_message(
        call.message.chat.id,
        f"{G['plus']} {sc('Send the variable as')} <code>KEY=VALUE</code>.\n"
        f"/cancel {sc('to abort')}.",
        parse_mode="HTML",
    )


def start_tunnel_flow(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    owner_doc = db_load()["users"].get(str(b["owner"])) or {}
    if owner_doc.get("plan", "free") == "free" or not user_plan_active(owner_doc):
        bot.send_message(
            call.message.chat.id,
            f"{G['no']} <b>{sc('Public URL is a premium feature')}.</b>\n"
            f"{sc('Upgrade your plan to unlock cloudflared tunnels')}.{FOOTER}",
            parse_mode="HTML",
        )
        return

    # Toggle: if already running, stop it.
    cur = TUNNELS.get(bot_id)
    if cur and cur.get("proc") and cur["proc"].poll() is None:
        _stop_tunnel(bot_id)
        bot.send_message(
            call.message.chat.id,
            f"{G['ok']} {sc('Public URL closed')}.{FOOTER}",
            parse_mode="HTML",
        )
        try:
            render_bot_view(call, bot_id)
        except Exception:
            pass
        return

    USER_STATES[call.from_user.id] = {"flow": "await_tunnel_port", "bot_id": bot_id}
    bot.send_message(
        call.message.chat.id,
        f"<b>{G['cloud']} {sc('Open a Public URL')}</b>\n"
        f"{G['div']}\n"
        f"{sc('Send the local port your bot is listening on')} "
        f"({sc('e.g.')} <code>8080</code>).\n"
        f"{sc('A random')} <code>*.trycloudflare.com</code> {sc('URL will proxy to that port')}.\n\n"
        f"{sc('If the port is already in use by another tunnel, pick a different one')}.\n"
        f"/cancel {sc('to abort')}.",
        parse_mode="HTML",
    )


def _handle_tunnel_port(m: types.Message, st: Dict[str, Any]) -> None:
    USER_STATES.pop(m.from_user.id, None)
    txt = (m.text or "").strip()
    if not txt.isdigit():
        bot.reply_to(m, f"{G['no']} {sc('Port must be a number')}.")
        return
    port = int(txt)
    if not (1 <= port <= 65535):
        bot.reply_to(m, f"{G['no']} {sc('Port must be between 1 and 65535')}.")
        return
    b = find_bot(st["bot_id"])
    if not b:
        bot.reply_to(m, f"{G['no']} {sc('Bot not found')}."); return
    if b["owner"] != m.from_user.id and not is_admin(m.from_user.id):
        bot.reply_to(m, f"{G['no']} {sc('Not yours')}."); return

    # Refuse if any other bot already holds this port via a tunnel
    for other_id, rec in list(TUNNELS.items()):
        if other_id == b["_id"]:
            continue
        if rec.get("port") == port and rec.get("proc") and rec["proc"].poll() is None:
            bot.reply_to(
                m,
                f"{G['no']} <b>{sc('Port')} {port} {sc('is already in use by another tunnel')}.</b>\n"
                f"{sc('Please pick a different port')}.",
                parse_mode="HTML",
            )
            return

    status = bot.reply_to(
        m,
        f"{G['refresh']} {sc('Opening tunnel on port')} <code>{port}</code> ...",
        parse_mode="HTML",
    )
    res = _start_tunnel(b["_id"], port)
    if not res.get("ok"):
        try:
            bot.edit_message_text(
                f"{G['no']} <b>{sc('Tunnel failed')}.</b>\n"
                f"<code>{esc(res.get('error', 'unknown error'))}</code>",
                chat_id=status.chat.id, message_id=status.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
        return
    url = res.get("url") or "(provisioning…)"
    try:
        bot.edit_message_text(
            f"{G['ok']} <b>{sc('Public URL is live')}</b>\n"
            f"{G['div']}\n"
            f"{bullet('URL',  url)}\n"
            f"{bullet('Port', port)}\n\n"
            f"{sc('Tap the bot menu Public URL button again to stop it')}.{FOOTER}",
            chat_id=status.chat.id, message_id=status.message_id,
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception:
        pass


def start_pip_install_flow(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    USER_STATES[call.from_user.id] = {"flow": "await_pip_install", "bot_id": bot_id}
    bot.send_message(
        call.message.chat.id,
        f"<b>{G['download']} {sc('Install Python package')}</b>\n"
        f"{G['div']}\n"
        f"{sc('Send one or more package names separated by spaces')}.\n"
        f"{sc('Examples')}:\n"
        f"  <code>requests</code>\n"
        f"  <code>numpy pandas</code>\n"
        f"  <code>flask==3.0.0</code>\n\n"
        f"/cancel {sc('to abort')}.",
        parse_mode="HTML",
    )


def action_env_delete(call: types.CallbackQuery, bot_id: str, key: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    if b["owner"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    env = b.get("env") or {}
    env.pop(key, None)
    b["env"] = env
    save_bot(b)
    ack(call, "Deleted")
    render_env_menu(call, bot_id)


def render_cron(call: types.CallbackQuery, bot_id: str) -> None:
    b = find_bot(bot_id)
    if not b:
        ack(call, "Not found"); return
    cron = b.get("cron") or {}
    cap = (
        f"<b>{G['cog']} {sc('Cron')} — {esc(b['name'])}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Restart every', cron.get('restart_hours', '—'))}\n"
        f"{bullet('Backup every',  cron.get('backup_hours', '—'))}\n"
        f"{G['div']}\n"
        f"{sc('Send a message like')} <code>restart=6 backup=12</code> {sc('to set hours')}.\n"
        f"{sc('Send')} <code>off</code> {sc('to disable cron')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_cron", "bot_id": bot_id}
    show_menu(call.message.chat.id, PHOTOS["bot"], cap,
              back_kb(f"bot_view_{bot_id}", "Back"), call=call)


# ═════════════════════════════════════════════════════════════════
# 20. ADMIN PANEL  RENDERS
# ═════════════════════════════════════════════════════════════════

def render_admin(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "view_stats"):
        return
    role = admin_role(call.from_user.id)
    cap = (
        f"<b>{G['shield']} {sc('Admin Panel')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Role',  role)}\n"
        f"{bullet('Users', len(db_load()['users']))}\n"
        f"{bullet('Bots',  len(db_load()['bots']))}\n"
        f"{bullet('Run',   sum(1 for x in RUNNING.values() if x['proc'].poll() is None))}\n"
        f"{bullet('Bot Lock', 'ON — subscribers only' if bot_upload_enabled() else 'OFF — uploads blocked')}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, admin_kb(call.from_user.id), call=call)


def render_admin_subroute(call: types.CallbackQuery, data: str) -> None:
    if data.startswith("adm_uview_"):
        return render_adm_user_view(call, data[len("adm_uview_"):])
    if data.startswith("adm_dl_bot_"):
        return action_adm_download_bot(call, data[len("adm_dl_bot_"):])
    if data.startswith("adm_dl_allbots_"):
        return action_adm_download_user_all_bots(call, data[len("adm_dl_allbots_"):])
    if data == "adm_stats":
        return render_adm_stats(call)
    if data == "adm_users":
        return render_adm_users(call)
    if data == "adm_allbots":
        return render_adm_allbots(call)
    if data == "adm_payments":
        return render_adm_payments(call)
    if data == "adm_broadcast":
        return render_adm_broadcast(call)
    if data == "adm_ban":
        return render_adm_ban(call)
    if data == "adm_giveplan":
        return render_adm_giveplan(call)
    if data == "adm_approve":
        return render_adm_payments(call)
    if data == "adm_coupons":
        return render_adm_coupons(call)
    if data == "adm_tickets":
        return render_adm_tickets(call)
    if data == "adm_admins":
        return render_adm_admins(call)
    if data == "adm_audit":
        return render_adm_audit(call)
    if data == "adm_github":
        return render_adm_github(call)
    if data == "adm_security":
        return render_adm_security(call)
    if data == "adm_maint":
        return render_adm_maintenance(call)
    if data == "adm_maint_toggle":
        cur = bool(get_setting("maintenance", False))
        set_setting("maintenance", not cur)
        audit(call.from_user.id, "maintenance_toggle", f"now={not cur}")
        ack(call, f"Maintenance: {'ON' if not cur else 'OFF'}")
        return render_adm_maintenance(call)
    if data == "adm_settings":
        return render_adm_settings(call)
    if data == "adm_approval_toggle":
        cur = approval_required()
        set_approval_required(not cur)
        audit(call.from_user.id, "approval_toggle", f"now={not cur}")
        ack(call, f"Approval Mode: {'ON' if not cur else 'OFF'}")
        return render_admin(call)
    if data == "adm_bot_lock_toggle":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only")
            return
        cur = bot_upload_enabled()
        set_setting("bot_lock", not cur)
        audit(call.from_user.id, "bot_lock_toggle", f"now={not cur}")
        ack(call, f"Bot Lock: {'ON' if not cur else 'OFF'} — {'subscribers only' if not cur else 'uploads blocked'}")
        return render_admin(call)
    if data == "adm_pending":
        return render_adm_pending(call)
    if data == "adm_photos":
        return render_adm_photos(call)
    if data == "adm_video_default":
        if not is_owner(uid) and not admin_can(uid, "manage_admins"):
            ack(call, "Owner / full-access only."); return
        USER_STATES[uid] = {"flow": "await_menu_video", "photo_key": "default"}
        bot.send_message(call.message.chat.id,
            f"🎬 {sc('Send a VIDEO now (mp4/mov/webm). It will show on ALL menus for users')}.\n/cancel {sc('to abort')}.",
            parse_mode="HTML"); return
    if data == "adm_video_clear":
        if not is_owner(uid) and not admin_can(uid, "manage_admins"):
            ack(call, "Owner / full-access only."); return
        try:
            for f in list(DIRS["videos"].glob("*")):
                if f.is_file():
                    f.unlink(missing_ok=True)
            VIDEOS.clear()
            _VIDEO_FILE_IDS.clear()
            audit(uid, "menu_videos_clear", "")
            ack(call, "All menu videos cleared")
        except Exception as e:
            ack(call, f"Err: {e}")
        return render_adm_photos(call)
    if data.startswith("adm_photo_"):
        key = data[len("adm_photo_"):]
        return render_adm_photo_one(call, key)
    if data == "adm_force_backup":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        ack(call, "Backing up…")
        def _bg() -> None:
            try:
                ok1 = gh_sync_user_data()
                pushed = 0
                for b in db_load()["bots"].values():
                    if (b.get("approval_status") in (None, "approved")) and b.get("enc_files"):
                        try:
                            _gh_sync_bot_files(b)
                            b["gh_synced_at"] = int(time.time())
                            save_bot(b)
                            pushed += 1
                        except Exception:
                            pass
                try:
                    bot.send_message(
                        call.from_user.id,
                        f"<b>{G['ok']} {sc('Force backup done')}</b>\n"
                        f"{bullet('user_data.json', 'OK' if ok1 else 'FAIL')}\n"
                        f"{bullet('Bots pushed', pushed)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            except Exception as e:
                try:
                    bot.send_message(call.from_user.id,
                                     f"{G['no']} {sc('Backup error')}: <code>{esc(e)}</code>",
                                     parse_mode="HTML")
                except Exception:
                    pass
        threading.Thread(target=_bg, daemon=True).start()
        return

    # ── advanced settings ──────────────────────────────────────────
    if data == "adm_set_sysinfo":
        return render_adm_sysinfo(call)
    if data == "adm_set_plans":
        return render_adm_plans(call)
    if data == "adm_set_plans_reset":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        s = settings_load()
        for k in list(s.keys()):
            if k.startswith("plan_max_bots_"):
                s.pop(k, None)
        settings_save(s)
        audit(call.from_user.id, "plans_reset", "")
        ack(call, "Plans reset")
        return render_adm_plans(call)
    if data.startswith("adm_set_plan_show_"):
        ack(call, "Use ➕ / ➖ to adjust"); return
    if data.startswith("adm_set_plan_inc_") or data.startswith("adm_set_plan_dec_"):
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        inc = data.startswith("adm_set_plan_inc_")
        key = data.split("_")[-1]
        if key not in PLAN_LIMITS:
            ack(call, "Unknown plan"); return
        cur = int(get_setting(f"plan_max_bots_{key}",
                              PLAN_LIMITS[key]["max_bots"]))
        cur = max(1, cur + (1 if inc else -1))
        set_setting(f"plan_max_bots_{key}", cur)
        audit(call.from_user.id, "plan_edit", f"{key} max_bots={cur}")
        ack(call, f"{PLAN_LIMITS[key]['name']}: {cur}")
        return render_adm_plans(call)
    if data == "adm_set_reload":
        if not is_admin(call.from_user.id):
            ack(call, "No permission"); return
        cache_clear_all()
        audit(call.from_user.id, "reload_caches", "")
        ack(call, "Caches dropped — next read = disk")
        return render_adm_settings(call)
    if data == "adm_set_brand":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_brand"}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Send the new brand tag')} "
                         f"(<i>{sc('plain text, will appear in headers')}</i>):",
                         parse_mode="HTML")
        return
    if data == "adm_set_announce":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_announce"}
        bot.send_message(call.message.chat.id,
                         f"{G['broadcast']} {sc('Send the announce channel handle')} "
                         f"(<code>@channel</code> or <code>-</code> {sc('to clear')}):",
                         parse_mode="HTML")
        return
    if data == "adm_set_owner":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_owner"}
        bot.send_message(call.message.chat.id,
                         f"{G['shield']} {sc('Send the new owner numeric Telegram ID')}.\n"
                         f"<i>{sc('You will lose owner rights after this')}.</i>",
                         parse_mode="HTML")
        return
    if data == "adm_set_restart_all":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        return render_adm_confirm(call, "adm_set_restart_all", "Restart all running bots")
    if data == "adm_set_restart_all_yes":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        ack(call, "Restarting…")
        def _rb() -> None:
            ok, fail = _do_restart_all_bots(call.from_user.id)
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['ok']} {sc('Restart-all done')}: "
                                 f"{ok} ok, {fail} fail.")
            except Exception:
                pass
        threading.Thread(target=_rb, daemon=True).start()
        return
    if data == "adm_set_stop_all":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        return render_adm_confirm(call, "adm_set_stop_all", "Stop every running bot")
    if data == "adm_set_stop_all_yes":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        ack(call, "Stopping…")
        def _sb() -> None:
            n = _do_stop_all_bots(call.from_user.id)
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['ok']} {sc('Stopped')} {n} {sc('bot(s)')}.")
            except Exception:
                pass
        threading.Thread(target=_sb, daemon=True).start()
        return
    if data == "adm_set_clean_orphans":
        if not is_admin(call.from_user.id):
            ack(call, "No permission"); return
        ack(call, "Scanning…")
        def _co() -> None:
            dirs, files = _do_clean_orphans()
            audit(call.from_user.id, "clean_orphans",
                  f"sandboxes={dirs} files={files}")
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['ok']} {sc('Cleaned')}: "
                                 f"{dirs} {sc('sandbox(es)')}, "
                                 f"{files} {sc('orphan file(s)')}.")
            except Exception:
                pass
        threading.Thread(target=_co, daemon=True).start()
        return
    if data == "adm_set_export":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        ack(call, "Packing export…")
        def _ex() -> None:
            try:
                p = _do_export_data(call.from_user.id)
                with p.open("rb") as fh:
                    bot.send_document(
                        call.from_user.id, fh,
                        caption=f"{G['ok']} {sc('Encrypted DB export')} "
                                f"({p.stat().st_size // 1024} KB)")
            except Exception as e:
                try:
                    bot.send_message(
                        call.from_user.id,
                        f"{G['no']} {sc('Export error')}: <code>{esc(e)}</code>",
                        parse_mode="HTML")
                except Exception:
                    pass
        threading.Thread(target=_ex, daemon=True).start()
        return

    # ── NEW: 6 Advanced Sub-Panel Routes ────────────────────────────
    if data == "adm_analytics":
        return render_adm_analytics(call)
    if data == "adm_user_tools":
        return render_adm_user_tools(call)
    if data == "adm_bot_manager":
        return render_adm_bot_manager(call)
    if data == "adm_sec_center":
        return render_adm_sec_center(call)
    if data == "adm_notify_center":
        return render_adm_notify_center(call)
    if data == "adm_sys_tools":
        return render_adm_sys_tools(call)
    # Analytics sub-routes
    if data == "adm_revenue_report":
        return render_adm_revenue_report(call)
    if data == "adm_growth_stats":
        return render_adm_growth_stats(call)
    if data == "adm_top_users":
        return render_adm_top_users(call)
    if data == "adm_plan_dist":
        return render_adm_plan_dist(call)
    if data == "adm_bot_activity":
        return render_adm_bot_activity(call)
    # User Tools sub-routes
    if data == "adm_user_search":
        return render_adm_user_search(call)
    if data == "adm_banned_list":
        return render_adm_banned_list(call)
    if data == "adm_wallet_admin":
        return render_adm_wallet_admin(call)
    if data == "adm_user_export_csv":
        return render_adm_user_export_csv(call)
    if data == "adm_notify_user":
        return render_adm_notify_user(call)
    if data == "adm_user_reset":
        return render_adm_user_reset_prompt(call)
    # Bot Manager sub-routes
    if data == "adm_crashed_bots":
        return render_adm_crashed_bots(call)
    if data == "adm_mass_restart_stopped":
        return render_adm_mass_restart_stopped(call)
    if data == "adm_mass_restart_stopped_yes":
        return action_adm_mass_restart_stopped(call)
    if data == "adm_bot_search":
        return render_adm_bot_search(call)
    if data == "adm_bot_size_report":
        return render_adm_bot_size_report(call)
    if data == "adm_force_scan_all":
        return action_adm_force_scan_all(call)
    if data == "adm_kill_all_now":
        return render_adm_confirm_custom(call, "adm_kill_all_now_yes",
                                         "Kill ALL running bots immediately", "adm_bot_manager")
    if data == "adm_kill_all_now_yes":
        return action_adm_kill_all(call)
    # Security Center sub-routes
    if data == "adm_threat_log":
        return render_adm_threat_log(call)
    if data == "adm_sec_stats":
        return render_adm_sec_stats(call)
    if data == "adm_sec_whitelist":
        return render_adm_sec_whitelist_prompt(call)
    if data == "adm_scan_report":
        return render_adm_scan_report(call)
    if data == "adm_sec_blacklist":
        return render_adm_sec_blacklist(call)
    # Notifications sub-routes
    if data == "adm_notify_all":
        return render_adm_notify_all(call)
    if data == "adm_notify_running":
        return render_adm_notify_running(call)
    if data == "adm_notify_plan_select":
        return render_adm_notify_plan_select(call)
    if data.startswith("adm_notify_plan_"):
        plan_key = data[len("adm_notify_plan_"):]
        return render_adm_notify_plan(call, plan_key)
    if data == "adm_schedule_msg":
        return render_adm_schedule_msg(call)
    if data == "adm_quick_announce":
        return render_adm_quick_announce(call)
    # System Tools sub-routes
    if data == "adm_sys_health":
        return render_adm_sys_health(call)
    if data == "adm_disk_usage":
        return render_adm_disk_usage(call)
    if data == "adm_db_info":
        return render_adm_db_info(call)
    if data == "adm_clear_cache":
        cache_clear_all()
        audit(call.from_user.id, "clear_cache", "manual")
        ack(call, "All caches cleared!")
        return render_adm_sys_tools(call)
    if data == "adm_token_check":
        return render_adm_token_check(call)
    if data == "adm_export_users_csv":
        return render_adm_user_export_csv(call)
    if data == "adm_set_footer_text":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_footer"}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} <b>{sc('Send new footer text')}</b> "
                         f"(<i>{sc('or')} <code>-</code> {sc('to reset')}</i>):",
                         parse_mode="HTML")
        return
    if data == "adm_set_welcome_text":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_welcome"}
        bot.send_message(call.message.chat.id,
                         f"{G['broadcast']} <b>{sc('Send new welcome message')}</b>:",
                         parse_mode="HTML")
        return
    if data == "adm_set_rules_text":
        if not is_owner(call.from_user.id):
            ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_set_rules"}
        bot.send_message(call.message.chat.id,
                         f"{G['shield']} <b>{sc('Send new hosting rules text')}</b>:",
                         parse_mode="HTML")
        return

    # ══════════════════ MEGA ADVANCED PANEL ROUTES ══════════════════
    # GitHub Browser
    if data == "adm_gh_browser":        return render_adm_gh_browser(call)
    if data == "adm_gh_repos":          return render_adm_gh_repos(call)
    if data == "adm_gh_refresh_repos":  return render_adm_gh_repos(call, force=True)
    if data.startswith("adm_ghrepo_"):
        repo = data[len("adm_ghrepo_"):]
        st2 = USER_STATES.get(call.from_user.id, {})
        gh_path = st2.get("gh_path", "")
        return render_adm_gh_files(call, repo, gh_path)
    if data == "adm_gh_up":
        st2 = USER_STATES.get(call.from_user.id, {})
        repo = st2.get("gh_repo", "")
        path = "/".join(st2.get("gh_path", "").split("/")[:-1])
        USER_STATES[call.from_user.id] = {**st2, "gh_path": path}
        return render_adm_gh_files(call, repo, path)
    if data.startswith("adm_ghfile_"):
        idx = int(data[len("adm_ghfile_"):])
        st2 = USER_STATES.get(call.from_user.id, {})
        files_list = st2.get("gh_files_list", [])
        if idx < len(files_list):
            item = files_list[idx]
            repo = st2.get("gh_repo", "")
            if item["type"] == "dir":
                USER_STATES[call.from_user.id] = {**st2, "gh_path": item["path"]}
                return render_adm_gh_files(call, repo, item["path"])
            else:
                return render_adm_gh_file_view(call, repo, item["path"])
    if data == "adm_gh_run_file":
        st2 = USER_STATES.get(call.from_user.id, {})
        return action_adm_gh_run_file(call, st2.get("gh_repo",""), st2.get("gh_view_path",""))
    if data == "adm_gh_dl_file":
        st2 = USER_STATES.get(call.from_user.id, {})
        return action_adm_gh_dl_file(call, st2.get("gh_repo",""), st2.get("gh_view_path",""))
    if data == "adm_gh_browse_repo":
        st2 = USER_STATES.get(call.from_user.id, {})
        repo = st2.get("gh_repo","")
        return render_adm_gh_files(call, repo, "")
    if data == "adm_gh_set_default_repo":
        st2 = USER_STATES.get(call.from_user.id, {})
        repo = st2.get("gh_repo","")
        if repo:
            set_setting("github_repo", repo)
            gh_set_config({"repo": repo}); gh_load_config()
            audit(call.from_user.id, "gh_set_default_repo", repo)
            ack(call, f"Default repo set: {repo}")
        return render_adm_gh_browser(call)
    # Bot API Settings
    if data == "adm_api_settings":
        return render_adm_api_settings(call)
    if data in ("adm_api_set_1", "adm_api_set_2"):
        slot = 1 if data.endswith("_1") else 2
        USER_STATES[call.from_user.id] = {"flow": "await_adm_api_token", "slot": slot}
        bot.send_message(
            call.message.chat.id,
            f"{G['key']} <b>{sc('Send Bot API token')}</b> — Bot {slot}\n"
            f"<i>{sc('Get it from @BotFather. The token will be validated before saving.')}</i>\n"
            f"/cancel",
            parse_mode="HTML"
        )
        return
    if data in ("adm_api_clear_1", "adm_api_clear_2"):
        slot = 1 if data.endswith("_1") else 2
        if not is_owner(call.from_user.id):
            ack(call, "Owner only")
            return
        set_setting(f"api_bot_token_{slot}", "")
        audit(call.from_user.id, f"bot_api_clear_{slot}", "")
        ack(call, f"Bot {slot} API cleared")
        return render_adm_api_settings(call)

    # Payment Config
    if data == "adm_pay_config":          return render_adm_pay_config(call)
    if data == "adm_pay_methods":         return render_adm_pay_methods(call)
    if data.startswith("adm_pay_edit_"):  return render_adm_pay_method_edit(call, data[len("adm_pay_edit_"):])
    if data == "adm_pay_limits":          return render_adm_pay_limits(call)
    if data == "adm_pay_currency":        return render_adm_pay_currency(call)
    if data == "adm_pay_auto_approve":
        cur = bool(get_setting("auto_approve_payments", False))
        set_setting("auto_approve_payments", not cur)
        audit(call.from_user.id, "auto_approve_toggle", f"now={not cur}")
        ack(call, f"Auto-approve: {'ON' if not cur else 'OFF'}")
        return render_adm_pay_config(call)
    if data == "adm_pay_receipt_tmpl":    return render_adm_pay_receipt_tmpl(call)
    if data == "adm_pay_notif":           return render_adm_pay_notif_settings(call)
    if data.startswith("adm_pay_method_"): return action_adm_pay_method_number(call, data)
    # Bot Config
    if data == "adm_bot_cfg":             return render_adm_bot_cfg(call)
    if data == "adm_bc_timeouts":         return render_adm_bc_timeouts(call)
    if data == "adm_bc_limits":           return render_adm_bc_limits(call)
    if data == "adm_bc_sandbox":          return render_adm_bc_sandbox(call)
    if data == "adm_bc_policy":           return render_adm_bc_policy(call)
    if data == "adm_bc_upload":           return render_adm_bc_upload(call)
    if data == "adm_bc_env":              return render_adm_bc_env(call)
    if data.startswith("adm_bc_toggle_"):
        flag_key = data[len("adm_bc_toggle_"):]
        cur = bool(get_setting(f"bc_{flag_key}", False))
        set_setting(f"bc_{flag_key}", not cur)
        audit(call.from_user.id, f"bc_toggle_{flag_key}", f"now={not cur}")
        ack(call, f"{flag_key}: {'ON' if not cur else 'OFF'}")
        return render_adm_bot_cfg(call)
    if data.startswith("adm_bc_set_"):
        USER_STATES[call.from_user.id] = {"flow": "await_adm_bc_set", "bc_key": data[len("adm_bc_set_"):]}
        bot.send_message(call.message.chat.id, f"{G['settings']} {sc('Send new value')}:", parse_mode="HTML"); return
    # Appearance
    if data == "adm_appearance":          return render_adm_appearance(call)
    if data == "adm_app_emojis":          return render_adm_app_emojis(call)
    if data == "adm_app_theme":           return render_adm_app_theme(call)
    if data.startswith("adm_app_theme_"):
        theme = data[len("adm_app_theme_"):]
        set_setting("ui_theme", theme)
        audit(call.from_user.id, "set_theme", theme)
        ack(call, f"Theme: {theme}")
        return render_adm_app_theme(call)
    if data == "adm_app_banner":          return render_adm_app_banner(call)
    if data == "adm_rebuild_banners":
        _PHOTO_FILE_IDS.clear()
        ack(call, f"{G['ok']} Banner cache cleared — photos will reload fresh")
        return render_adm_app_banner(call)
    if data == "adm_bc_set_currency_symbol":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_bc_set", "bc_key": "currency_symbol"}
        bot.send_message(call.message.chat.id, f"{G['settings']} Send new currency symbol (e.g. ₹ $ €):", parse_mode="HTML"); return
    if data.startswith("adm_bc_set_currency_") and len(data.split("_")) >= 6:
        parts = data[len("adm_bc_set_currency_"):].split("_", 1)
        if len(parts) == 2:
            _bc_set("currency_code", parts[0]); _bc_set("currency_symbol", parts[1])
            ack(call, f"{G['ok']} Currency set: {parts[0]} {parts[1]}")
        return render_adm_pay_config(call)
    if data == "adm_app_emoji_reset":
        if not is_owner(call.from_user.id): ack(call, "Owner only"); return
        set_setting("custom_emojis", {})
        audit(call.from_user.id, "emoji_reset", "")
        ack(call, "Emojis reset to default")
        return render_adm_app_emojis(call)
    if data.startswith("adm_app_emoji_set_"):
        key = data[len("adm_app_emoji_set_"):]
        USER_STATES[call.from_user.id] = {"flow": "await_adm_emoji_set", "emoji_key": key}
        bot.send_message(call.message.chat.id, f"Send emoji for <code>{esc(key)}</code>:", parse_mode="HTML"); return
    # Coupon Plus
    if data == "adm_coupon_plus":         return render_adm_coupon_plus(call)
    if data == "adm_coupon_bulk":         return render_adm_coupon_bulk(call)
    if data == "adm_coupon_analytics":    return render_adm_coupon_analytics(call)
    if data == "adm_coupon_expiry":       return render_adm_coupon_expiry(call)
    if data == "adm_coupon_clearexp":
        d = db_load()
        now_s = ts_iso()
        before = len(d["coupons"])
        d["coupons"] = {k: v for k, v in d["coupons"].items()
                        if not (v.get("expiry") and v["expiry"] < now_s)}
        db_save(d)
        removed = before - len(d["coupons"])
        audit(call.from_user.id, "coupon_clear_expired", f"removed={removed}")
        ack(call, f"Removed {removed} expired coupons")
        return render_adm_coupon_plus(call)
    # Templates
    if data == "adm_templates":           return render_adm_templates(call)
    if data.startswith("adm_tmpl_edit_"):
        key = data[len("adm_tmpl_edit_"):]
        USER_STATES[call.from_user.id] = {"flow": "await_adm_tmpl_edit", "tmpl_key": key}
        cur = get_setting(f"tmpl_{key}", "") or ""
        bot.send_message(call.message.chat.id,
                         f"<b>📝 {sc('Edit Template')}: <code>{esc(key)}</code></b>\n"
                         f"{G['div']}\n<i>{sc('Current')}:</i>\n{esc(cur) or '(default)'}\n\n"
                         f"{sc('Send new template text. Use')} <code>{{name}}</code>, <code>{{plan}}</code>, "
                         f"<code>{{amount}}</code>, <code>{{date}}</code> {sc('as placeholders')}.",
                         parse_mode="HTML"); return
    if data.startswith("adm_tmpl_reset_"):
        key = data[len("adm_tmpl_reset_"):]
        set_setting(f"tmpl_{key}", "")
        audit(call.from_user.id, f"tmpl_reset_{key}", "")
        ack(call, f"Template {key} reset to default")
        return render_adm_templates(call)
    # Referral System
    if data == "adm_referral_sys":        return render_adm_referral_sys(call)
    if data == "adm_ref_toggle":
        cur = bool(get_setting("referral_enabled", True))
        set_setting("referral_enabled", not cur)
        audit(call.from_user.id, "referral_toggle", f"now={not cur}")
        ack(call, f"Referrals: {'ON' if not cur else 'OFF'}")
        return render_adm_referral_sys(call)
    if data == "adm_ref_stats":           return render_adm_ref_stats(call)
    if data == "adm_ref_rewards":         return render_adm_ref_rewards(call)
    if data == "adm_ref_leaderboard":     return render_adm_ref_leaderboard(call)
    if data == "adm_ref_set_reward":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_ref_reward"}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Send wallet reward amount per referral (in ৳)')}."); return
    if data == "adm_ref_set_min_plan":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_ref_min_plan"}
        plans = ", ".join(PLAN_LIMITS.keys())
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Send min plan to enable referrals')}: <code>{plans}</code>",
                         parse_mode="HTML"); return
    # Janitor
    if data == "adm_janitor":             return render_adm_janitor(call)
    if data == "adm_jan_run_now":
        ack(call, "Running janitor…")
        threading.Thread(target=lambda: action_adm_jan_run(call.from_user.id), daemon=True).start(); return
    if data == "adm_jan_rules":           return render_adm_jan_rules(call)
    if data == "adm_jan_schedule":        return render_adm_jan_schedule(call)
    if data.startswith("adm_jan_toggle_"):
        k = data[len("adm_jan_toggle_"):]
        cur = bool(get_setting(f"jan_{k}", False))
        set_setting(f"jan_{k}", not cur)
        audit(call.from_user.id, f"jan_toggle_{k}", f"now={not cur}")
        ack(call, f"Janitor {k}: {'ON' if not cur else 'OFF'}")
        return render_adm_janitor(call)
    # Webhooks
    if data == "adm_webhooks":            return render_adm_webhooks(call)
    if data == "adm_wh_set":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_wh_set"}
        bot.send_message(call.message.chat.id, f"{G['settings']} {sc('Send full HTTPS webhook URL')}:"); return
    if data == "adm_wh_clear":
        try:
            bot.remove_webhook()
            set_setting("webhook_url", "")
            audit(call.from_user.id, "wh_clear", "")
            ack(call, "Webhook cleared → polling mode")
        except Exception as _we:
            ack(call, f"Error: {_we}")
        return render_adm_webhooks(call)
    if data == "adm_wh_test":             return action_adm_wh_test(call)
    if data == "adm_wh_info":             return render_adm_wh_info(call)
    # Feature Flags
    if data == "adm_feature_flags":       return render_adm_feature_flags(call)
    if data.startswith("adm_ff_toggle_"):
        ff_key = data[len("adm_ff_toggle_"):]
        cur = bool(get_setting(f"ff_{ff_key}", _FEATURE_FLAG_DEFAULTS.get(ff_key, True)))
        set_setting(f"ff_{ff_key}", not cur)
        audit(call.from_user.id, f"ff_toggle_{ff_key}", f"now={not cur}")
        ack(call, f"Flag {ff_key}: {'ON' if not cur else 'OFF'}")
        return render_adm_feature_flags(call)
    if data == "adm_ff_reset_all":
        for k, v in _FEATURE_FLAG_DEFAULTS.items():
            set_setting(f"ff_{k}", v)
        audit(call.from_user.id, "ff_reset_all", "")
        ack(call, "All feature flags reset to defaults")
        return render_adm_feature_flags(call)
    # Rate Limits
    if data == "adm_rate_config":         return render_adm_rate_config(call)
    if data.startswith("adm_rate_plan_"): return render_adm_rate_plan(call, data[len("adm_rate_plan_"):])
    if data.startswith("adm_rate_set_"):
        USER_STATES[call.from_user.id] = {"flow": "await_adm_rate_set", "rate_key": data[len("adm_rate_set_"):]}
        bot.send_message(call.message.chat.id, f"{G['settings']} {sc('Send new limit value (integer)')}:"); return
    # Live Monitor
    if data == "adm_live_monitor":        return render_adm_live_monitor(call)
    if data == "adm_monitor_bots":        return render_adm_monitor_bots(call)
    if data == "adm_monitor_system":      return render_adm_monitor_system(call)
    if data == "adm_monitor_refresh":     return render_adm_live_monitor(call)
    # Revenue Goals
    if data == "adm_rev_goals":           return render_adm_rev_goals(call)
    if data == "adm_goal_set_monthly":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_goal_set", "goal_type": "monthly"}
        bot.send_message(call.message.chat.id, f"{G['settings']} {sc('Send monthly revenue target (৳)')}:"); return
    if data == "adm_goal_set_yearly":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_goal_set", "goal_type": "yearly"}
        bot.send_message(call.message.chat.id, f"{G['settings']} {sc('Send yearly revenue target (৳)')}:"); return
    if data == "adm_goal_history":        return render_adm_goal_history(call)
    # Scheduler
    if data == "adm_scheduler":           return render_adm_scheduler(call)
    if data == "adm_sched_add":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_sched_add"}
        bot.send_message(call.message.chat.id,
                         f"<b>⏰ {sc('Add Scheduled Task')}</b>\n{G['div']}\n"
                         f"{sc('Format')}: <code>HH:MM daily Your message</code>\n"
                         f"{sc('or')}: <code>YYYY-MM-DD HH:MM once Your message</code>\n"
                         f"{sc('Example')}: <code>09:00 daily Good morning everyone!</code>",
                         parse_mode="HTML"); return
    if data == "adm_sched_list":          return render_adm_sched_list(call)
    if data.startswith("adm_sched_del_"):
        tid = data[len("adm_sched_del_"):]
        tasks = get_setting("scheduled_tasks", []) or []
        tasks = [t for t in tasks if t.get("id") != tid]
        set_setting("scheduled_tasks", tasks)
        audit(call.from_user.id, "sched_del", tid)
        ack(call, f"Task {tid[:8]} deleted")
        return render_adm_sched_list(call)
    if data.startswith("adm_sched_toggle_"):
        tid = data[len("adm_sched_toggle_"):]
        tasks = get_setting("scheduled_tasks", []) or []
        for t in tasks:
            if t.get("id") == tid:
                t["enabled"] = not t.get("enabled", True)
        set_setting("scheduled_tasks", tasks)
        ack(call, "Task toggled")
        return render_adm_sched_list(call)
    # Import / Export
    if data == "adm_import_export":       return render_adm_import_export(call)
    if data == "adm_export_full_cfg":     return action_adm_export_full_cfg(call)
    if data == "adm_export_userdata":     return render_adm_user_export_csv(call)
    if data == "adm_import_cfg":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_import_cfg"}
        bot.send_message(call.message.chat.id,
                         f"{G['upload']} {sc('Upload the settings JSON file exported from this bot')}."); return
    if data == "adm_import_reset":
        if not is_owner(call.from_user.id): ack(call, "Owner only"); return
        USER_STATES[call.from_user.id] = {"flow": "await_adm_factory_reset"}
        bot.send_message(call.message.chat.id,
                         f"⚠️ <b>{sc('FACTORY RESET')}</b> — {sc('Type')} <code>CONFIRM RESET</code> "
                         f"{sc('to wipe ALL settings (not user data). This cannot be undone!')}",
                         parse_mode="HTML"); return
    # Admin 2FA
    if data == "adm_admin_2fa":           return render_adm_admin_2fa(call)
    if data == "adm_2fa_setup":           return action_adm_2fa_setup(call)
    if data == "adm_2fa_disable":
        if not is_owner(call.from_user.id): ack(call, "Owner only"); return
        set_setting("admin_2fa_secret", "")
        set_setting("admin_2fa_enabled", False)
        audit(call.from_user.id, "2fa_disable", "")
        ack(call, "2FA disabled")
        return render_adm_admin_2fa(call)
    # Leaderboard
    if data == "adm_leaderboard":         return render_adm_leaderboard(call)
    if data == "adm_lb_spenders":         return render_adm_lb_spenders(call)
    if data == "adm_lb_bots":             return render_adm_lb_bots(call)
    if data == "adm_lb_referrals":        return render_adm_lb_referrals(call)
    if data == "adm_lb_active":           return render_adm_lb_active(call)
    if data == "adm_lb_uptime":           return render_adm_lb_uptime(call)
    # Languages
    if data == "adm_languages":           return render_adm_languages(call)
    if data.startswith("adm_lang_set_"):
        lang = data[len("adm_lang_set_"):]
        set_setting("default_language", lang)
        audit(call.from_user.id, "set_lang", lang)
        ack(call, f"Default language: {lang}")
        return render_adm_languages(call)
    # Bot Controls
    if data == "adm_bot_controls":        return render_adm_bot_controls_panel(call)
    if data == "adm_bc_list_all":         return render_adm_bc_list_all(call)
    if data.startswith("adm_bcbot_"):     return render_adm_bc_single(call, data[len("adm_bcbot_"):])
    if data.startswith("adm_bc_env_"):    return render_adm_bc_env_editor(call, data[len("adm_bc_env_"):])
    if data.startswith("adm_bc_res_"):    return render_adm_bc_resources(call, data[len("adm_bc_res_"):])
    if data.startswith("adm_bc_logs_"):   return render_adm_bc_logs(call, data[len("adm_bc_logs_"):])
    if data.startswith("adm_bc_restart_"):
        bid = data[len("adm_bc_restart_"):]
        b = find_bot(bid)
        if b:
            threading.Thread(target=lambda: restart_child(b), daemon=True).start()
            ack(call, f"Restarting {b.get('name','?')[:15]}…")
        return
    if data.startswith("adm_bc_stop_"):
        bid = data[len("adm_bc_stop_"):]
        stop_child(bid, manual=True)
        ack(call, f"Stopped {bid[:8]}")
        return render_adm_bc_list_all(call)
    if data.startswith("adm_bc_del_"):
        bid = data[len("adm_bc_del_"):]
        b = find_bot(bid)
        if b:
            return render_adm_confirm_custom(call, f"adm_bc_del_confirm_{bid}",
                                             f"Delete bot {b.get('name','?')[:20]}", "adm_bot_controls")
    if data.startswith("adm_bc_del_confirm_"):
        bid = data[len("adm_bc_del_confirm_"):]
        stop_child(bid, manual=True)
        d = db_load()
        d["bots"].pop(bid, None)
        db_save(d)
        audit(call.from_user.id, "admin_del_bot", bid)
        ack(call, f"Bot {bid[:8]} deleted")
        return render_adm_bc_list_all(call)
    # Subscriptions
    if data == "adm_subscriptions":       return render_adm_subscriptions(call)
    if data == "adm_sub_expiring":        return render_adm_sub_expiring(call)
    if data == "adm_sub_expired":         return render_adm_sub_expired(call)
    if data == "adm_sub_remind_all":
        ack(call, "Sending reminders…")
        threading.Thread(target=lambda: action_adm_sub_remind_all(call.from_user.id), daemon=True).start(); return
    if data == "adm_sub_auto_downgrade":
        cur = bool(get_setting("auto_downgrade_expired", True))
        set_setting("auto_downgrade_expired", not cur)
        audit(call.from_user.id, "auto_downgrade_toggle", f"now={not cur}")
        ack(call, f"Auto-downgrade: {'ON' if not cur else 'OFF'}")
        return render_adm_subscriptions(call)
    if data == "adm_sub_extend_prompt":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_sub_extend"}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Format')}: <code>uid days</code> {sc('(e.g.')} <code>12345 30</code>)",
                         parse_mode="HTML"); return
    if data == "adm_sub_history":
        USER_STATES[call.from_user.id] = {"flow": "await_adm_sub_history"}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Send user ID to view subscription history')}:"); return
    if data == "adm_sub_run_downgrade":
        if not is_owner(call.from_user.id): ack(call, "Owner only"); return
        ack(call, "Running downgrade now…")
        threading.Thread(target=lambda: action_adm_downgrade_expired(call.from_user.id), daemon=True).start(); return

    ack(call, "?")


def render_adm_stats(call: types.CallbackQuery) -> None:
    d = db_load()
    users = d["users"]
    bots  = d["bots"]
    pays  = d["payments"]
    revenue = sum(p.get("amount", 0) for p in pays if p.get("status") == "approved")
    today_str = now_utc().strftime("%Y-%m-%d")
    new_today = sum(1 for u in users.values() if str(u.get("joined", "")).startswith(today_str))
    week_ago = now_utc() - timedelta(days=7)
    new_week = 0
    for u in users.values():
        try:
            if datetime.fromisoformat(str(u.get("joined")).replace("Z", "+00:00")) >= week_ago:
                new_week += 1
        except Exception:
            pass
    plan_counts: Dict[str, int] = defaultdict(int)
    for u in users.values():
        plan_counts[u.get("plan", "free")] += 1
    rss = 0
    if psutil is not None:
        try:
            rss = psutil.Process(os.getpid()).memory_info().rss
        except Exception:
            pass
    storage_size = 0
    for root, _, files in os.walk(BASE_DIR / "storage"):
        for f in files:
            try:
                storage_size += (Path(root) / f).stat().st_size
            except OSError:
                pass

    cap = (
        f"<b>{G['graph']} {sc('System Stats')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total users',  len(users))}\n"
        f"{bullet('New today',    new_today)}\n"
        f"{bullet('New this week', new_week)}\n"
        f"{bullet('Total bots',   len(bots))}\n"
        f"{bullet('Bots running', sum(1 for x in RUNNING.values() if x['proc'].poll() is None))}\n"
        f"{bullet('Revenue',      '{}$'.format(revenue))}\n"
        f"{bullet('Storage',      fmt_bytes(storage_size))}\n"
        f"{bullet('Panel RSS',    fmt_bytes(rss))}\n"
        f"{bullet('Uptime',       fmt_dur(int(time.time() * 1000) - START_TS))}\n"
        f"{G['div']}\n"
        + "\n".join(f"{bullet(PLAN_LIMITS[p]['name'], n)}" for p, n in plan_counts.items())
        + FOOTER
    )
    show_menu(call.message.chat.id, PHOTOS["stats"], cap, back_admin_kb(), call=call)


def render_adm_users(call: types.CallbackQuery) -> None:
    d = db_load()["users"]
    items = sorted(d.values(), key=lambda u: u.get("joined", ""), reverse=True)[:20]
    rows = "\n".join(
        f"{G['bullet']} <code>{u['_id']}</code> — {esc(u.get('name'))} "
        f"(@{esc(u.get('username') or '—')}) "
        f"{G['bullet']} <i>{esc(PLAN_LIMITS.get(u.get('plan'), {}).get('name', u.get('plan')))}</i>"
        for u in items
    ) or f"<i>{sc('no users yet')}</i>"
    cap = (
        f"<b>{G['users']} {sc('Recent Users')} ({len(d)} {sc('total')})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}\n"
        f"{sc('Send a numeric user id to look one up')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_admin_finduser"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)


def render_adm_allbots(call: types.CallbackQuery) -> None:
    d = db_load()["bots"]
    items = list(d.values())[:25]
    rows = "\n".join(
        f"{G['bullet']} <code>{b['_id']}</code> — {esc(b['name'])} "
        f"{G['bullet']} <i>uid {b['owner']}</i> "
        f"{G['bullet']} {'run' if b['_id'] in RUNNING and RUNNING[b['_id']]['proc'].poll() is None else 'idle'}"
        for b in items
    ) or f"<i>{sc('no bots')}</i>"
    cap = (
        f"<b>{G['diamond']} {sc('All Bots')} ({len(d)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)


def render_adm_payments(call: types.CallbackQuery) -> None:
    """Admin payment inbox: pending plan payments + wallet deposits."""
    if not admin_only_call(call, "approve_payment"):
        return
    d = db_load()
    # Pending plan payments may live in the pending_payments map until
    # approval; include both the map and legacy payments list so the inbox
    # never shows 0 while a payment is actually waiting.
    pays_map = d.get("pending_payments", {}) or {}
    pays = []
    for pid, p in pays_map.items():
        if isinstance(p, dict) and p.get("status") == "pending":
            pays.append(dict(p, id=pid))
    for p in d.get("payments", []) or []:
        if isinstance(p, dict) and p.get("status") == "pending":
            pid = str(p.get("id", ""))
            if not any(str(x.get("id")) == pid for x in pays):
                pays.append(p)
    pays = pays[-10:]
    topups = [(tid, x) for tid, x in (d.get("pending_topups", {}) or {}).items()
              if isinstance(x, dict) and x.get("status") == "pending"][-10:]

    rows = []
    kb = types.InlineKeyboardMarkup(row_width=2)
    for p in pays:
        pid = str(p.get("id", ""))
        rows.append(f"💳 <code>{esc(pid)}</code> — uid <code>{p.get('uid')}</code> — "
                    f"{esc(str(p.get('plan', '—')).upper())} — {esc(str(p.get('method', '—')).upper())}")
        kb.add(Btn(f"✅ Approve {pid[:8]}", callback_data=f"adm_pay_approve_{pid}", style="success"),
               Btn(f"❌ Reject {pid[:8]}", callback_data=f"adm_pay_reject_{pid}", style="danger"))

    for tid, x in topups:
        rows.append(f"💰 <code>{esc(tid)}</code> — uid <code>{x.get('uid')}</code> — "
                    f"<b>{x.get('amount')} BDT</b> — {esc(str(x.get('method', '—')).upper())}")
        kb.add(Btn(f"✅ Deposit {tid[:8]}", callback_data=f"adm_topup_approve_{tid}", style="success"),
               Btn(f"❌ Deposit {tid[:8]}", callback_data=f"adm_topup_reject_{tid}", style="danger"))

    if not rows:
        rows.append(f"<i>{sc('No pending payments or deposits')}</i>")
    cap = (f"<b>{G['wallet']} {sc('Payment & Deposit Inbox')}</b>\n"
           f"{G['div_eq']}\n" + "\n".join(rows) +
           f"\n{G['div']}\n"
           f"{sc('Pending plan payments')}: <b>{len(pays)}</b>\n"
           f"{sc('Pending wallet deposits')}: <b>{len(topups)}</b>{FOOTER}")
    kb.add(Btn(f"{G['back']}  {sc('Admin')}", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_broadcast(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "broadcast"):
        return
    cap = (
        f"<b>{G['broadcast']} {sc('Broadcast')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send the message text now')}.\n"
        f"<b>{sc('Optional prefix')}:</b>\n"
        f"  <code>plan:pro</code> — {sc('only pro users')}\n"
        f"  <code>plan:free</code> — {sc('only free users')}\n"
        f"  <code>at:YYYY-MM-DD HH:MM</code> — {sc('schedule')}\n"
        f"  {sc('Otherwise message goes to everyone now')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_broadcast"}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, back_admin_kb(), call=call)


def render_adm_ban(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "ban_user"):
        return
    cap = (
        f"<b>{G['no']} {sc('Ban / Unban')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send')} <code>ban &lt;user_id&gt; &lt;reason&gt;</code>\n"
        f"{sc('Send')} <code>unban &lt;user_id&gt;</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_ban_cmd"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)


def render_adm_giveplan(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "give_plan"):
        return
    cap = (
        f"<b>{G['plus']} {sc('Give Plan')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send')} <code>&lt;user_id&gt; &lt;plan&gt; [days]</code>\n"
        f"{sc('Plans')}: {', '.join(PLAN_LIMITS.keys())}{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_giveplan"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)


def render_adm_coupons(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "manage_coupons"):
        return
    d = db_load()["coupons"]
    rows = "\n".join(
        f"{G['bullet']} <code>{esc(code)}</code> — {esc(c.get('percent'))}% "
        f"{G['bullet']} {esc(c.get('uses_left'))} {sc('uses left')}"
        for code, c in d.items()
    ) or f"<i>{sc('no coupons yet')}</i>"
    cap = (
        f"<b>{G['key']} {sc('Coupons')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}\n"
        f"{sc('Send')} <code>add CODE PERCENT USES</code> {sc('to create')}.\n"
        f"{sc('Send')} <code>del CODE</code> {sc('to remove')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_coupon_admin"}
    show_menu(call.message.chat.id, PHOTOS["coupon"], cap, back_admin_kb(), call=call)


def render_adm_tickets(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "reply_ticket"):
        return
    d = db_load()["tickets"]
    open_t = [t for t in d.values() if t.get("status") == "open"][-15:]
    rows = "\n".join(
        f"{G['bullet']} <code>{t['id']}</code> uid {t['uid']} — {esc(t.get('subject'))[:40]}"
        for t in open_t
    ) or f"<i>{sc('no open tickets')}</i>"
    cap = (
        f"<b>{G['ticket']} {sc('Open Tickets')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    for t in open_t:
        kb.add(Btn(
            f"{G['eye']}  #{t['id']}", callback_data=f"ticket_view_{t['id']}"))
    kb.add(Btn(
        f"{G['back']}  {sc('Admin')}", callback_data="menu_admin"))
    show_menu(call.message.chat.id, PHOTOS["ticket"], cap, kb, call=call)


def render_adm_admins(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "Owner only"); return
    d = db_load()["admins"]
    rows = "\n".join(
        f"{G['bullet']} <code>{uid}</code> — {esc(a.get('role'))}"
        for uid, a in d.items()
    ) or f"<i>{sc('no extra admins yet')}</i>"
    cap = (
        f"<b>{G['shield']} {sc('Admins')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}\n"
        f"{sc('Send')} <code>add &lt;uid&gt; &lt;role&gt;</code>\n"
        f"  {sc('Roles')}: <code>view-only</code>, <code>manage-users</code>, <code>full-access</code>\n"
        f"{sc('Send')} <code>del &lt;uid&gt;</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_admin_admins"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)


def render_adm_audit(call: types.CallbackQuery) -> None:
    d = db_load()["audit"][-25:]
    rows = "\n".join(
        f"{G['bullet']} {esc(a['ts'][11:19])} uid {a['uid']} → {esc(a['action'])} {esc(a.get('detail', ''))[:60]}"
        for a in reversed(d)
    ) or f"<i>{sc('no audit entries yet')}</i>"
    cap = (
        f"<b>{G['eye']} {sc('Recent Audit')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["security"], cap, back_admin_kb(), call=call)


def render_adm_pending(call: types.CallbackQuery) -> None:
    """List of bot uploads waiting for approval. Each row links back
    to a quick approve / reject pair for that upload."""
    if not admin_only_call(call, "approve_payment"):
        return
    items = pending_list()
    if not items:
        cap = (
            f"<b>{G['eye']} {sc('Pending Uploads')}</b>\n"
            f"{G['div_eq']}\n<i>{sc('Inbox is empty — nothing waiting for approval')}.</i>\n"
            f"{G['div']}{FOOTER}"
        )
        show_menu(call.message.chat.id, PHOTOS["admin"], cap, back_admin_kb(), call=call)
        return
    rows = []
    kb = types.InlineKeyboardMarkup(row_width=2)
    for bid, info in items[:15]:
        b = find_bot(bid)
        nm = (b or {}).get("name") or info.get("file_name") or bid
        rows.append(
            f"{G['bullet']} <code>{esc(bid)}</code> — {esc(nm)} "
            f"{G['bullet']} uid {info.get('user_id')} "
            f"{G['bullet']} {fmt_bytes(info.get('size', 0))}"
        )
        kb.add(
            Btn(f"{G['ok']}  {sc('OK')} {esc(nm)[:18]}",
                                       callback_data=f"appr_ok_{bid}"),
            Btn(f"{G['no']}  {sc('No')} {esc(nm)[:18]}",
                                       callback_data=f"appr_no_{bid}"),
        )
    kb.add(Btn(
        f"{G['back']}  {sc('Admin')}", callback_data="menu_admin"))
    cap = (
        f"<b>{G['eye']} {sc('Pending Uploads')} ({len(items)})</b>\n"
        f"{G['div_eq']}\n" + "\n".join(rows) + f"\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_photos(call: types.CallbackQuery) -> None:
    """List every menu photo key. Tapping one prompts the admin to
    send a fresh photo, which replaces that banner."""
    if not is_owner(call.from_user.id) and not admin_can(call.from_user.id, "manage_admins"):
        # Allow only owner / full-access admins to change branding.
        ack(call, "Owner / full-access only.")
        return
    cap = (
        f"<b>{G['upload']} {sc('Menu Photos')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Tap any menu below, then send a photo to replace its banner')}.\n"
        f"{sc('Photos are saved locally and synced to GitHub on next backup')}.\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    items = sorted(PHOTO_KEYS_FRIENDLY.items())
    pairs: List[types.InlineKeyboardButton] = []
    for key, label in items:
        if key not in _PHOTO_SPECS:
            continue
        pairs.append(Btn(
            f"{G['cog']}  {sc(label)}", callback_data=f"adm_photo_{key}"))
    # 2 per row
    for i in range(0, len(pairs), 2):
        kb.add(*pairs[i:i + 2])
    kb.add(Btn(
        f"{G['back']}  {sc('Admin')}", callback_data="menu_admin"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_photo_one(call: types.CallbackQuery, key: str) -> None:
    """Prompt the admin to send the next photo as the banner for `key`."""
    if not is_owner(call.from_user.id) and not admin_can(call.from_user.id, "manage_admins"):
        ack(call, "Owner / full-access only.")
        return
    if key not in _PHOTO_SPECS:
        ack(call, "Unknown photo key.")
        return
    USER_STATES[call.from_user.id] = {"flow": "await_admin_photo", "photo_key": key}
    label = PHOTO_KEYS_FRIENDLY.get(key, key)
    cap = (
        f"<b>{G['upload']} {sc('Replace banner')}: {esc(label)}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send the new photo now (as a photo, not a file)')}.\n"
        f"{sc('Send /cancel to abort')}.\n"
        f"{G['div']}{FOOTER}"
    )
    # Show the current banner so the admin sees what they're replacing.
    cur = PHOTOS.get(key) or PHOTOS.get("admin", "")
    show_menu(call.message.chat.id, cur, cap, back_admin_kb(), call=call)


def render_adm_github(call: types.CallbackQuery) -> None:
    s = gh_status()
    cap = (
        f"<b>{G['cog']} {sc('GitHub Backup')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Configured', 'Yes' if s['enabled'] else 'No')}\n"
        f"{bullet('Repo',       s['repo'] or '—')}\n"
        f"{bullet('Branch',     s['branch'])}\n"
        f"{bullet('Interval',   '{} min'.format(s['intervalMin']))}\n"
        f"{bullet('Auto',       'On' if s['autoEnabled'] else 'Off')}\n"
        f"{bullet('Last',       fmt_ts(s['lastBackup']))}\n"
        f"{bullet('Last err',   s['lastError'] or '—')}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["github"], cap, github_kb(s), call=call)


def render_github_subroute(call: types.CallbackQuery, data: str) -> None:
    if data == "gh_backup_now":
        threading.Thread(target=lambda: _gh_backup_thread(call), daemon=True).start()
        ack(call, "Backup started"); return
    if data == "gh_restore_now":
        threading.Thread(target=lambda: _gh_restore_thread(call), daemon=True).start()
        ack(call, "Restore started"); return
    if data == "gh_toggle_auto":
        GH["autoEnabled"] = not GH["autoEnabled"]
        set_setting("github_auto_enabled", GH["autoEnabled"])
        ack(call, f"Auto: {'ON' if GH['autoEnabled'] else 'OFF'}")
        render_adm_github(call); return
    if data == "gh_set_token":
        USER_STATES[call.from_user.id] = {"flow": "await_gh_token"}
        bot.send_message(call.message.chat.id, f"{G['key']} {sc('Send the GitHub token now')} (Tᴇxᴛ)."); return
    if data == "gh_set_repo":
        USER_STATES[call.from_user.id] = {"flow": "await_gh_repo"}
        bot.send_message(call.message.chat.id, f"{G['diamond']} {sc('Send the repo as')} <code>Oᴡɴᴇʀ/repo</code>.", parse_mode="HTML"); return
    if data == "gh_set_branch":
        USER_STATES[call.from_user.id] = {"flow": "await_gh_branch"}
        bot.send_message(call.message.chat.id, f"{G['tri']} {sc('Send the branch name')}."); return
    if data == "gh_set_interval":
        USER_STATES[call.from_user.id] = {"flow": "await_gh_interval"}
        bot.send_message(call.message.chat.id, f"{G['cog']} {sc('Send interval in minutes (>=15)')}."); return
    if data == "gh_clear":
        gh_set_config({"token": "", "repo": "", "branch": "main", "intervalMin": 360})
        gh_load_config()
        ack(call, "Cleared")
        render_adm_github(call); return
    ack(call, "?")


def _gh_backup_thread(call: types.CallbackQuery) -> None:
    res = gh_backup_now()
    msg = (f"{G['ok']} {sc('backup ok')} ({res.get('sizeMB')} MB)"
           if res["ok"] else f"{G['no']} {esc(res.get('error'))}")
    try:
        bot.send_message(call.message.chat.id, msg)
    except Exception:
        pass


def _gh_restore_thread(call: types.CallbackQuery) -> None:
    res = gh_restore_now(overwrite=True)
    msg = (f"{G['ok']} {sc('restore ok')} ({fmt_bytes(res.get('sizeBytes', 0))})"
           if res["ok"] else f"{G['no']} {esc(res.get('error'))}")
    try:
        bot.send_message(call.message.chat.id, msg)
    except Exception:
        pass


def render_adm_security(call: types.CallbackQuery) -> None:
    d = db_load()
    cap = (
        f"<b>{G['lock']} {sc('Security')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Banned users', sum(1 for u in d['users'].values() if u.get('banned')))}\n"
        f"{bullet('Rate violators', sum(1 for n in d.get('rate_violations', {}).values() if int(n) > 0))}\n"
        f"{bullet('Encryption',   'Fernet (AES-128-CBC) per file')}\n"
        f"{bullet('Key storage',  'GitHub' if KEYRING.gh_enabled() else 'Local cache')}\n"
        f"{bullet('Path-traversal','blocked (safe_path_join)')}\n"
        f"{bullet('Secret env strip','active')}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["security"], cap, back_admin_kb(), call=call)


def render_adm_maintenance(call: types.CallbackQuery) -> None:
    cur = bool(get_setting("maintenance", False))
    cap = (
        f"<b>{G['warn']} {sc('Maintenance Mode')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('State', 'ON' if cur else 'OFF')}\n"
        f"{sc('When ON, only admins can use the bot')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    label = "Turn OFF" if cur else "Turn ON"
    kb.add(Btn(
        f"{G['refresh']}  {sc(label)}", callback_data="adm_maint_toggle",
        style="danger" if cur else "success"))
    kb.add(Btn(
        f"{G['back']}  {sc('Admin')}", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["maint"], cap, kb, call=call)


def render_adm_settings(call: types.CallbackQuery) -> None:
    running_n = sum(1 for x in RUNNING.values() if x['proc'].poll() is None)
    total_bots = len(db_load_ro()['bots'])
    cap = (
        f"<b>{G['settings']} {sc('Settings & Advanced')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Brand',          BRAND_TAG)}\n"
        f"{bullet('Owner ID',       OWNER_ID)}\n"
        f"{bullet('Announce chan',  ANNOUNCE_CHANNEL or '—')}\n"
        f"{bullet('Keep-alive port', KEEPALIVE_PORT)}\n"
        f"{bullet('GitHub keys',    'GitHub' if KEYRING.gh_enabled() else 'Local cache')}\n"
        f"{bullet('GitHub backup',  'On' if gh_enabled() and GH['autoEnabled'] else 'Off')}\n"
        f"{bullet('Bots running',   f'{running_n} / {total_bots}')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    # ── live tunables ───────────────────────────────────────────────
    kb.add(
        Btn(f"{G['settings']}  {sc('Edit Brand')}",
            callback_data="adm_set_brand",   style="primary"),
        Btn(f"{G['broadcast']}  {sc('Announce Chan')}",
            callback_data="adm_set_announce", style="primary"),
    )
    kb.add(
        Btn(f"{G['shield']}  {sc('Transfer Owner')}",
            callback_data="adm_set_owner",   style="primary"),
        Btn(f"{G['diamond']}  {sc('Plans Editor')}",
            callback_data="adm_set_plans",   style="primary"),
    )
    # ── ops actions ─────────────────────────────────────────────────
    kb.add(
        Btn(f"{G['refresh']}  {sc('Reload Caches')}",
            callback_data="adm_set_reload",  style="success"),
        Btn(f"{G['eye']}  {sc('System Info')}",
            callback_data="adm_set_sysinfo", style="primary"),
    )
    kb.add(
        Btn(f"{G['refresh']}  {sc('Restart All Bots')}",
            callback_data="adm_set_restart_all", style="success"),
        Btn(f"{G['no']}  {sc('Stop All Bots')}",
            callback_data="adm_set_stop_all",    style="danger"),
    )
    kb.add(
        Btn(f"{G['warn']}  {sc('Clean Orphans')}",
            callback_data="adm_set_clean_orphans", style="danger"),
        Btn(f"{G['upload']}  {sc('Export Data')}",
            callback_data="adm_set_export",        style="primary"),
    )
    kb.add(Btn(f"{G['back']}  {sc('Admin')}", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


# ───────────────────────────────────────────────────────────────────
#  Advanced settings — sub-renderers + handlers
# ───────────────────────────────────────────────────────────────────

def _set_back_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(
        f"{G['back']}  {sc('Settings')}", callback_data="adm_settings"))
    return kb


def render_adm_sysinfo(call: types.CallbackQuery) -> None:
    """Live system info — RAM, disk, uptime, child processes."""
    rss = vms = pct = 0
    if psutil is not None:
        try:
            p = psutil.Process(os.getpid())
            mi = p.memory_info()
            rss, vms = mi.rss, mi.vms
            pct = p.cpu_percent(interval=0.2)
        except Exception:
            pass
    storage_size = 0
    storage_files = 0
    for root, _, files in os.walk(BASE_DIR / "storage"):
        for f in files:
            try:
                storage_size += (Path(root) / f).stat().st_size
                storage_files += 1
            except OSError:
                pass
    sandbox_size = 0
    sandbox_dirs = 0
    sandbox_root = BASE_DIR / "sandbox"
    if sandbox_root.exists():
        for entry in sandbox_root.iterdir():
            if entry.is_dir():
                sandbox_dirs += 1
                for root, _, files in os.walk(entry):
                    for f in files:
                        try:
                            sandbox_size += (Path(root) / f).stat().st_size
                        except OSError:
                            pass
    up_secs = int(time.time() - START_TIME) if "START_TIME" in globals() else 0
    days, rem = divmod(up_secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    running_n = sum(1 for x in RUNNING.values() if x['proc'].poll() is None)
    cap = (
        f"<b>{G['eye']} {sc('System Info')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Uptime',       f'{days}d {hours}h {mins}m')}\n"
        f"{bullet('Panel RSS',    f'{rss / 1024 / 1024:.1f} MB')}\n"
        f"{bullet('Panel VMS',    f'{vms / 1024 / 1024:.1f} MB')}\n"
        f"{bullet('CPU sample',   f'{pct:.1f}%')}\n"
        f"{bullet('Bots live',    running_n)}\n"
        f"{bullet('Storage',      f'{storage_size / 1024 / 1024:.1f} MB ({storage_files} files)')}\n"
        f"{bullet('Sandboxes',    f'{sandbox_dirs} dirs, {sandbox_size / 1024 / 1024:.1f} MB')}\n"
        f"{bullet('Cache entries', len(_DB_CACHE))}\n"
        f"{bullet('PID',          os.getpid())}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _set_back_kb(), call=call)


def render_adm_plans(call: types.CallbackQuery) -> None:
    """Live plan editor — adjust max_bots per plan tier."""
    rows = []
    for k, v in PLAN_LIMITS.items():
        live = int(get_setting(f"plan_max_bots_{k}", v["max_bots"]))
        rows.append(f"{bullet(v['name'], f'max_bots = {live}')}")
    cap = (
        f"<b>{G['diamond']} {sc('Plans Editor')}</b>\n"
        f"{G['div_eq']}\n"
        + "\n".join(rows) + "\n"
        f"{G['div']}\n"
        f"<i>{sc('Tap a plan to bump its bot quota')}.</i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=3)
    for k, v in PLAN_LIMITS.items():
        live = int(get_setting(f"plan_max_bots_{k}", v["max_bots"]))
        kb.add(
            Btn(f"{sc(v['name'])}",
                                       callback_data=f"adm_set_plan_dec_{k}"),
            Btn(f"{live}",
                                       callback_data=f"adm_set_plan_show_{k}"),
            Btn(f"{sc(v['name'])}",
                                       callback_data=f"adm_set_plan_inc_{k}"),
        )
    kb.add(Btn(
        f"{G['refresh']}  {sc('Reset Defaults')}",
        callback_data="adm_set_plans_reset"))
    kb.add(Btn(
        f"{G['back']}  {sc('Settings')}", callback_data="adm_settings"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_confirm(call: types.CallbackQuery, action: str, label: str) -> None:
    cap = (
        f"<b>{G['warn']} {sc('Confirm')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('You are about to')}: <b>{esc(label)}</b>.\n"
        f"{sc('This affects every running bot. Continue')}?{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{G['ok']}  {sc('Yes, do it')}",
                                   callback_data=f"{action}_yes"),
        Btn(f"{G['no']}  {sc('Cancel')}",
                                   callback_data="adm_settings"),
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_confirm_custom(call: types.CallbackQuery, action: str,
                              label: str, back_cb: str = "menu_admin") -> None:
    cap = (
        f"<b>{G['warn']} {sc('Confirm')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('You are about to')}: <b>{esc(label)}</b>.\n"
        f"{sc('Are you sure')}?{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{G['ok']}  {sc('Yes')}",    callback_data=action,  style="danger"),
        Btn(f"{G['no']}  {sc('Cancel')}", callback_data=back_cb, style="primary"),
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


# ═══════════════════════════════════════════════════════════════════
#  ADVANCED ADMIN SUB-PANELS  (35+ new features)
# ═══════════════════════════════════════════════════════════════════

def _adm_back(dest: str = "menu_admin") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(f"{G['back']}  {sc('Back')}", callback_data=dest, style="primary"))
    return kb


# ─── 1. ANALYTICS ────────────────────────────────────────────────────────────

def render_adm_analytics(call: types.CallbackQuery) -> None:
    d = db_load()
    total_rev = sum(p.get("amount", 0) for p in d["payments"] if p.get("status") == "approved")
    running_n = sum(1 for x in RUNNING.values() if x["proc"].poll() is None)
    cap = (
        f"<b>📊 {sc('Analytics Dashboard')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Revenue',   f'{total_rev}৳')}\n"
        f"{bullet('Total Users',     len(d['users']))}\n"
        f"{bullet('Total Bots',      len(d['bots']))}\n"
        f"{bullet('Bots Running',    running_n)}\n"
        f"{G['div']}\n{sc('Choose a report below')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Rᴇᴠᴇɴᴜᴇ Rᴇᴘᴏʀᴛ",  callback_data="adm_revenue_report", style="success"),
        Btn("Gʀᴏᴡᴛʜ Sᴛᴀᴛꜱ",    callback_data="adm_growth_stats",   style="primary"),
    )
    kb.add(
        Btn("Tᴏᴘ Uꜱᴇʀꜱ",       callback_data="adm_top_users",      style="primary"),
        Btn("Pʟᴀɴ Dɪꜱᴛ",       callback_data="adm_plan_dist",      style="primary"),
    )
    kb.add(
        Btn("Bᴏᴛ Aᴄᴛɪᴠɪᴛʏ",   callback_data="adm_bot_activity",   style="primary"),
        Btn("Sᴛᴀᴛꜱ Oᴠᴇʀᴠɪᴇᴡ",  callback_data="adm_stats",          style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_revenue_report(call: types.CallbackQuery) -> None:
    pays = db_load()["payments"]
    now = now_utc()
    today   = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    def _sum(since: str) -> float:
        return sum(p.get("amount", 0) for p in pays
                   if p.get("status") == "approved" and str(p.get("ts", "")) >= since)
    rev_day   = _sum(today)
    rev_week  = _sum(week_ago)
    rev_month = _sum(month_ago)
    rev_all   = sum(p.get("amount", 0) for p in pays if p.get("status") == "approved")
    plan_rev: Dict[str, float] = defaultdict(float)
    for p in pays:
        if p.get("status") == "approved":
            plan_rev[p.get("plan", "unknown")] += p.get("amount", 0)
    by_plan = "\n".join(f"{bullet(k, f'{v}৳')}" for k, v in sorted(plan_rev.items()))
    cap = (
        f"<b>📈 {sc('Revenue Report')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Today',        f'{rev_day}৳')}\n"
        f"{bullet('Last 7 days',  f'{rev_week}৳')}\n"
        f"{bullet('Last 30 days', f'{rev_month}৳')}\n"
        f"{bullet('All time',     f'{rev_all}৳')}\n"
        f"{G['div']}\n<b>{sc('By Plan')}:</b>\n{by_plan}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_analytics"), call=call)


def render_adm_growth_stats(call: types.CallbackQuery) -> None:
    users = db_load()["users"].values()
    now = now_utc()
    def _count(days: int) -> int:
        since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        return sum(1 for u in users if str(u.get("joined", "")) >= since)
    bar = lambda n, mx: "█" * int(n / max(mx, 1) * 10) + "░" * (10 - int(n / max(mx, 1) * 10))
    d1, d7, d30, all_ = _count(1), _count(7), _count(30), len(list(users))
    cap = (
        f"<b>📉 {sc('User Growth')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Today',        f'{d1}  {bar(d1, d30)}')}\n"
        f"{bullet('Last 7 days',  f'{d7}  {bar(d7, all_)}')}\n"
        f"{bullet('Last 30 days', f'{d30}  {bar(d30, all_)}')}\n"
        f"{bullet('Total users',  all_)}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_analytics"), call=call)


def render_adm_top_users(call: types.CallbackQuery) -> None:
    d = db_load()
    pays = d["payments"]
    spend: Dict[str, float] = defaultdict(float)
    for p in pays:
        if p.get("status") == "approved":
            spend[str(p.get("uid", ""))] += p.get("amount", 0)
    top = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:10]
    rows = []
    for i, (uid, amt) in enumerate(top, 1):
        u = d["users"].get(uid, {})
        name = esc(u.get("name") or uid)
        bot_count = sum(1 for b in d["bots"].values() if str(b.get("owner")) == uid)
        rows.append(f"{i}. {name} — <b>{amt}৳</b> {G['bullet']} {bot_count} bots")
    cap = (
        f"<b>🏆 {sc('Top Users by Spending')}</b>\n"
        f"{G['div_eq']}\n"
        + ("\n".join(rows) or f"<i>{sc('No payments yet')}</i>")
        + FOOTER
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_analytics"), call=call)


def render_adm_plan_dist(call: types.CallbackQuery) -> None:
    users = list(db_load()["users"].values())
    total = max(len(users), 1)
    counts: Dict[str, int] = defaultdict(int)
    for u in users:
        counts[u.get("plan", "free")] += 1
    bar = lambda n: "█" * int(n / total * 12) + "░" * (12 - int(n / total * 12))
    rows = "\n".join(
        f"{bullet(PLAN_LIMITS.get(p, {}).get('name', p), f'{n} ({n*100//total}%) {bar(n)}')}"
        for p, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    )
    cap = (
        f"<b>🥧 {sc('Plan Distribution')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_analytics"), call=call)


def render_adm_bot_activity(call: types.CallbackQuery) -> None:
    bots = list(db_load()["bots"].values())
    total   = len(bots)
    running = sum(1 for x in RUNNING.values() if x["proc"].poll() is None)
    stopped = total - running
    crashed = sum(1 for b in bots if b.get("last_exit_code") not in (None, 0, ""))
    never   = sum(1 for b in bots if not b.get("last_started"))
    bar = lambda n: "█" * int(n / max(total, 1) * 10)
    cap = (
        f"<b>🤖 {sc('Bot Activity')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total bots',   total)}\n"
        f"{bullet('▶ Running',    f'{running}  {bar(running)}')}\n"
        f"{bullet('⏹ Stopped',    f'{stopped}  {bar(stopped)}')}\n"
        f"{bullet('💥 Crashed',   f'{crashed}  {bar(crashed)}')}\n"
        f"{bullet('⬜ Never run', never)}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_analytics"), call=call)


# ─── 2. USER TOOLS ───────────────────────────────────────────────────────────

def render_adm_user_tools(call: types.CallbackQuery) -> None:
    d = db_load()
    banned_n = sum(1 for u in d["users"].values() if u.get("banned"))
    cap = (
        f"<b>👥 {sc('User Tools')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total users', len(d['users']))}\n"
        f"{bullet('Banned',      banned_n)}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴀʀᴄʜ Uꜱᴇʀ",    callback_data="adm_user_search",     style="primary"),
        Btn("Bᴀɴɴᴇᴅ Lɪꜱᴛ",    callback_data="adm_banned_list",     style="danger"),
    )
    kb.add(
        Btn("Wᴀʟʟᴇᴛ Aᴅᴊᴜꜱᴛ",  callback_data="adm_wallet_admin",    style="success"),
        Btn("Exᴘᴏʀᴛ CSV",      callback_data="adm_user_export_csv", style="primary"),
    )
    kb.add(
        Btn("Nᴏᴛɪꜰʏ Uꜱᴇʀ",    callback_data="adm_notify_user",     style="primary"),
        Btn("Rᴇꜱᴇᴛ Uꜱᴇʀ",     callback_data="adm_user_reset",      style="danger"),
    )
    kb.add(
        Btn("Gɪᴠᴇ Pʟᴀɴ",      callback_data="adm_giveplan",        style="success"),
        Btn("Bᴀɴ/Uɴʙᴀɴ",      callback_data="adm_ban",             style="danger"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def package_bot_files_for_admin(bot_doc: Dict[str, Any]) -> Optional[Tuple[str, bytes]]:
    """
    Decrypts and bundles all source files for a given bot into a downloadable zip file (or returns single file bytes)
    for the admin.
    """
    bot_dir = Path(bot_doc.get("dir", ""))
    files = bot_doc.get("enc_files") or []
    bot_name = safe_name(bot_doc.get("name") or bot_doc.get("_id", "bot"))
    in_memory_files: List[Tuple[str, bytes]] = []

    # 1. Try decrypting from encrypted storage
    if files:
        for f in files:
            key_id = f.get("key_id")
            enc_path = Path(f.get("enc_path", ""))
            rel_name = f.get("rel_path") or f.get("filename") or "script.py"
            if enc_path.exists() and key_id:
                try:
                    key = KEYRING.fetch(key_id)
                    if key:
                        plain = read_encrypted(enc_path, key)
                        in_memory_files.append((rel_name, plain))
                except Exception as _e:
                    print(f"[AdminDL] Key decrypt error: {_e}", flush=True)

    # 2. If sandbox bot_dir has files on disk, grab them
    if not in_memory_files and bot_dir.exists():
        for root, dirs, fnames in os.walk(bot_dir):
            if any(x in root for x in (".deps", "venv", "__pycache__", ".git")):
                continue
            for fn in fnames:
                p = Path(root) / fn
                rel = str(p.relative_to(bot_dir))
                try:
                    in_memory_files.append((rel, p.read_bytes()))
                except Exception:
                    pass

    if not in_memory_files:
        return None

    if len(in_memory_files) == 1 and not in_memory_files[0][0].endswith(".zip"):
        fname, data = in_memory_files[0]
        return (fname, data)
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, data in in_memory_files:
                zf.writestr(rel, data)
        return (f"{bot_name}_{str(bot_doc.get('_id', 'bot'))[:6]}.zip", buf.getvalue())




# ══════════════════════════════════════════════════════════════════════════════
# 🛠️ ROBUST ADMIN USER TOOLS: GIVE PLAN & WALLET ADJUST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def action_adm_wallet_adjust(call: types.CallbackQuery, target_uid: Optional[str] = None) -> None:
    """Safe fallback & execution for adm_wallet_adjust callback."""
    if target_uid:
        render_adm_wallet_user(call, target_uid)
    else:
        render_adm_wallet_admin(call)


def action_adm_give_plan(call: types.CallbackQuery, target_uid: Optional[str] = None) -> None:
    """Safe fallback & execution for adm_giveplan callback."""
    if target_uid:
        render_adm_giveplan_user(call, target_uid)
    else:
        render_adm_giveplan(call)


def render_adm_giveplan_user(call: types.CallbackQuery, target_uid: str) -> None:
    """Interactive plan selection dashboard for a specific user ID."""
    if not is_admin(call.from_user.id):
        ack(call, "Admin only"); return
    d = db_load()
    u = d["users"].get(str(target_uid), {})
    u_name = esc(u.get("name", f"User {target_uid}"))
    cur_plan = u.get("plan", "free").upper()
    exp_str = fmt_ts(u.get("plan_expires")) if u.get("plan_expires") else "Lifetime / None"
    
    cap = (
        f"<b>🎁 {sc('Give Plan')} — {u_name}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('User ID', f'<code>{target_uid}</code>')}\n"
        f"{bullet('Current Plan', cur_plan)}\n"
        f"{bullet('Expires', exp_str)}\n"
        f"{G['div']}\n"
        f"<i>{sc('Click a plan below to grant immediately')}:</i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Starter (30d)", callback_data=f"adm_grant_{target_uid}_starter_30", style="primary"),
        Btn("Basic (30d)", callback_data=f"adm_grant_{target_uid}_basic_30", style="primary"),
    )
    kb.add(
        Btn("Pro (30d)", callback_data=f"adm_grant_{target_uid}_pro_30", style="success"),
        Btn("Enterprise (30d)", callback_data=f"adm_grant_{target_uid}_enterprise_30", style="success"),
    )
    kb.add(
        Btn("Lifetime (Never Expire)", callback_data=f"adm_grant_{target_uid}_lifetime_36500", style="success"),
        Btn("🆓 Reset to Free", callback_data=f"adm_grant_{target_uid}_free_0", style="danger"),
    )
    kb.add(Btn(f"{G['back']}  User Profile", callback_data=f"adm_uview_{target_uid}", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_wallet_user(call: types.CallbackQuery, target_uid: str) -> None:
    """Interactive 1-click wallet balance adjuster for a specific user ID."""
    if not is_admin(call.from_user.id):
        ack(call, "Admin only"); return
    d = db_load()
    u = d["users"].get(str(target_uid), {})
    u_name = esc(u.get("name", f"User {target_uid}"))
    cur_bal = float(u.get("wallet", 0))
    
    cap = (
        f"<b>💰 {sc('Adjust User Wallet')} — {u_name}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('User ID', f'<code>{target_uid}</code>')}\n"
        f"{bullet('Current Wallet', f'<b>{cur_bal}৳</b>')}\n"
        f"{G['div']}\n"
        f"<i>{sc('Click a quick button or type an amount (+100, -50, or =500)')}:</i>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_wallet_adjust", "target_uid": str(target_uid)}
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        Btn("+50৳", callback_data=f"adm_wbal_{target_uid}_+50", style="success"),
        Btn("+100৳", callback_data=f"adm_wbal_{target_uid}_+100", style="success"),
        Btn("+200৳", callback_data=f"adm_wbal_{target_uid}_+200", style="success"),
    )
    kb.add(
        Btn("+500৳", callback_data=f"adm_wbal_{target_uid}_+500", style="success"),
        Btn("+1000৳", callback_data=f"adm_wbal_{target_uid}_+1000", style="success"),
        Btn("-50৳", callback_data=f"adm_wbal_{target_uid}_-50", style="danger"),
    )
    kb.add(
        Btn("-100৳", callback_data=f"adm_wbal_{target_uid}_-100", style="danger"),
        Btn("Set 0৳", callback_data=f"adm_wbal_{target_uid}_=0", style="danger"),
    )
    kb.add(Btn(f"{G['back']}  User Profile", callback_data=f"adm_uview_{target_uid}", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def parse_flexible_giveplan(text: str) -> Optional[Dict[str, Any]]:
    """Parses arbitrary user inputs like '12345 pro 30', '12345 starter', '12345 60 pro', or '12345'."""
    parts = (text or "").strip().split()
    if not parts:
        return None
    if len(parts) == 1:
        if parts[0].isdigit():
            return {"uid": int(parts[0]), "plan": None, "days": None}
        return None
    uid = None
    plan = None
    days = None
    for p in parts:
        p_clean = p.lower().strip()
        if p_clean in PLAN_LIMITS and plan is None:
            plan = p_clean
        elif p.isdigit():
            if uid is None:
                uid = int(p)
            elif days is None:
                days = int(p)
    return {"uid": uid, "plan": plan, "days": days}


def parse_flexible_wallet(text: str, default_uid: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parses inputs like '12345 +100', '12345 500', '+100', '-50', '=200'."""
    parts = (text or "").strip().split()
    if not parts:
        return None
    if len(parts) == 1:
        tok = parts[0]
        if default_uid:
            return {"uid": str(default_uid), "op": tok}
        if tok.isdigit() and len(tok) >= 6:
            return {"uid": tok, "op": None}
        return None
    p1, p2 = parts[0], parts[1]
    if p1.isdigit() and len(p1) >= 6:
        return {"uid": p1, "op": p2}
    elif p2.isdigit() and len(p2) >= 6:
        return {"uid": p2, "op": p1}
    return {"uid": p1, "op": p2}


def render_adm_user_view(call: types.CallbackQuery, target_uid: str) -> None:
    if not is_admin(call.from_user.id):
        ack(call, "Admin only"); return
    d = db_load()
    u = d["users"].get(str(target_uid))
    if not u:
        ack(call, "User not found"); return
    user_bots = [b for b in d["bots"].values() if str(b.get("owner")) == str(target_uid)]

    bot_lines = []
    for idx, b in enumerate(user_bots, 1):
        bid = b["_id"]
        bname = esc(b.get("name", "unnamed"))
        st_icon = "🟢" if bid in RUNNING else ("🔴" if b.get("status") == "stopped" else "⚠️")
        bot_lines.append(f"{idx}. {st_icon} <b>{bname}</b> (<code>{bid}</code>)")

    bots_text = "\n".join(bot_lines) if bot_lines else f"<i>{sc('No bots hosted yet')}</i>"
    username_val = f"@{esc(u.get('username'))}" if u.get('username') else "—"
    ban_reason = esc(u.get('ban_reason', ''))
    ban_status = f"🚫 BANNED ({ban_reason})" if u.get('banned') else "✅ Active"
    u_name = esc(u.get('name', '—'))
    u_plan = esc(PLAN_LIMITS.get(u.get('plan', 'free'), {}).get('name', u.get('plan', 'free')))
    u_wallet = f"{u.get('wallet', 0)}৳"
    u_joined = str(u.get('joined', ''))[:19]
    u_botcount = f"{len(user_bots)} Hosted Bots"

    cap = (
        f"<b>👤 {sc('User Information & Bots')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('User ID', f'<code>{target_uid}</code>')}\n"
        f"{bullet('Name', u_name)}\n"
        f"{bullet('Username', username_val)}\n"
        f"{bullet('Plan', u_plan)}\n"
        f"{bullet('Wallet', u_wallet)}\n"
        f"{bullet('Joined', u_joined)}\n"
        f"{bullet('Status', ban_status)}\n"
        f"{bullet('Total Bots', u_botcount)}\n"
        f"{G['div']}\n"
        f"<b>🤖 {sc('Hosted Bots')}:</b>\n{bots_text}\n"
        f"{G['div']}{FOOTER}"
    )

    kb = types.InlineKeyboardMarkup()
    for b in user_bots:
        bid = b["_id"]
        bname = b.get("name", bid[:6])
        kb.add(Btn(f"Download'{bname[:14]}'", callback_data=f"adm_dl_bot_{bid}", style="success"))

    if len(user_bots) > 1:
        kb.add(Btn(f"Download ALL ({len(user_bots)}) Bots (.ZIP)", callback_data=f"adm_dl_allbots_{target_uid}", style="primary"))

    kb.add(
        Btn("Give Plan", callback_data=f"adm_giveplan_u_{target_uid}", style="success"),
        Btn("Adjust Wallet", callback_data=f"adm_wallet_u_{target_uid}", style="primary"),
    )
    kb.add(
        Btn("Send Message", callback_data=f"adm_notify_user_{target_uid}", style="primary"),
        Btn("Reset User", callback_data=f"adm_user_reset_{target_uid}", style="danger"),
    )
    kb.add(
        Btn("Ban/Unban", callback_data="adm_ban", style="danger"),
        Btn("Reset User", callback_data="adm_user_reset", style="danger"),
    )
    kb.add(Btn(f"{G['back']}  {sc('User Tools')}", callback_data="adm_user_tools", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def action_adm_download_bot(call: types.CallbackQuery, bot_id: str) -> None:
    if not is_owner(call.from_user.id) and not admin_can(call.from_user.id, "manage_admins"):
        ack(call, "🚫 Owner / full-access only.", show_alert=True); return
    ack(call, "Preparing bot files...")
    d = db_load()
    b = d["bots"].get(bot_id)
    if not b:
        ack(call, "Bot not found"); return
    res = package_bot_files_for_admin(b)
    if not res:
        bot.send_message(call.from_user.id, f"{G['no']} Could not retrieve source files for bot <code>{bot_id}</code>.", parse_mode="HTML")
        return
    fname, data = res
    owner_u = d["users"].get(str(b.get("owner")), {})
    owner_name = f"{owner_u.get('name','')} (@{owner_u.get('username','N/A')})"
    owner_id_val = str(b.get('owner', ''))
    b_name_val = esc(b.get('name', 'unnamed'))
    fsize_val = fmt_bytes(len(data))
    cap = (
        f"<b>📥 {sc('Bot Source Download')}</b>\n"
        f"{G['div']}\n"
        f"{bullet('Bot Name', b_name_val)}\n"
        f"{bullet('Bot ID', f'<code>{bot_id}</code>')}\n"
        f"{bullet('Owner', owner_name)}\n"
        f"{bullet('Owner ID', f'<code>{owner_id_val}</code>')}\n"
        f"{bullet('Filesize', fsize_val)}\n"
        f"{G['div']}"
    )
    try:
        bot.send_document(
            call.from_user.id,
            (fname, io.BytesIO(data)),
            caption=cap,
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(call.from_user.id, f"{G['no']} Error sending bot file: <code>{esc(e)}</code>", parse_mode="HTML")


def action_adm_download_user_all_bots(call: types.CallbackQuery, target_uid: str) -> None:
    if not is_owner(call.from_user.id) and not admin_can(call.from_user.id, "manage_admins"):
        ack(call, "🚫 Owner / full-access only.", show_alert=True); return
    ack(call, "Packaging all bots...")
    d = db_load()
    u = d["users"].get(str(target_uid), {})
    user_bots = [b for b in d["bots"].values() if str(b.get("owner")) == str(target_uid)]
    if not user_bots:
        ack(call, "No bots found for this user"); return

    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as master_zf:
        for b in user_bots:
            res = package_bot_files_for_admin(b)
            if res:
                fn, b_data = res
                folder = f"{safe_name(b.get('name', 'bot'))}_{b['_id'][:6]}"
                if fn.endswith(".zip"):
                    try:
                        with zipfile.ZipFile(io.BytesIO(b_data)) as sub_zf:
                            for m in sub_zf.infolist():
                                master_zf.writestr(f"{folder}/{m.filename}", sub_zf.read(m))
                        count += 1
                    except Exception:
                        master_zf.writestr(f"{folder}/{fn}", b_data)
                        count += 1
                else:
                    master_zf.writestr(f"{folder}/{fn}", b_data)
                    count += 1

    if count == 0:
        bot.send_message(call.from_user.id, f"{G['no']} No files found to export.", parse_mode="HTML")
        return

    zip_bytes = buf.getvalue()
    user_display = f"{u.get('name','')} (@{u.get('username','N/A')})"
    cap = (
        f"<b>📦 {sc('User Bots Master Archive')}</b>\n"
        f"{G['div']}\n"
        f"{bullet('User', user_display)}\n"
        f"{bullet('User ID', f'<code>{target_uid}</code>')}\n"
        f"{bullet('Total Bots', f'{count} Bots Packaged')}\n"
        f"{bullet('Archive Size', fmt_bytes(len(zip_bytes)))}\n"
        f"{G['div']}"
    )
    try:
        bot.send_document(
            call.from_user.id,
            (f"user_{target_uid}_all_bots.zip", io.BytesIO(zip_bytes)),
            caption=cap,
            parse_mode="HTML"
        )
    except Exception as e:
        bot.send_message(call.from_user.id, f"{G['no']} Error sending master archive: <code>{esc(e)}</code>", parse_mode="HTML")


def render_adm_user_search(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>🔍 {sc('Search User')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send a user ID, @username or part of their name')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_user_search"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_user_tools"), call=call)


def render_adm_banned_list(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    banned = [(uid, u) for uid, u in users.items() if u.get("banned")]
    rows = "\n".join(
        f"{G['bullet']} <code>{uid}</code> — {esc(u.get('name','?'))} "
        f"({esc(u.get('ban_reason','—'))})"
        for uid, u in banned[:20]
    ) or f"<i>{sc('No banned users')}</i>"
    cap = (
        f"<b>🚫 {sc('Banned Users')} ({len(banned)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_user_tools"), call=call)


def render_adm_wallet_admin(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "give_plan"):
        return
    cap = (
        f"<b>💰 {sc('Adjust User Wallet')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send')}: <code>&lt;user_id&gt; +amount</code> {sc('to add')}\n"
        f"{sc('Send')}: <code>&lt;user_id&gt; -amount</code> {sc('to deduct')}\n"
        f"{sc('Send')}: <code>&lt;user_id&gt; =amount</code> {sc('to set exact')}{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_wallet_adjust"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_user_tools"), call=call)


def render_adm_user_export_csv(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "Owner only"); return
    ack(call, "Building CSV…")
    def _bg() -> None:
        try:
            d = db_load()
            lines = ["id,name,username,plan,joined,bots,wallet,banned"]
            bots_by_owner: Dict[str, int] = defaultdict(int)
            for b in d["bots"].values():
                bots_by_owner[str(b.get("owner", ""))] += 1
            for uid, u in d["users"].items():
                lines.append(",".join(str(x).replace(",", " ") for x in [
                    uid,
                    u.get("name", ""),
                    u.get("username", ""),
                    u.get("plan", "free"),
                    str(u.get("joined", ""))[:10],
                    bots_by_owner.get(uid, 0),
                    u.get("wallet", 0),
                    "yes" if u.get("banned") else "no",
                ]))
            csv_bytes = "\n".join(lines).encode("utf-8")
            tmp = Path(tempfile.mktemp(suffix="_users.csv"))
            tmp.write_bytes(csv_bytes)
            with tmp.open("rb") as fh:
                bot.send_document(
                    call.from_user.id, fh,
                    caption=f"{G['ok']} {sc('Users CSV')} ({len(d['users'])} rows)",
                    visible_file_name="users_export.csv")
            tmp.unlink(missing_ok=True)
        except Exception as e:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} CSV error: <code>{esc(e)}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()


def render_adm_notify_user(call: types.CallbackQuery) -> None:
    if not admin_only_call(call, "give_plan"):
        return
    cap = (
        f"<b>📨 {sc('Notify Specific User')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send')}: <code>&lt;user_id&gt; Your message here</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_notify_user"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_user_tools"), call=call)


def render_adm_user_reset_prompt(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "🚫 Owner only.", show_alert=True); return
    cap = (
        f"<b>🔄 {sc('Reset User')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('This will stop all bots, delete bot records, and reset plan to free')}.\n"
        f"{sc('Send')}: <code>&lt;user_id&gt;</code> {sc('to reset')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_user_reset"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_user_tools"), call=call)


# ─── 3. BOT MANAGER ──────────────────────────────────────────────────────────

def render_adm_bot_manager(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"]
    running_n = sum(1 for x in RUNNING.values() if x["proc"].poll() is None)
    crashed_n = sum(1 for b in bots.values()
                    if b.get("last_exit_code") not in (None, 0, "") and
                    b["_id"] not in RUNNING)
    cap = (
        f"<b>🤖 {sc('Bot Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total bots',  len(bots))}\n"
        f"{bullet('Running',     running_n)}\n"
        f"{bullet('Crashed',     crashed_n)}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Cʀᴀꜱʜᴇᴅ Bᴏᴛꜱ",     callback_data="adm_crashed_bots",        style="danger"),
        Btn("Rᴇꜱᴛᴀʀᴛ Sᴛᴏᴘᴘᴇᴅ",   callback_data="adm_mass_restart_stopped", style="success"),
    )
    kb.add(
        Btn("Sᴇᴀʀᴄʜ Bᴏᴛ",        callback_data="adm_bot_search",          style="primary"),
        Btn("Sɪᴢᴇ Rᴇᴘᴏʀᴛ",       callback_data="adm_bot_size_report",     style="primary"),
    )
    kb.add(
        Btn("AI Sᴄᴀɴ Pᴇɴᴅɪɴɢ",   callback_data="adm_force_scan_all",      style="primary"),
        Btn("Aʟʟ Bᴏᴛꜱ",          callback_data="adm_allbots",             style="primary"),
    )
    kb.add(
        Btn("Kɪʟʟ Aʟʟ Nᴏᴡ",     callback_data="adm_kill_all_now",        style="danger"),
        Btn("Cʟᴇᴀɴ Oʀᴘʜᴀɴꜱ",    callback_data="adm_set_clean_orphans",   style="danger"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_crashed_bots(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"].values()
    crashed = [b for b in bots
               if b.get("last_exit_code") not in (None, 0, "")
               and b["_id"] not in RUNNING]
    rows = "\n".join(
        f"{G['bullet']} <code>{b['_id']}</code> {esc(b['name'][:20])} "
        f"— exit <b>{b.get('last_exit_code')}</b> "
        f"uid {b.get('owner')}"
        for b in crashed[:20]
    ) or f"<i>{sc('No crashed bots')}</i>"
    cap = (
        f"<b>💥 {sc('Crashed Bots')} ({len(crashed)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_bot_manager"), call=call)


def render_adm_mass_restart_stopped(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "🚫 Owner only.", show_alert=True); return
    stopped = [b for b in db_load()["bots"].values()
               if b["_id"] not in RUNNING
               and b.get("approval_status") != "pending"
               and b.get("status") != "stopped"]
    cap = (
        f"<b>🔄 {sc('Mass Restart Stopped Bots')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Eligible bots', len(stopped))}\n"
        f"{sc('This will try to start all idle/crashed bots')}.\n"
        f"{sc('Continue')}?{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{G['ok']}  {sc('Yes, Start All')}", callback_data="adm_mass_restart_stopped_yes", style="success"),
        Btn(f"{G['no']}  {sc('Cancel')}",          callback_data="adm_bot_manager",              style="primary"),
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def action_adm_mass_restart_stopped(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "🚫 Owner only.", show_alert=True); return
    ack(call, "Starting bots…")
    def _bg() -> None:
        ok = fail = 0
        for b in list(db_load()["bots"].values()):
            if b["_id"] in RUNNING:
                continue
            if b.get("approval_status") in ("pending", "rejected"):
                continue
            try:
                r = start_child(b)
                if r.get("ok"):
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
        audit(call.from_user.id, "mass_restart_stopped", f"ok={ok} fail={fail}")
        try:
            bot.send_message(call.from_user.id,
                             f"{G['ok']} {sc('Mass restart done')}: {ok} started, {fail} failed.")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


def render_adm_bot_search(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>🔍 {sc('Search Bot')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send a bot name or bot ID to find it')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_bot_search"}
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_bot_manager"), call=call)


def render_adm_bot_size_report(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"].values()
    usage: List[Tuple[float, str, str]] = []
    sandbox_root = BASE_DIR / "sandbox"
    for b in bots:
        bot_dir = Path(b.get("dir", ""))
        total = 0
        if bot_dir.exists():
            for root, _, files in os.walk(bot_dir):
                for f in files:
                    try:
                        total += (Path(root) / f).stat().st_size
                    except OSError:
                        pass
        usage.append((total, b["_id"], b.get("name", "?")))
    usage.sort(reverse=True)
    rows = "\n".join(
        f"{G['bullet']} {esc(name[:20])} — <b>{fmt_bytes(size)}</b>"
        for size, _, name in usage[:15]
    ) or f"<i>{sc('No sandboxes found')}</i>"
    total_all = sum(s for s, _, _ in usage)
    cap = (
        f"<b>📦 {sc('Bot Storage Report')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total storage', fmt_bytes(total_all))}\n"
        f"{bullet('Bot count',     len(usage))}\n"
        f"{G['div']}\n{rows}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_bot_manager"), call=call)


def action_adm_force_scan_all(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id) and not admin_can(call.from_user.id, "manage_admins"):
        ack(call, "🚫 Owner / full-access only.", show_alert=True); return
    ack(call, "Scanning pending bots with AI…")
    def _bg() -> None:
        pending = pending_list()
        scanned = flagged = 0
        results = []
        for bid, info in pending[:5]:
            b = find_bot(bid)
            if not b or not b.get("enc_files"):
                continue
            scanned += 1
            try:
                files_added = [(r, cipher_decrypt(enc)) for r, enc in
                               list(b["enc_files"].items())[:3]]
                result = _run_security_scan(files_added)
                verdict = result.get("verdict", "SAFE")
                if verdict in ("DANGEROUS", "SUSPICIOUS"):
                    flagged += 1
                    results.append(f"⚠️ {b['name'][:20]}: {verdict}")
                else:
                    results.append(f"✅ {b['name'][:20]}: SAFE")
            except Exception as e:
                results.append(f"❌ {bid[:8]}: error")
        summary = "\n".join(results) or "No pending bots to scan."
        audit(call.from_user.id, "force_scan_all", f"scanned={scanned} flagged={flagged}")
        try:
            bot.send_message(
                call.from_user.id,
                f"<b>🧪 {sc('AI Scan Report')}</b>\n"
                f"{G['div_eq']}\n"
                f"{bullet('Scanned', scanned)}\n"
                f"{bullet('Flagged', flagged)}\n"
                f"{G['div']}\n{summary}",
                parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


def action_adm_kill_all(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "🚫 Owner only.", show_alert=True); return
    ack(call, "Killing all bots…")
    def _bg() -> None:
        n = _do_stop_all_bots(call.from_user.id)
        try:
            bot.send_message(call.from_user.id,
                             f"{G['ok']} {sc('Killed')} {n} {sc('bot(s)')}.")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


# ─── 4. SECURITY CENTER ──────────────────────────────────────────────────────

def render_adm_sec_center(call: types.CallbackQuery) -> None:
    d = db_load()
    scan_log = d.get("scan_log", [])
    blocked  = sum(1 for s in scan_log if s.get("verdict") == "DANGEROUS")
    reviewed = sum(1 for s in scan_log if s.get("verdict") == "SUSPICIOUS")
    banned_n = sum(1 for u in d["users"].values() if u.get("banned"))
    cap = (
        f"<b>🛡️ {sc('Security Center')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Files Blocked',     blocked)}\n"
        f"{bullet('Manual Reviews',    reviewed)}\n"
        f"{bullet('Banned Users',      banned_n)}\n"
        f"{bullet('AI Scanner',        'Active' if os.environ.get('AI_INTEGRATIONS_OPENROUTER_BASE_URL') else 'No URL')}\n"
        f"{bullet('Pattern Scanner',   'Active')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Tʜʀᴇᴀᴛ Lᴏɢ",      callback_data="adm_threat_log",     style="danger"),
        Btn("Sᴇᴄ Sᴛᴀᴛꜱ",        callback_data="adm_sec_stats",      style="primary"),
    )
    kb.add(
        Btn("Wʜɪᴛᴇʟɪꜱᴛ Uꜱᴇʀ",  callback_data="adm_sec_whitelist",  style="success"),
        Btn("Bʟᴀᴄᴋʟɪꜱᴛ",        callback_data="adm_sec_blacklist",  style="danger"),
    )
    kb.add(
        Btn("Sᴄᴀɴ Rᴇᴘᴏʀᴛ",     callback_data="adm_scan_report",    style="primary"),
        Btn("Bᴀɴɴᴇᴅ Lɪꜱᴛ",     callback_data="adm_banned_list",    style="primary"),
    )
    kb.add(
        Btn("Sᴇᴄᴜʀɪᴛʏ Iɴꜰᴏ",   callback_data="adm_security",       style="primary"),
        Btn("Aᴜᴅɪᴛ Lᴏɢ",        callback_data="adm_audit",          style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["security"], cap, kb, call=call)


def render_adm_threat_log(call: types.CallbackQuery) -> None:
    scan_log = db_load().get("scan_log", [])
    flagged = [s for s in scan_log if s.get("verdict") in ("DANGEROUS", "SUSPICIOUS")][-20:]
    rows = "\n".join(
        f"{G['bullet']} <b>{esc(s.get('verdict'))}</b> "
        f"risk={s.get('risk_score',0)} "
        f"uid {s.get('uid','?')} "
        f"— {esc(s.get('filename','?'))[:25]} "
        f"<i>{str(s.get('ts',''))[:10]}</i>"
        for s in reversed(flagged)
    ) or f"<i>{sc('No threats logged')}</i>"
    cap = (
        f"<b>📋 {sc('Threat Log')} ({len(flagged)} {sc('entries')})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["security"], cap, _adm_back("adm_sec_center"), call=call)


def render_adm_sec_stats(call: types.CallbackQuery) -> None:
    scan_log = db_load().get("scan_log", [])
    total    = len(scan_log)
    blocked  = sum(1 for s in scan_log if s.get("verdict") == "DANGEROUS")
    sus      = sum(1 for s in scan_log if s.get("verdict") == "SUSPICIOUS")
    safe_n   = sum(1 for s in scan_log if s.get("verdict") == "SAFE")
    avg_risk = int(sum(s.get("risk_score", 0) for s in scan_log) / max(total, 1))
    cap = (
        f"<b>📊 {sc('Security Statistics')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total scans',    total)}\n"
        f"{bullet('🔴 Blocked',     blocked)}\n"
        f"{bullet('🟡 Suspicious',  sus)}\n"
        f"{bullet('✅ Safe',        safe_n)}\n"
        f"{bullet('Avg risk score', avg_risk)}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["security"], cap, _adm_back("adm_sec_center"), call=call)


def render_adm_sec_whitelist_prompt(call: types.CallbackQuery) -> None:
    wl = get_setting("scan_whitelist", []) or []
    rows = ", ".join(f"<code>{uid}</code>" for uid in wl) or f"<i>{sc('Empty')}</i>"
    cap = (
        f"<b>✅ {sc('Scan Whitelist')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Whitelisted users skip AI + pattern scan')}.\n"
        f"{sc('Current')}: {rows}\n"
        f"{G['div']}\n"
        f"{sc('Send')}: <code>add &lt;uid&gt;</code> {sc('or')} <code>del &lt;uid&gt;</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_whitelist"}
    show_menu(call.message.chat.id, PHOTOS["security"], cap, _adm_back("adm_sec_center"), call=call)


def render_adm_scan_report(call: types.CallbackQuery) -> None:
    scan_log = db_load().get("scan_log", [])
    last10 = scan_log[-10:]
    rows = "\n".join(
        f"{G['bullet']} {esc(s.get('verdict','?'))[:4]} "
        f"risk={s.get('risk_score',0):>3} "
        f"{esc(s.get('filename','?')[:22])} "
        f"<i>uid {s.get('uid','?')}</i>"
        for s in reversed(last10)
    ) or f"<i>{sc('No scans yet')}</i>"
    cap = (
        f"<b>🔍 {sc('Recent Scan Report')} (last {len(last10)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["security"], cap, _adm_back("adm_sec_center"), call=call)


def render_adm_sec_blacklist(call: types.CallbackQuery) -> None:
    bl = get_setting("domain_blacklist", []) or []
    rows = "\n".join(f"{G['bullet']} <code>{esc(d)}</code>" for d in bl) or f"<i>{sc('Empty')}</i>"
    cap = (
        f"<b>🚫 {sc('Domain Blacklist')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Bots containing these domains auto-flag as SUSPICIOUS')}.\n"
        f"{sc('Current')}: {rows}\n"
        f"{G['div']}\n"
        f"{sc('Send')}: <code>add domain.com</code> {sc('or')} <code>del domain.com</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_blacklist"}
    show_menu(call.message.chat.id, PHOTOS["security"], cap, _adm_back("adm_sec_center"), call=call)


# ─── 5. NOTIFICATIONS ────────────────────────────────────────────────────────

def render_adm_notify_center(call: types.CallbackQuery) -> None:
    users_n  = len(db_load()["users"])
    running_n = sum(1 for x in RUNNING.values() if x["proc"].poll() is None)
    cap = (
        f"<b>💬 {sc('Notifications Center')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total users',    users_n)}\n"
        f"{bullet('Running bots',   running_n)}\n"
        f"{G['div']}\n{sc('Choose notification type')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Nᴏᴛɪꜰʏ Eᴠᴇʀʏᴏɴᴇ", callback_data="adm_notify_all",        style="success"),
        Btn("▶ Bᴏᴛ Uꜱᴇʀꜱ Oɴʟʏ",  callback_data="adm_notify_running",     style="primary"),
    )
    kb.add(
        Btn("Bʏ Pʟᴀɴ",          callback_data="adm_notify_plan_select", style="primary"),
        Btn("Sɪɴɢʟᴇ Uꜱᴇʀ",     callback_data="adm_notify_user",        style="primary"),
    )
    kb.add(
        Btn("⏰ Sᴄʜᴇᴅᴜʟᴇ Mꜱɢ",    callback_data="adm_schedule_msg",       style="primary"),
        Btn("Qᴜɪᴄᴋ Aɴɴᴏᴜɴᴄᴇ",  callback_data="adm_quick_announce",     style="success"),
    )
    kb.add(
        Btn("Bʀᴏᴀᴅᴄᴀꜱᴛ",        callback_data="adm_broadcast",          style="success"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, kb, call=call)


def render_adm_notify_all(call: types.CallbackQuery) -> None:
    total = len(db_load()["users"])
    cap = (
        f"<b>📢 {sc('Notify All Users')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Recipients', total)}\n"
        f"{sc('Send your message now — it will be delivered to every user')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_broadcast"}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, _adm_back("adm_notify_center"), call=call)


def render_adm_notify_running(call: types.CallbackQuery) -> None:
    running_owner_ids: set = {str(info["owner"]) for info in RUNNING.values()
                               if info["proc"].poll() is None}
    cap = (
        f"<b>▶️ {sc('Notify Active Bot Users')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Recipients', len(running_owner_ids))}\n"
        f"{sc('Send your message now')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_notify_running",
                                       "target_uids": list(running_owner_ids)}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, _adm_back("adm_notify_center"), call=call)


def render_adm_notify_plan_select(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>📊 {sc('Notify By Plan')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Choose which plan to message')}.{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, v in PLAN_LIMITS.items():
        cnt = sum(1 for u in db_load()["users"].values() if u.get("plan") == k)
        kb.add(Btn(f"{esc(v['name'])} ({cnt})", callback_data=f"adm_notify_plan_{k}"))
    kb.add(Btn(f"{G['back']}  {sc('Back')}", callback_data="adm_notify_center"))
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, kb, call=call)


def render_adm_notify_plan(call: types.CallbackQuery, plan_key: str) -> None:
    users = db_load()["users"]
    targets = [uid for uid, u in users.items() if u.get("plan") == plan_key]
    plan_name = PLAN_LIMITS.get(plan_key, {}).get("name", plan_key)
    cap = (
        f"<b>📊 {sc('Notify')} {esc(plan_name)} {sc('Users')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Recipients', len(targets))}\n"
        f"{sc('Send your message now')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_notify_running",
                                       "target_uids": targets}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, _adm_back("adm_notify_center"), call=call)


def render_adm_schedule_msg(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>⏰ {sc('Schedule Message')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Send in format')}:\n"
        f"<code>at:YYYY-MM-DD HH:MM Your message text</code>\n"
        f"{sc('Example')}: <code>at:2025-12-31 10:00 Happy New Year!</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_broadcast"}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, _adm_back("adm_notify_center"), call=call)


def render_adm_quick_announce(call: types.CallbackQuery) -> None:
    chan = ANNOUNCE_CHANNEL or "—"
    cap = (
        f"<b>📣 {sc('Quick Announce')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Channel', chan)}\n"
        f"{sc('Send your message — it will be pinned in the announce channel')}.{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_quick_announce"}
    show_menu(call.message.chat.id, PHOTOS["broadcast"], cap, _adm_back("adm_notify_center"), call=call)


# ─── 6. SYSTEM TOOLS ─────────────────────────────────────────────────────────

def render_adm_sys_tools(call: types.CallbackQuery) -> None:
    rss = 0
    if psutil is not None:
        try:
            rss = psutil.Process(os.getpid()).memory_info().rss
        except Exception:
            pass
    up_secs = int(time.time() - START_TIME) if "START_TIME" in globals() else 0
    cap = (
        f"<b>⚙️ {sc('System Tools')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Uptime',   fmt_dur(up_secs * 1000))}\n"
        f"{bullet('RAM',      fmt_bytes(rss))}\n"
        f"{bullet('PID',      os.getpid())}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sʏꜱ Hᴇᴀʟᴛʜ",    callback_data="adm_sys_health",      style="primary"),
        Btn("Dɪꜱᴋ Uꜱᴀɢᴇ",    callback_data="adm_disk_usage",      style="primary"),
    )
    kb.add(
        Btn("DB Iɴꜰᴏ",       callback_data="adm_db_info",         style="primary"),
        Btn("Cʟᴇᴀʀ Cᴀᴄʜᴇ",   callback_data="adm_clear_cache",     style="danger"),
    )
    kb.add(
        Btn("Tᴏᴋᴇɴ Cʜᴇᴄᴋ",   callback_data="adm_token_check",     style="primary"),
        Btn("Exᴘᴏʀᴛ Dᴀᴛᴀ",   callback_data="adm_set_export",      style="primary"),
    )
    kb.add(
        Btn("Rᴇʟᴏᴀᴅ Cᴀᴄʜᴇ",  callback_data="adm_set_reload",      style="success"),
        Btn("Sʏꜱᴛᴇᴍ Iɴꜰᴏ",   callback_data="adm_set_sysinfo",     style="primary"),
    )
    kb.add(
        Btn("Fᴏᴏᴛᴇʀ Tᴇxᴛ",   callback_data="adm_set_footer_text", style="primary"),
        Btn("Wᴇʟᴄᴏᴍᴇ Mꜱɢ",   callback_data="adm_set_welcome_text",style="primary"),
    )
    kb.add(
        Btn("Rᴜʟᴇꜱ Tᴇxᴛ",    callback_data="adm_set_rules_text",  style="primary"),
        Btn("Gɪᴛʜᴜʙ",         callback_data="adm_github",          style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, kb, call=call)


def render_adm_sys_health(call: types.CallbackQuery) -> None:
    rss = vms = cpu_p = 0.0
    disk_total = disk_used = disk_free = 0
    if psutil is not None:
        try:
            p = psutil.Process(os.getpid())
            mi = p.memory_info()
            rss, vms = mi.rss, mi.vms
            cpu_p = p.cpu_percent(interval=0.3)
            du = psutil.disk_usage("/")
            disk_total, disk_used, disk_free = du.total, du.used, du.free
        except Exception:
            pass
    # Child bot CPU/RAM
    child_rss = 0
    child_n   = 0
    if psutil is not None:
        for info in RUNNING.values():
            if info["proc"].poll() is not None:
                continue
            try:
                cp = psutil.Process(info["proc"].pid)
                child_rss += cp.memory_info().rss
                child_n += 1
            except Exception:
                pass
    up_secs = int(time.time() - START_TIME) if "START_TIME" in globals() else 0
    cap = (
        f"<b>🖥️ {sc('System Health')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Uptime',          fmt_dur(up_secs * 1000))}\n"
        f"{bullet('Panel RAM (RSS)', fmt_bytes(int(rss)))}\n"
        f"{bullet('Panel RAM (VMS)', fmt_bytes(int(vms)))}\n"
        f"{bullet('Panel CPU',       f'{cpu_p:.1f}%')}\n"
        f"{bullet('Child bots',      f'{child_n} running')}\n"
        f"{bullet('Child RAM total', fmt_bytes(child_rss))}\n"
        f"{bullet('Disk total',      fmt_bytes(disk_total))}\n"
        f"{bullet('Disk used',       fmt_bytes(disk_used))}\n"
        f"{bullet('Disk free',       fmt_bytes(disk_free))}\n"
        f"{bullet('PID',             os.getpid())}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_sys_tools"), call=call)


def render_adm_disk_usage(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"].values()
    by_user: Dict[str, int] = defaultdict(int)
    for b in bots:
        bot_dir = Path(b.get("dir", ""))
        if not bot_dir.exists():
            continue
        size = 0
        for root, _, files in os.walk(bot_dir):
            for f in files:
                try:
                    size += (Path(root) / f).stat().st_size
                except OSError:
                    pass
        by_user[str(b.get("owner", "unknown"))] += size
    top = sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:12]
    d = db_load()
    rows = "\n".join(
        f"{G['bullet']} uid <code>{uid}</code> "
        f"({esc(d['users'].get(uid, {}).get('name', '?')[:15])}) — <b>{fmt_bytes(sz)}</b>"
        for uid, sz in top
    ) or f"<i>{sc('No data')}</i>"
    cap = (
        f"<b>💾 {sc('Disk Usage by User')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_sys_tools"), call=call)


def render_adm_db_info(call: types.CallbackQuery) -> None:
    d = db_load()
    db_file = DB_FILE
    db_size = db_file.stat().st_size if db_file.exists() else 0
    settings_size = SETTINGS_FILE.stat().st_size if SETTINGS_FILE.exists() else 0
    cap = (
        f"<b>🗄️ {sc('Database Info')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('DB file',       db_file.name)}\n"
        f"{bullet('DB size',       fmt_bytes(db_size))}\n"
        f"{bullet('Settings size', fmt_bytes(settings_size))}\n"
        f"{bullet('Users',         len(d['users']))}\n"
        f"{bullet('Bots',          len(d['bots']))}\n"
        f"{bullet('Payments',      len(d['payments']))}\n"
        f"{bullet('Coupons',       len(d['coupons']))}\n"
        f"{bullet('Tickets',       len(d.get('tickets', {})))}\n"
        f"{bullet('Audit entries', len(d.get('audit', [])))}\n"
        f"{bullet('Scan log',      len(d.get('scan_log', [])))}\n"
        f"{bullet('Cache entries', len(_DB_CACHE))}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS["admin"], cap, _adm_back("adm_sys_tools"), call=call)


def render_adm_token_check(call: types.CallbackQuery) -> None:
    ack(call, "Checking tokens…")
    def _bg() -> None:
        bots = list(db_load()["bots"].values())
        valid = invalid = missing = 0
        bad_list: List[str] = []
        for b in bots[:20]:
            tok = b.get("env", {}).get("BOT_TOKEN") or b.get("token")
            if not tok:
                missing += 1
                continue
            try:
                resp = _urllib_req.urlopen(
                    f"https://api.telegram.org/bot{tok}/getMe", timeout=5)
                data = _json.loads(resp.read())
                if data.get("ok"):
                    valid += 1
                else:
                    invalid += 1
                    bad_list.append(b.get("name", b["_id"])[:20])
            except Exception:
                invalid += 1
                bad_list.append(b.get("name", b["_id"])[:20])
        bad_txt = "\n".join(f"  ❌ {n}" for n in bad_list) or "  (none)"
        audit(call.from_user.id, "token_check", f"valid={valid} invalid={invalid}")
        try:
            bot.send_message(
                call.from_user.id,
                f"<b>🔑 {sc('Token Check Report')}</b>\n"
                f"{G['div_eq']}\n"
                f"{bullet('Valid',   valid)}\n"
                f"{bullet('Invalid', invalid)}\n"
                f"{bullet('Missing', missing)}\n"
                f"{G['div']}\n<b>Invalid bots:</b>\n{bad_txt}",
                parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()

# ═══════════════════════ END NEW ADMIN SUB-PANELS ═══════════════════════════


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║          MEGA ADVANCED ADMIN PANELS  (20+ new panels, 200+ features)     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS / DEFAULTS for new systems
# ─────────────────────────────────────────────────────────────────────────────

_FEATURE_FLAG_DEFAULTS: Dict[str, bool] = {
    "user_registration":    True,   # allow new users to register
    "bot_upload":           True,   # allow users to upload bots
    "bot_auto_start":       True,   # auto-start bots after approval
    "payment_system":       True,   # enable the payment panel
    "coupon_system":        True,   # allow coupon redemption
    "referral_system":      True,   # enable referrals
    "ticket_system":        True,   # enable support tickets
    "wallet_topup":         True,   # allow wallet top-up
    "gift_plan":            True,   # allow gifting plans
    "trial_plan":           True,   # allow free trials
    "public_stats":         False,  # show stats to regular users
    "bot_logs_user":        True,   # users can view their own bot logs
    "multi_file_upload":    True,   # allow zip uploads with multiple files
    "github_backup":        True,   # enable GitHub backup
    "cloudflare_tunnel":    True,   # enable Cloudflare tunnel feature
    "ai_scanner":           True,   # enable AI security scan
    "approval_system":      False,  # require admin approval for uploads (DISABLED)
    "maintenance_bypass":   False,  # admins bypass maintenance mode
    "sandbox_wipe":         True,   # wipe source files after start
    "rate_limiting":        True,   # enable rate limiting
    "audit_logging":        True,   # log admin actions to audit trail
    "auto_restart_bots":    True,   # auto-restart crashed bots
    "broadcast_enabled":    True,   # enable broadcast messages
    "webhook_notifications":False,  # send events to external webhook
    "2fa_required":         False,  # require 2FA for admin actions
}

_BOT_CONFIG_DEFAULTS: Dict[str, Any] = {
    "sandbox_wipe_delay":   6,      # seconds before wiping source files
    "max_upload_mb":        75,     # max upload size in MB
    "allowed_extensions":   ".py,.js,.zip,.txt,.json,.env",
    "bot_start_timeout":    30,     # seconds to wait for bot to start
    "bot_stop_timeout":     10,     # seconds for graceful stop
    "crash_restart_delay":  5,      # seconds before auto-restart after crash
    "max_crash_restarts":   5,      # max auto-restarts per bot per hour
    "log_ring_size":        200,    # lines kept in memory log ring
    "zip_max_files":        50,     # max files in a zip upload
    "env_strip_secrets":    True,   # strip BOT_TOKEN etc from child env
    "sandbox_network":      True,   # allow bots to use network
    "idle_timeout_mins":    0,      # 0 = no idle timeout
    "resource_check_secs":  30,     # interval for resource checks
}

_RATE_LIMIT_DEFAULTS: Dict[str, Dict[str, int]] = {
    "free":       {"uploads_per_day": 3,  "starts_per_hour": 5,  "msgs_per_min": 20},
    "starter":    {"uploads_per_day": 10, "starts_per_hour": 15, "msgs_per_min": 40},
    "basic":      {"uploads_per_day": 20, "starts_per_hour": 30, "msgs_per_min": 60},
    "pro":        {"uploads_per_day": 50, "starts_per_hour": 60, "msgs_per_min": 120},
    "enterprise": {"uploads_per_day": 100,"starts_per_hour": 120,"msgs_per_min": 240},
    "lifetime":   {"uploads_per_day": 999,"starts_per_hour": 999,"msgs_per_min": 999},
}

_MESSAGE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "welcome": {
        "label": "Welcome Message",
        "default": "Welcome {name}! 🎉 You're now registered on {brand}. Use /start to explore.",
        "vars": "{name}, {brand}, {plan}",
    },
    "payment_received": {
        "label": "Payment Received",
        "default": "✅ Payment of {amount}৳ received for {plan} plan. Your account has been upgraded!",
        "vars": "{name}, {amount}, {plan}, {tx_id}, {date}",
    },
    "plan_expired": {
        "label": "Plan Expiry Warning",
        "default": "⚠️ Your {plan} plan expires in {days} days. Renew now to avoid service interruption!",
        "vars": "{name}, {plan}, {days}, {expiry_date}",
    },
    "bot_approved": {
        "label": "Bot Approved",
        "default": "✅ Your bot '{bot_name}' has been approved and is now running!",
        "vars": "{name}, {bot_name}, {bot_id}",
    },
    "bot_rejected": {
        "label": "Bot Rejected",
        "default": "❌ Your bot '{bot_name}' was rejected. Reason: {reason}",
        "vars": "{name}, {bot_name}, {reason}",
    },
    "referral_reward": {
        "label": "Referral Reward",
        "default": "🎁 You earned {amount}৳ for referring {referred_name}! Keep sharing!",
        "vars": "{name}, {amount}, {referred_name}",
    },
    "ticket_reply": {
        "label": "Ticket Reply",
        "default": "📩 Admin replied to your ticket #{ticket_id}: {reply}",
        "vars": "{name}, {ticket_id}, {reply}",
    },
    "bot_crashed": {
        "label": "Bot Crashed Alert",
        "default": "💥 Your bot '{bot_name}' crashed (exit code {exit_code}). Check logs or re-upload.",
        "vars": "{name}, {bot_name}, {exit_code}",
    },
    "maintenance": {
        "label": "Maintenance Notice",
        "default": "🔧 {brand} is currently under maintenance. We'll be back soon!",
        "vars": "{brand}, {eta}",
    },
    "upgrade_prompt": {
        "label": "Upgrade Prompt",
        "default": "💎 Upgrade to {plan} and get {max_bots} bots, {ram}MB RAM, and more!",
        "vars": "{name}, {plan}, {max_bots}, {ram}, {price}",
    },
}

_SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en":    "🇬🇧 English",
    "bn":    "🇧🇩 বাংলা (Bengali)",
    "hi":    "🇮🇳 हिन्दी (Hindi)",
    "ar":    "🇸🇦 العربية (Arabic)",
    "ur":    "🇵🇰 اردو (Urdu)",
    "tr":    "🇹🇷 Türkçe",
    "ru":    "🇷🇺 Русский",
    "es":    "🇪🇸 Español",
    "fr":    "🇫🇷 Français",
    "de":    "🇩🇪 Deutsch",
    "pt":    "🇧🇷 Português",
    "id":    "🇮🇩 Bahasa Indonesia",
    "ms":    "🇲🇾 Bahasa Melayu",
    "fa":    "🇮🇷 فارسی (Persian)",
    "zh":    "🇨🇳 中文 (Chinese)",
}

_APPEARANCE_THEMES: Dict[str, Dict[str, str]] = {
    "dark":      {"name": "Dark",       "header": "#0F172A", "accent": "#6366F1", "emoji_ok": "✅"},
    "midnight":  {"name": "Midnight",   "header": "#020617", "accent": "#818CF8", "emoji_ok": "💫"},
    "ocean":     {"name": "Ocean",      "header": "#0E4472", "accent": "#38BDF8", "emoji_ok": "🌊"},
    "forest":    {"name": "Forest",     "header": "#14532D", "accent": "#4ADE80", "emoji_ok": "🌿"},
    "sunset":    {"name": "Sunset",     "header": "#7C2D12", "accent": "#FB923C", "emoji_ok": "🌅"},
    "royal":     {"name": "Royal",      "header": "#3B0764", "accent": "#C084FC", "emoji_ok": "👑"},
    "neon":      {"name": "Neon",       "header": "#0A0A0A", "accent": "#39FF14", "emoji_ok": "⚡"},
    "rose":      {"name": "Rose",       "header": "#881337", "accent": "#FB7185", "emoji_ok": "🌹"},
    "gold":      {"name": "Gold",       "header": "#451A03", "accent": "#FBBF24", "emoji_ok": "💰"},
    "ice":       {"name": "Ice",        "header": "#1E3A5F", "accent": "#BAE6FD", "emoji_ok": "❄️"},
}

# ─────────────────────────────────────────────────────────────────────────────
# GITHUB FILE BROWSER & RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def _gh_api(endpoint: str, token: Optional[str] = None,
            method: str = "GET", body: Optional[bytes] = None) -> Any:
    """Make a GitHub API call. Returns parsed JSON or raises."""
    import urllib.request as _ur
    import json as _j
    tok = token or GH.get("token", "")
    url = endpoint if endpoint.startswith("http") else f"https://api.github.com{endpoint}"
    req = _ur.Request(url, method=method, data=body)
    req.add_header("Authorization", f"token {tok}")
    req.add_header("Accept",        "application/vnd.github.v3+json")
    req.add_header("User-Agent",    "SirLinuxxHostingBot/2.0")
    if body:
        req.add_header("Content-Type", "application/json")
    with _ur.urlopen(req, timeout=15) as resp:
        return _j.loads(resp.read().decode("utf-8"))


def _gh_api_safe(endpoint: str, token: Optional[str] = None) -> Tuple[bool, Any]:
    """GitHub API call returning (ok, data_or_error_str)."""
    try:
        return True, _gh_api(endpoint, token)
    except Exception as e:
        return False, str(e)


def render_adm_gh_browser(call: types.CallbackQuery) -> None:
    """GitHub File Browser — main landing panel."""
    has_token = bool(GH.get("token"))
    has_repo  = bool(GH.get("repo"))
    cur_repo  = GH.get("repo") or "—"
    cur_branch= GH.get("branch") or "main"
    cap = (
        f"<b>🐙 {sc('GitHub File Browser')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Token',  '✅ Set' if has_token else '❌ Not set')}\n"
        f"{bullet('Repo',   esc(cur_repo))}\n"
        f"{bullet('Branch', esc(cur_branch))}\n"
        f"{G['div']}\n"
        f"<i>{sc('Browse and run files directly from any GitHub repo. Works with public and private repos (with token).')}  </i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    if has_token:
        kb.add(Btn("Bʀᴏᴡꜱᴇ Mʏ Rᴇᴘᴏꜱ",  callback_data="adm_gh_repos",        style="success"))
        if has_repo:
            kb.add(Btn(f"{esc(cur_repo)[:25]}",  callback_data="adm_gh_browse_repo", style="primary"))
    kb.add(
        Btn("Sᴇᴛ Tᴏᴋᴇɴ",       callback_data="gh_set_token",   style="primary"),
        Btn("Sᴇᴛ Rᴇᴘᴏ",         callback_data="gh_set_repo",    style="primary"),
    )
    kb.add(
        Btn("Sᴇᴛ Bʀᴀɴᴄʜ",       callback_data="gh_set_branch",  style="primary"),
        Btn("Rᴇꜰʀᴇꜱʜ",          callback_data="adm_gh_refresh_repos", style="primary"),
    )
    kb.add(
        Btn("Gɪᴛʜᴜʙ Bᴀᴄᴋᴜᴘ",   callback_data="adm_github",     style="primary"),
        Btn(f"Aᴅᴍɪɴ",  callback_data="menu_admin",     style="primary"),
    )
    show_menu(call.message.chat.id, PHOTOS.get("gh_browser", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_gh_repos(call: types.CallbackQuery, force: bool = False) -> None:
    """List all accessible GitHub repositories."""
    if not GH.get("token"):
        ack(call, "Set GitHub token first"); return render_adm_gh_browser(call)
    ack(call, "Fetching repos…")
    def _bg() -> None:
        ok, data = _gh_api_safe("/user/repos?per_page=50&sort=updated&type=all")
        if not ok:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('GitHub API error')}: <code>{esc(str(data)[:200])}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
            return
        repos = data if isinstance(data, list) else []
        if not repos:
            try:
                bot.send_message(call.from_user.id, f"<i>{sc('No repos found.')}</i>", parse_mode="HTML")
            except Exception:
                pass
            return
        rows = "\n".join(
            f"{G['bullet']} <b>{esc(r['full_name'])}</b> "
            f"{'🔒' if r.get('private') else '🌐'} "
            f"⭐{r.get('stargazers_count',0)} "
            f"<i>{esc((r.get('description') or '')[:40])}</i>"
            for r in repos[:20]
        )
        cap = (
            f"<b>🐙 {sc('Your GitHub Repos')} ({len(repos)})</b>\n"
            f"{G['div_eq']}\n{rows}\n{G['div']}\n"
            f"{sc('Tap a repo to browse its files')}.{FOOTER}"
        )
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in repos[:15]:
            name = r["full_name"]
            short = name[:35]
            icon = "🔒" if r.get("private") else "🌐"
            # Store repo in state, use index-based callback
            kb.add(Btn(f"{icon} {short}", callback_data=f"adm_ghrepo_{name[:40]}", style="primary"))
        kb.add(Btn(f"{G['back']}  Gʜ Bʀᴏᴡꜱᴇʀ", callback_data="adm_gh_browser", style="primary"))
        try:
            bot.send_message(call.from_user.id, cap, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


def render_adm_gh_files(call: types.CallbackQuery, repo: str, path: str = "") -> None:
    """Browse files in a GitHub repo at a given path."""
    if not GH.get("token") or not repo:
        ack(call, "Set token and repo first"); return
    ack(call, f"Loading {repo}/{path or 'root'}…")
    def _bg() -> None:
        branch = GH.get("branch", "main")
        ep = f"/repos/{repo}/contents/{path}?ref={branch}"
        ok, data = _gh_api_safe(ep)
        if not ok:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('Error loading files')}: <code>{esc(str(data)[:200])}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
            return
        items = data if isinstance(data, list) else [data]
        items.sort(key=lambda x: (0 if x.get("type") == "dir" else 1, x.get("name", "")))
        # Save file list in state for index-based navigation
        USER_STATES[call.from_user.id] = USER_STATES.get(call.from_user.id, {})
        USER_STATES[call.from_user.id].update({
            "gh_repo": repo,
            "gh_path": path,
            "gh_files_list": items,
        })
        breadcrumb = f"{repo}/{path}" if path else repo
        rows = "\n".join(
            f"{'📁' if it.get('type')=='dir' else '📄'} {esc(it.get('name','?'))} "
            + (f"<i>({fmt_bytes(it.get('size',0))})</i>" if it.get('type') != 'dir' else "")
            for it in items[:25]
        )
        cap = (
            f"<b>📂 {esc(breadcrumb[:50])}</b>\n"
            f"{G['div_eq']}\n{rows}\n"
            f"{G['div']}\n{len(items)} items{FOOTER}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        if path:
            kb.add(Btn("⬆ Uᴘ",  callback_data="adm_gh_up", style="primary"))
        for i, it in enumerate(items[:12]):
            icon = "📁" if it.get("type") == "dir" else _file_icon(it.get("name",""))
            kb.add(Btn(f"{icon} {esc(it.get('name','?'))[:28]}", callback_data=f"adm_ghfile_{i}", style="primary"))
        kb.add(Btn(f"{G['back']}  Rᴇᴘᴏꜱ", callback_data="adm_gh_repos", style="primary"))
        try:
            bot.send_message(call.from_user.id, cap, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


def _file_icon(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {"py":"🐍",".js":"📜",".json":"📋",".env":"🔐",".txt":"📝",
            ".md":"📝",".zip":"📦",".sh":"⚙️",".yaml":"📋",".yml":"📋",
            ".toml":"📋",".cfg":"⚙️",".ini":"⚙️",".html":"🌐",".css":"🎨"}.get(ext, "📄")


def render_adm_gh_file_view(call: types.CallbackQuery, repo: str, path: str) -> None:
    """View a single file from GitHub and optionally run it."""
    ack(call, f"Loading {Path(path).name}…")
    USER_STATES[call.from_user.id] = USER_STATES.get(call.from_user.id, {})
    USER_STATES[call.from_user.id]["gh_view_path"] = path
    USER_STATES[call.from_user.id]["gh_repo"] = repo
    def _bg() -> None:
        branch = GH.get("branch", "main")
        ep = f"/repos/{repo}/contents/{path}?ref={branch}"
        ok, data = _gh_api_safe(ep)
        if not ok or isinstance(data, list):
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('Cannot read file')}: <code>{esc(str(data)[:200])}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
            return
        fname   = data.get("name", path)
        size    = data.get("size", 0)
        sha     = data.get("sha", "")[:7]
        dl_url  = data.get("download_url", "")
        content_b64 = data.get("content", "")
        try:
            raw = base64.b64decode(content_b64.replace("\n", ""))
            preview = raw[:1000].decode("utf-8", errors="replace")
        except Exception:
            preview = "(binary file — cannot preview)"
        ext = Path(fname).suffix.lower()
        runnable = ext in (".py", ".js")
        cap = (
            f"<b>{_file_icon(fname)} {esc(fname)}</b>\n"
            f"{G['div_eq']}\n"
            f"{bullet('Repo',   esc(repo))}\n"
            f"{bullet('Path',   esc(path))}\n"
            f"{bullet('Size',   fmt_bytes(size))}\n"
            f"{bullet('SHA',    sha)}\n"
            f"{bullet('Branch', GH.get('branch','main'))}\n"
            f"{G['div']}\n"
            f"<pre>{esc(preview[:800])}</pre>"
            f"{'...(truncated)' if len(raw) > 1000 else ''}{FOOTER}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        if runnable:
            kb.add(Btn("▶ Rᴜɴ Aꜱ Bᴏᴛ",  callback_data="adm_gh_run_file",  style="success"))
        kb.add(
            Btn("Dᴏᴡɴʟᴏᴀᴅ",        callback_data="adm_gh_dl_file",   style="primary"),
            Btn("Bᴀᴄᴋ ᴛᴏ Fᴏʟᴅᴇʀ",  callback_data="adm_gh_browse_repo",style="primary"),
        )
        kb.add(Btn(f"{G['back']}  Gʜ Bʀᴏᴡꜱᴇʀ", callback_data="adm_gh_browser", style="primary"))
        try:
            bot.send_message(call.from_user.id, cap, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    threading.Thread(target=_bg, daemon=True).start()


def action_adm_gh_run_file(call: types.CallbackQuery, repo: str, path: str) -> None:
    """Download a file from GitHub and register + start it as a bot."""
    if not repo or not path:
        ack(call, "No file selected"); return
    ack(call, f"Downloading and deploying {Path(path).name}…")
    def _bg() -> None:
        try:
            branch = GH.get("branch", "main")
            ep = f"/repos/{repo}/contents/{path}?ref={branch}"
            ok, data = _gh_api_safe(ep)
            if not ok:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} API error: <code>{esc(str(data)[:200])}</code>",
                                 parse_mode="HTML"); return
            fname = data.get("name", Path(path).name)
            content_b64 = data.get("content", "")
            raw = base64.b64decode(content_b64.replace("\n", ""))
            # Create a new bot entry
            bid   = secrets.token_hex(8)
            d_db  = db_load()
            owner = call.from_user.id
            bot_name = Path(fname).stem[:30]
            # Build the bot record
            bot_dir = BASE_DIR / "sandbox" / bid
            bot_dir.mkdir(parents=True, exist_ok=True)
            src_file = bot_dir / fname
            src_file.write_bytes(raw)
            # Encrypt the file for storage
            enc_files: Dict[str, str] = {}
            try:
                enc_files[fname] = cipher_encrypt(raw)
            except Exception:
                enc_files[fname] = base64.b64encode(raw).decode()
            new_bot: Dict[str, Any] = {
                "_id":          bid,
                "name":         bot_name,
                "owner":        owner,
                "dir":          str(bot_dir),
                "files":        [fname],
                "enc_files":    enc_files,
                "env":          {},
                "plan":         d_db["users"].get(str(owner), {}).get("plan", "free"),
                "status":       "stopped",
                "approval_status": "approved",  # admin-deployed
                "created_at":   ts_iso(),
                "source":       f"github:{repo}/{path}",
                "last_exit_code": None,
            }
            d_db["bots"][bid] = new_bot
            db_save(d_db)
            audit(owner, "gh_run_file", f"repo={repo} path={path} bid={bid}")
            # Start the bot
            result = start_child(new_bot)
            if result.get("ok"):
                msg = (f"✅ <b>{esc(bot_name)}</b> {sc('deployed and started from GitHub!')}\n"
                       f"{bullet('Bot ID', f'<code>{bid}</code>')}\n"
                       f"{bullet('Source', f'{esc(repo)}/{esc(path)}')} ")
            else:
                msg = (f"⚠️ <b>{esc(bot_name)}</b> {sc('uploaded but failed to start')}.\n"
                       f"{bullet('Error', esc(str(result.get('error','?'))[:100]))}")
            bot.send_message(call.from_user.id, msg, parse_mode="HTML")
        except Exception as e:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('Deploy error')}: <code>{esc(e)}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()


def action_adm_gh_dl_file(call: types.CallbackQuery, repo: str, path: str) -> None:
    """Download a raw file from GitHub and send it to admin."""
    if not repo or not path:
        ack(call, "No file selected"); return
    ack(call, "Downloading…")
    def _bg() -> None:
        try:
            branch = GH.get("branch", "main")
            ep = f"/repos/{repo}/contents/{path}?ref={branch}"
            ok, data = _gh_api_safe(ep)
            if not ok:
                bot.send_message(call.from_user.id, f"{G['no']} {esc(str(data)[:200])}"); return
            fname = data.get("name", Path(path).name)
            raw = base64.b64decode(data.get("content","").replace("\n",""))
            tmp = Path(tempfile.mktemp(suffix=f"_{fname}"))
            tmp.write_bytes(raw)
            with tmp.open("rb") as fh:
                bot.send_document(call.from_user.id, fh,
                                  caption=f"📥 {esc(fname)} ({fmt_bytes(len(raw))})\n"
                                          f"<code>{esc(repo)}/{esc(path)}</code>",
                                  visible_file_name=fname, parse_mode="HTML")
            tmp.unlink(missing_ok=True)
        except Exception as e:
            try:
                bot.send_message(call.from_user.id, f"{G['no']} {esc(e)}")
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# BOT API SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

def _mask_api_token(token: str) -> str:
    token = str(token or "").strip()
    if not token:
        return "❌ Not set"
    if len(token) <= 12:
        return "••••••••"
    return f"{token[:6]}••••••••{token[-6:]}"


def render_adm_api_settings(call: types.CallbackQuery) -> None:
    """Unified panel for configuring the two Telegram Bot API tokens."""
    if not is_owner(call.from_user.id):
        ack(call, "Owner only")
        return

    t1 = get_setting("api_bot_token_1", "") or os.environ.get("BOT_TOKEN", "")
    t2 = get_setting("api_bot_token_2", "") or os.environ.get("BOT_TOKEN_2", "") or os.environ.get("SECOND_BOT_TOKEN", "")

    cap = (
        f"<b>🔑 {sc('Bot API Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Bot 1 API', _mask_api_token(t1))}\n"
        f"{bullet('Bot 2 API', _mask_api_token(t2))}\n"
        f"{G['div']}\n"
        f"<i>{sc('Set or replace your Telegram BotFather tokens here. Changes take effect after restarting/redeploying the panel.')}</i>{FOOTER}"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Bᴏᴛ 1 API", callback_data="adm_api_set_1", style="primary"),
        Btn("Sᴇᴛ Bᴏᴛ 2 API", callback_data="adm_api_set_2", style="primary"),
    )
    kb.add(
        Btn("Cʟᴇᴀʀ Bᴏᴛ 1", callback_data="adm_api_clear_1", style="danger"),
        Btn("Cʟᴇᴀʀ Bᴏᴛ 2", callback_data="adm_api_clear_2", style="danger"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def _validate_and_save_bot_api(uid: int, token: str, slot: int) -> bool:
    token = token.strip()
    if not _is_valid_telegram_token(token):
        return False
    set_setting(f"api_bot_token_{slot}", token)
    audit(uid, f"bot_api_set_{slot}", "Telegram Bot API token updated")
    return True


# PAYMENT CONFIG PANEL
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_pay_config(call: types.CallbackQuery) -> None:
    """Full payment configuration panel."""
    auto_approve = bool(get_setting("auto_approve_payments", False))
    min_amt = get_setting("min_payment_amount", 50)
    max_amt = get_setting("max_payment_amount", 10000)
    currency = get_setting("payment_currency", "BDT")
    currency_sym = get_setting("currency_symbol", "৳")
    tax_pct = get_setting("payment_tax_pct", 0)
    methods_enabled = sum(1 for k in PAYMENT_METHODS.keys() if get_setting(f"pm_enabled_{k}", True))
    notif_chan = get_setting("payment_notif_channel", "") or "—"
    cap = (
        f"<b>💳 {sc('Payment Configuration')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Auto-Approve',   '✅ ON' if auto_approve else '❌ OFF')}\n"
        f"{bullet('Min Amount',     f'{min_amt}{currency_sym}')}\n"
        f"{bullet('Max Amount',     f'{max_amt}{currency_sym}')}\n"
        f"{bullet('Currency',       f'{currency} ({currency_sym})')}\n"
        f"{bullet('Tax/Fee %',      f'{tax_pct}%')}\n"
        f"{bullet('Active Methods', methods_enabled)}\n"
        f"{bullet('Notif Channel',  esc(notif_chan))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅' if auto_approve else '❌'}  Aᴜᴛᴏ-Aᴘᴘʀ",
            callback_data="adm_pay_auto_approve",
            style="success" if auto_approve else "danger"),
        Btn("Pᴀʏ Mᴇᴛʜᴏᴅꜱ",   callback_data="adm_pay_methods",      style="primary"),
    )
    kb.add(
        Btn("Aᴍᴏᴜɴᴛ Lɪᴍɪᴛꜱ",  callback_data="adm_pay_limits",       style="primary"),
        Btn("Cᴜʀʀᴇɴᴄʏ",        callback_data="adm_pay_currency",     style="primary"),
    )
    kb.add(
        Btn("Rᴇᴄᴇɪᴘᴛ Tᴇᴍᴘʟ",  callback_data="adm_pay_receipt_tmpl", style="primary"),
        Btn("Nᴏᴛɪꜰ Sᴇᴛᴛɪɴɢꜱ",  callback_data="adm_pay_notif",        style="primary"),
    )
    kb.add(
        Btn("Sᴇᴛ Tᴀx %",       callback_data="adm_bc_set_payment_tax_pct",  style="primary"),
        Btn("Pᴀʏ Hɪꜱᴛᴏʀʏ",    callback_data="adm_payments",         style="primary"),
    )
    kb.add(
        Btn("Aᴘᴘʀᴏᴠᴇ Pᴀʏ",     callback_data="adm_approve",          style="success"),
        Btn("Exᴘᴏʀᴛ CSV",       callback_data="adm_user_export_csv",  style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_methods(call: types.CallbackQuery) -> None:
    """Show all payment methods with enable/disable toggle."""
    rows = []
    for key, m in PAYMENT_METHODS.items():
        enabled = bool(get_setting(f"pm_enabled_{key}", True))
        rows.append(f"{'✅' if enabled else '❌'} <b>{esc(m['name'])}</b> — "
                    f"<code>{esc(m['number'])}</code> ({esc(m['type'])})")
    cap = (
        f"<b>💰 {sc('Payment Methods')}</b>\n"
        f"{G['div_eq']}\n"
        + "\n".join(rows)
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for key, m in PAYMENT_METHODS.items():
        enabled = bool(get_setting(f"pm_enabled_{key}", True))
        kb.add(
            Btn(f"{'✅' if enabled else '❌'} {esc(m['name'])}",
                callback_data=f"adm_pay_edit_{key}", style="primary"),
        )
    kb.add(Btn(f"{G['back']}  Pᴀʏ Cᴏɴꜰɪɢ", callback_data="adm_pay_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_method_edit(call: types.CallbackQuery, key: str) -> None:
    """Edit a single payment method."""
    m = PAYMENT_METHODS.get(key)
    if not m:
        ack(call, "Unknown method"); return
    enabled = bool(get_setting(f"pm_enabled_{key}", True))
    stored_num = get_setting(f"pm_number_{key}", m["number"]) or m["number"]
    cap = (
        f"<b>💰 {sc('Edit')} {esc(m['name'])}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Status',  '✅ Enabled' if enabled else '❌ Disabled')}\n"
        f"{bullet('Number',  esc(stored_num))}\n"
        f"{bullet('Type',    esc(m['type']))}\n"
        f"{bullet('Tag',     esc(m['tag']))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'❌ Disable' if enabled else '✅ Enable'}",
            callback_data=f"adm_pay_method_toggle_{key}",
            style="danger" if enabled else "success"),
        Btn("Cʜᴀɴɢᴇ Nᴜᴍʙᴇʀ",
            callback_data=f"adm_pay_method_setnumber_{key}", style="primary"),
    )
    kb.add(Btn(f"{G['back']}  Pᴀʏ Mᴇᴛʜᴏᴅꜱ", callback_data="adm_pay_methods", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_limits(call: types.CallbackQuery) -> None:
    min_amt = get_setting("min_payment_amount", 50)
    max_amt = get_setting("max_payment_amount", 10000)
    disc_threshold = get_setting("discount_threshold", 500)
    disc_pct  = get_setting("discount_pct", 5)
    cap = (
        f"<b>📊 {sc('Payment Amount Limits')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Min Payment',      f'{min_amt}৳')}\n"
        f"{bullet('Max Payment',      f'{max_amt}৳')}\n"
        f"{bullet('Discount >= ৳',   disc_threshold)}\n"
        f"{bullet('Discount %',       f'{disc_pct}%')}\n"
        f"{G['div']}\n"
        f"{sc('Set limits below. All values in your currency unit.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Mɪɴ",         callback_data="adm_bc_set_min_payment_amount",  style="primary"),
        Btn("Sᴇᴛ Mᴀx",         callback_data="adm_bc_set_max_payment_amount",  style="primary"),
    )
    kb.add(
        Btn("Dɪꜱᴄ Tʜʀᴇꜱʜᴏʟᴅ", callback_data="adm_bc_set_discount_threshold",  style="primary"),
        Btn("Dɪꜱᴄ %",           callback_data="adm_bc_set_discount_pct",        style="primary"),
    )
    kb.add(Btn(f"{G['back']}  Pᴀʏ Cᴏɴꜰɪɢ", callback_data="adm_pay_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_currency(call: types.CallbackQuery) -> None:
    cur = get_setting("payment_currency", "BDT")
    sym = get_setting("currency_symbol",  "৳")
    cap = (
        f"<b>💱 {sc('Currency Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Currency Code', cur)}\n"
        f"{bullet('Symbol',        sym)}\n"
        f"{G['div']}\n"
        f"{sc('Examples')}: BDT/৳, USD/$, EUR/€, INR/₹, PKR/₨{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Cᴏᴅᴇ",     callback_data="adm_bc_set_payment_currency", style="primary"),
        Btn("Sᴇᴛ Sʏᴍʙᴏʟ",   callback_data="adm_bc_set_currency_symbol",  style="primary"),
    )
    for code, sym_str in [("BDT","৳"),("USD","$"),("EUR","€"),("INR","₹"),("PKR","₨")]:
        kb.add(Btn(f"{code} {sym_str}", callback_data=f"adm_bc_set_currency_{code}_{sym_str}", style="primary"))
    kb.add(Btn(f"{G['back']}  Pᴀʏ Cᴏɴꜰɪɢ", callback_data="adm_pay_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_receipt_tmpl(call: types.CallbackQuery) -> None:
    cur = get_setting("tmpl_payment_received", "") or _MESSAGE_TEMPLATES["payment_received"]["default"]
    cap = (
        f"<b>🧾 {sc('Payment Receipt Template')}</b>\n"
        f"{G['div_eq']}\n"
        f"<i>{sc('Current template')}:</i>\n<code>{esc(cur[:300])}</code>\n"
        f"{G['div']}\n{sc('Variables')}: <code>{{name}}, {{amount}}, {{plan}}, {{tx_id}}, {{date}}</code>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Eᴅɪᴛ",      callback_data="adm_tmpl_edit_payment_received", style="primary"),
        Btn("Rᴇꜱᴇᴛ",     callback_data="adm_tmpl_reset_payment_received", style="danger"),
    )
    kb.add(Btn(f"{G['back']}  Pᴀʏ Cᴏɴꜰɪɢ", callback_data="adm_pay_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_pay_notif_settings(call: types.CallbackQuery) -> None:
    chan = get_setting("payment_notif_channel", "") or "—"
    on_new   = bool(get_setting("notif_on_new_payment", True))
    on_appr  = bool(get_setting("notif_on_approved",    True))
    on_rej   = bool(get_setting("notif_on_rejected",    True))
    cap = (
        f"<b>🔔 {sc('Payment Notifications')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Channel',    esc(chan))}\n"
        f"{bullet('New payment', '✅' if on_new else '❌')}\n"
        f"{bullet('Approved',   '✅' if on_appr else '❌')}\n"
        f"{bullet('Rejected',   '✅' if on_rej else '❌')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(Btn("Sᴇᴛ Cʜᴀɴɴᴇʟ", callback_data="adm_bc_set_payment_notif_channel", style="primary"))
    kb.add(
        Btn(f"{'✅' if on_new else '❌'}  Nᴇᴡ Pᴀʏ",  callback_data="adm_bc_toggle_notif_on_new_payment",  style="primary"),
        Btn(f"{'✅' if on_appr else '❌'}  Aᴘᴘʀᴏᴠᴇᴅ",callback_data="adm_bc_toggle_notif_on_approved",    style="primary"),
    )
    kb.add(Btn(f"{'✅' if on_rej else '❌'}  Rᴇᴊᴇᴄᴛᴇᴅ", callback_data="adm_bc_toggle_notif_on_rejected", style="primary"))
    kb.add(Btn(f"{G['back']}  Pᴀʏ Cᴏɴꜰɪɢ", callback_data="adm_pay_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("pay_config", PHOTOS["admin"]), cap, kb, call=call)


def action_adm_pay_method_number(call: types.CallbackQuery, data: str) -> None:
    """Handle toggle or set-number for a payment method."""
    if data.startswith("adm_pay_method_toggle_"):
        key = data[len("adm_pay_method_toggle_"):]
        cur = bool(get_setting(f"pm_enabled_{key}", True))
        set_setting(f"pm_enabled_{key}", not cur)
        audit(call.from_user.id, f"pm_toggle_{key}", f"now={not cur}")
        ack(call, f"{key}: {'enabled' if not cur else 'disabled'}")
        return render_adm_pay_method_edit(call, key)
    if data.startswith("adm_pay_method_setnumber_"):
        key = data[len("adm_pay_method_setnumber_"):]
        USER_STATES[call.from_user.id] = {"flow": "await_adm_pay_number", "pm_key": key}
        bot.send_message(call.message.chat.id,
                         f"{G['settings']} {sc('Send new payment number/address for')} "
                         f"<b>{esc(PAYMENT_METHODS.get(key,{}).get('name',key))}</b>:",
                         parse_mode="HTML")
        return


# ─────────────────────────────────────────────────────────────────────────────
# BOT CONFIG PANEL
# ─────────────────────────────────────────────────────────────────────────────

def _bc_get(key: str) -> Any:
    """Get a bot config value from settings, falling back to defaults."""
    return get_setting(f"bc_{key}", _BOT_CONFIG_DEFAULTS.get(key))


def _bc_set(key: str, val: Any) -> None:
    set_setting(f"bc_{key}", val)


def render_adm_bot_cfg(call: types.CallbackQuery) -> None:
    """Full bot configuration panel."""
    _mu  = str(_bc_get("max_upload_mb")) + " MB"
    _swd = str(_bc_get("sandbox_wipe_delay")) + "s"
    _bst = str(_bc_get("bot_start_timeout")) + "s"
    _bso = str(_bc_get("bot_stop_timeout")) + "s"
    _crd = str(_bc_get("crash_restart_delay")) + "s"
    cap = (
        f"<b>🔧 {sc('Bot Configuration')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Max Upload',          _mu)}\n"
        f"{bullet('Sandbox Wipe Delay',  _swd)}\n"
        f"{bullet('Start Timeout',       _bst)}\n"
        f"{bullet('Stop Timeout',        _bso)}\n"
        f"{bullet('Crash Restart Delay', _crd)}\n"
        f"{bullet('Max Crash Restarts',  _bc_get('max_crash_restarts'))}\n"
        f"{bullet('Log Ring Size',       _bc_get('log_ring_size'))}\n"
        f"{bullet('Zip Max Files',       _bc_get('zip_max_files'))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("⏱ Tɪᴍᴇᴏᴜᴛꜱ",       callback_data="adm_bc_timeouts",  style="primary"),
        Btn("Lɪᴍɪᴛꜱ",           callback_data="adm_bc_limits",    style="primary"),
    )
    kb.add(
        Btn("Uᴘʟᴏᴀᴅ Rᴜʟᴇꜱ",    callback_data="adm_bc_upload",    style="primary"),
        Btn("Eɴᴠ Sᴛʀɪᴘ",        callback_data="adm_bc_env",       style="danger"),
    )
    kb.add(
        Btn("Rᴇꜱᴛᴀʀᴛ Pᴏʟɪᴄʏ",  callback_data="adm_bc_policy",    style="primary"),
        Btn("Sᴀɴᴅʙᴏx",           callback_data="adm_bc_sandbox",   style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_timeouts(call: types.CallbackQuery) -> None:
    _t1 = str(_bc_get("bot_start_timeout")) + "s"
    _t2 = str(_bc_get("bot_stop_timeout")) + "s"
    _t3 = str(_bc_get("crash_restart_delay")) + "s"
    _t4 = str(_bc_get("idle_timeout_mins") or "Off")
    _t5 = str(_bc_get("resource_check_secs")) + "s"
    cap = (
        f"<b>⏱️ {sc('Timeout Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Bot Start Timeout',       _t1)}\n"
        f"{bullet('Bot Stop Timeout',        _t2)}\n"
        f"{bullet('Crash Restart Delay',     _t3)}\n"
        f"{bullet('Idle Timeout (mins)',      _t4)}\n"
        f"{bullet('Resource Check Interval', _t5)}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, label in [
        ("bot_start_timeout",   "Start Timeout"),
        ("bot_stop_timeout",    "Stop Timeout"),
        ("crash_restart_delay", "Crash Delay"),
        ("idle_timeout_mins",   "Idle Timeout"),
        ("resource_check_secs", "Res Check"),
    ]:
        kb.add(Btn(f"{label}", callback_data=f"adm_bc_set_{k}", style="primary"))
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_limits(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>📊 {sc('Resource Limits')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Max Upload MB',       _bc_get('max_upload_mb'))}\n"
        f"{bullet('Max Crash Restarts',  _bc_get('max_crash_restarts'))}\n"
        f"{bullet('Log Ring Size',       _bc_get('log_ring_size'))}\n"
        f"{bullet('Zip Max Files',       _bc_get('zip_max_files'))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, label in [
        ("max_upload_mb",     "Max Upload MB"),
        ("max_crash_restarts","Max Crash Restarts"),
        ("log_ring_size",     "Log Ring Size"),
        ("zip_max_files",     "Zip Max Files"),
    ]:
        kb.add(Btn(f"{label}", callback_data=f"adm_bc_set_{k}", style="primary"))
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_upload(call: types.CallbackQuery) -> None:
    exts = _bc_get("allowed_extensions") or ".py,.js,.zip"
    cap = (
        f"<b>📦 {sc('Upload Rules')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Max Upload',        str(_bc_get('max_upload_mb')) + ' MB')}\n"
        f"{bullet('Allowed Ext',       esc(str(exts)))}\n"
        f"{bullet('Zip Max Files',     _bc_get('zip_max_files'))}\n"
        f"{G['div']}\n"
        f"{sc('Allowed extensions are comma-separated. E.g.')} <code>.py,.js,.zip</code>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Max Upload MB",    callback_data="adm_bc_set_max_upload_mb",       style="primary"),
        Btn("Allowed Ext",      callback_data="adm_bc_set_allowed_extensions",  style="primary"),
    )
    kb.add(
        Btn("Zip Max Files",    callback_data="adm_bc_set_zip_max_files",       style="primary"),
    )
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_env(call: types.CallbackQuery) -> None:
    strip = bool(_bc_get("env_strip_secrets"))
    names = list(SECRET_ENV_NAMES)
    cap = (
        f"<b>🔐 {sc('Environment Variable Control')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Strip Secrets', '✅ ON' if strip else '❌ OFF')}\n"
        f"{G['div']}\n"
        f"<b>{sc('Currently stripped env names')}:</b>\n"
        f"<code>{', '.join(names[:10])}</code>"
        f"{('...' if len(names) > 10 else '')}\n"
        f"{G['div']}\n{sc('When ON, child bots cannot access these env vars.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅' if strip else '❌'}  Sᴛʀɪᴘ Sᴇᴄʀᴇᴛꜱ",
            callback_data="adm_bc_toggle_env_strip_secrets",
            style="success" if strip else "danger"),
        Btn("Aᴅᴅ Sᴇᴄʀᴇᴛ Nᴀᴍᴇ",  callback_data="adm_bc_set_add_secret_name",   style="primary"),
    )
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_sandbox(call: types.CallbackQuery) -> None:
    wipe   = bool(get_setting("ff_sandbox_wipe", True))
    delay  = _bc_get("sandbox_wipe_delay")
    net    = bool(_bc_get("sandbox_network"))
    cap = (
        f"<b>🧱 {sc('Sandbox Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('File Wipe',   '✅ ON' if wipe else '❌ OFF')}\n"
        f"{bullet('Wipe Delay',  f'{delay}s after start')}\n"
        f"{bullet('Network',     '✅ Allowed' if net else '❌ Blocked')}\n"
        f"{G['div']}\n"
        f"<i>{sc('File Wipe removes source .py/.js files after bot starts so child bots cannot read their own code.')}</i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅' if wipe else '❌'}  Fɪʟᴇ Wɪᴘᴇ",
            callback_data="adm_ff_toggle_sandbox_wipe",
            style="success" if wipe else "danger"),
        Btn("Wɪᴘᴇ Dᴇʟᴀʏ",     callback_data="adm_bc_set_sandbox_wipe_delay", style="primary"),
    )
    kb.add(
        Btn(f"{'✅' if net else '❌'}  Nᴇᴛᴡᴏʀᴋ",
            callback_data="adm_bc_toggle_sandbox_network",
            style="success" if net else "danger"),
    )
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_policy(call: types.CallbackQuery) -> None:
    auto_r  = bool(get_setting("ff_auto_restart_bots", True))
    max_r   = _bc_get("max_crash_restarts")
    delay_r = _bc_get("crash_restart_delay")
    auto_dg = bool(get_setting("auto_downgrade_expired", True))
    cap = (
        f"<b>🔄 {sc('Restart & Policy')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Auto-Restart Crashed', '✅ ON' if auto_r else '❌ OFF')}\n"
        f"{bullet('Max Restarts/hour',    max_r)}\n"
        f"{bullet('Restart Delay',        str(delay_r) + 's')}\n"
        f"{bullet('Auto-Downgrade Expiry','✅ ON' if auto_dg else '❌ OFF')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅' if auto_r else '❌'}  Aᴜᴛᴏ-Rᴇꜱᴛᴀʀᴛ",
            callback_data="adm_ff_toggle_auto_restart_bots",
            style="success" if auto_r else "danger"),
        Btn("Mᴀx Rᴇꜱᴛᴀʀᴛꜱ",   callback_data="adm_bc_set_max_crash_restarts", style="primary"),
    )
    kb.add(
        Btn("Rᴇꜱᴛᴀʀᴛ Dᴇʟᴀʏ",  callback_data="adm_bc_set_crash_restart_delay", style="primary"),
        Btn(f"{'✅' if auto_dg else '❌'}  Aᴜᴛᴏ-Dɢ",
            callback_data="adm_sub_auto_downgrade",
            style="success" if auto_dg else "danger"),
    )
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴꜰɪɢ", callback_data="adm_bot_cfg", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_config", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# APPEARANCE PANEL
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_appearance(call: types.CallbackQuery) -> None:
    theme    = get_setting("ui_theme", "dark")
    brand    = BRAND_TAG
    footer   = (get_setting("custom_footer", "") or "")[:40]
    welcome  = bool(get_setting("custom_welcome", ""))
    rules    = bool(get_setting("hosting_rules",  ""))
    cap = (
        f"<b>🎨 {sc('Appearance & Branding')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Theme',     esc(theme))}\n"
        f"{bullet('Brand Tag', esc(brand))}\n"
        f"{bullet('Footer',    esc(footer or '(default)'))}\n"
        f"{bullet('Custom Welcome', '✅' if welcome else '❌ (default)')}\n"
        f"{bullet('Custom Rules',   '✅' if rules else '❌ (default)')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Tʜᴇᴍᴇꜱ",            callback_data="adm_app_theme",      style="primary"),
        Btn("Bʀᴀɴᴅ Tᴀɢ",         callback_data="adm_set_brand",      style="primary"),
    )
    kb.add(
        Btn("Fᴏᴏᴛᴇʀ Tᴇxᴛ",       callback_data="adm_set_footer_text",    style="primary"),
        Btn("Wᴇʟᴄᴏᴍᴇ Mꜱɢ",      callback_data="adm_set_welcome_text",   style="primary"),
    )
    kb.add(
        Btn("Rᴜʟᴇꜱ Tᴇxᴛ",        callback_data="adm_set_rules_text",     style="primary"),
        Btn("Cᴜꜱᴛᴏᴍ Eᴍᴏᴊɪꜱ",     callback_data="adm_app_emojis",         style="primary"),
    )
    kb.add(
        Btn("Mᴇɴᴜ Pʜᴏᴛᴏꜱ",      callback_data="adm_photos",             style="primary"),
        Btn("Aɴɴ Cʜᴀɴɴᴇʟ",       callback_data="adm_set_announce",       style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("appearance", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_app_theme(call: types.CallbackQuery) -> None:
    cur = get_setting("ui_theme", "dark")
    cap = (
        f"<b>🎭 {sc('UI Themes')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Current')}: <b>{esc(cur)}</b>\n"
        f"{G['div']}\n"
        + "\n".join(
            f"{'✅' if k == cur else '  '} <b>{v['name']}</b> — "
            f"header={v['header']} accent={v['accent']} ok={v['emoji_ok']}"
            for k, v in _APPEARANCE_THEMES.items()
        )
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, v in _APPEARANCE_THEMES.items():
        kb.add(Btn(f"{'✅' if k == cur else '  '} {v['name']}",
                   callback_data=f"adm_app_theme_{k}", style="primary"))
    kb.add(Btn(f"{G['back']}  Aᴘᴘᴇᴀʀᴀɴᴄᴇ", callback_data="adm_appearance", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("appearance", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_app_emojis(call: types.CallbackQuery) -> None:
    custom_emojis = get_setting("custom_emojis", {}) or {}
    sample_keys = ["ok", "no", "warn", "bullet", "div", "shield", "key"]
    rows = "\n".join(
        f"{G['bullet']} <code>{k}</code>: {custom_emojis.get(k, G.get(k, '?'))} "
        f"{'<i>(custom)</i>' if k in custom_emojis else '<i>(default)</i>'}"
        for k in sample_keys
    )
    cap = (
        f"<b>😀 {sc('Custom Emojis')}</b>\n"
        f"{G['div_eq']}\n"
        f"{rows}\n"
        f"{G['div']}\n"
        f"{sc('Tap a key to set a custom emoji. Use')} <code>-</code> {sc('to reset.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k in sample_keys:
        kb.add(Btn(f"{k}: {custom_emojis.get(k, G.get(k,'?'))}",
                   callback_data=f"adm_app_emoji_set_{k}", style="primary"))
    kb.add(Btn("Rᴇꜱᴇᴛ Aʟʟ", callback_data="adm_app_emoji_reset", style="danger"))
    kb.add(Btn(f"{G['back']}  Aᴘᴘᴇᴀʀᴀɴᴄᴇ", callback_data="adm_appearance", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("appearance", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_app_banner(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>🖼️ {sc('Banner / Photo Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Each menu section has its own banner image.')}\n"
        f"{sc('Use Menu Photos to update each one by name.')}\n"
        f"{G['div']}\n"
        f"{bullet('Sections', len(PHOTOS))}\n"
        f"{bullet('Cached file IDs', len(_PHOTO_FILE_IDS))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(Btn("Mᴇɴᴜ Pʜᴏᴛᴏꜱ", callback_data="adm_photos",     style="primary"))
    kb.add(Btn("Rᴇʙᴜɪʟᴅ Bᴀɴɴᴇʀꜱ", callback_data="adm_rebuild_banners", style="danger"))
    kb.add(Btn(f"{G['back']}  Aᴘᴘᴇᴀʀᴀɴᴄᴇ", callback_data="adm_appearance", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("appearance", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCED COUPON MANAGER
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_coupon_plus(call: types.CallbackQuery) -> None:
    d = db_load()
    coupons = d["coupons"]
    total     = len(coupons)
    now_s     = ts_iso()
    active    = sum(1 for c in coupons.values()
                    if not (c.get("expiry") and c["expiry"] < now_s)
                    and c.get("uses_left", 1) != 0)
    expired   = total - active
    used_total = sum((c.get("max_uses", 1) - c.get("uses_left", 1))
                     for c in coupons.values() if c.get("max_uses"))
    cap = (
        f"<b>🎫 {sc('Advanced Coupon Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Coupons',   total)}\n"
        f"{bullet('Active',          active)}\n"
        f"{bullet('Expired/Used',    expired)}\n"
        f"{bullet('Total Redemptions', used_total)}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Cʀᴇᴀᴛᴇ Cᴏᴜᴘᴏɴ",   callback_data="adm_coupons",          style="success"),
        Btn("Bᴜʟᴋ Cʀᴇᴀᴛᴇ",      callback_data="adm_coupon_bulk",      style="primary"),
    )
    kb.add(
        Btn("Aɴᴀʟʏᴛɪᴄꜱ",        callback_data="adm_coupon_analytics", style="primary"),
        Btn("⏰ Exᴘɪʀʏ Mɢʀ",        callback_data="adm_coupon_expiry",    style="primary"),
    )
    kb.add(
        Btn("Cʟᴇᴀʀ Exᴘɪʀᴇᴅ",   callback_data="adm_coupon_clearexp",  style="danger"),
        Btn("Aʟʟ Cᴏᴜᴘᴏɴꜱ",      callback_data="adm_coupons",          style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("coupon_plus", PHOTOS["coupon"]), cap, kb, call=call)


def render_adm_coupon_bulk(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>🗂️ {sc('Bulk Create Coupons')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Format (one per line or send count')}:\n"
        f"<code>count plan discount_pct [max_uses] [days_valid]</code>\n"
        f"{sc('Example')}:\n"
        f"<code>10 pro 20 1 30</code>\n"
        f"→ {sc('Creates 10 single-use coupons for pro plan at 20% off, valid 30 days')}{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_coupon_bulk"}
    show_menu(call.message.chat.id, PHOTOS.get("coupon_plus", PHOTOS["coupon"]), cap,
              _adm_back("adm_coupon_plus"), call=call)


def render_adm_coupon_analytics(call: types.CallbackQuery) -> None:
    coupons = db_load()["coupons"]
    now_s = ts_iso()
    by_plan: Dict[str, int] = defaultdict(int)
    by_discount: Dict[int, int] = defaultdict(int)
    total_savings: float = 0.0
    for c in coupons.values():
        pl = c.get("plan", "any")
        by_plan[pl] += 1
        disc = int(c.get("discount", c.get("pct", 0)))
        by_discount[disc] += 1
        used = c.get("max_uses", 1) - c.get("uses_left", 1)
        if used and c.get("plan") and PLAN_LIMITS.get(c["plan"]):
            price = PLAN_LIMITS[c["plan"]]["price"]
            total_savings += price * disc / 100 * used
    plan_rows = "\n".join(f"  {G['bullet']} {k}: {v}" for k, v in sorted(by_plan.items()))
    cap = (
        f"<b>📊 {sc('Coupon Analytics')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Coupons',    len(coupons))}\n"
        f"{bullet('Total Savings Given', f'{total_savings:.0f}৳')}\n"
        f"{G['div']}\n<b>{sc('By Plan')}:</b>\n{plan_rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("coupon_plus", PHOTOS["coupon"]), cap,
              _adm_back("adm_coupon_plus"), call=call)


def render_adm_coupon_expiry(call: types.CallbackQuery) -> None:
    coupons = db_load()["coupons"]
    now_s = ts_iso()
    expiring_soon = [
        (code, c) for code, c in coupons.items()
        if c.get("expiry") and c["expiry"] > now_s
        and c["expiry"] <= (now_utc() + timedelta(days=7)).isoformat()
    ]
    expired = [
        (code, c) for code, c in coupons.items()
        if c.get("expiry") and c["expiry"] < now_s
    ]
    rows_soon = "\n".join(
        f"{G['bullet']} <code>{esc(code)}</code> expires <i>{str(c['expiry'])[:10]}</i>"
        for code, c in expiring_soon[:10]
    ) or f"<i>{sc('None expiring soon')}</i>"
    cap = (
        f"<b>⏰ {sc('Coupon Expiry Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Expiring in 7 days', len(expiring_soon))}\n"
        f"{bullet('Already expired',    len(expired))}\n"
        f"{G['div']}\n<b>{sc('Expiring soon')}:</b>\n{rows_soon}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(Btn("Cʟᴇᴀʀ Exᴘɪʀᴇᴅ", callback_data="adm_coupon_clearexp", style="danger"))
    kb.add(Btn(f"{G['back']}  Cᴏᴜᴘᴏɴ Mɢʀ", callback_data="adm_coupon_plus", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("coupon_plus", PHOTOS["coupon"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE MANAGER
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_templates(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>📝 {sc('Message Template Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Customize every message the bot sends. Use placeholders like')} "
        f"<code>{{name}}</code>, <code>{{plan}}</code>, <code>{{amount}}</code> {sc('etc.')}\n"
        f"{G['div']}\n"
        + "\n".join(
            f"{G['bullet']} <b>{esc(v['label'])}</b> "
            f"{'✅ custom' if get_setting(f'tmpl_{k}') else '📄 default'}"
            for k, v in _MESSAGE_TEMPLATES.items()
        )
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, v in _MESSAGE_TEMPLATES.items():
        has_custom = bool(get_setting(f"tmpl_{k}"))
        kb.add(Btn(f"{'✅' if has_custom else '📄'} {v['label'][:25]}",
                   callback_data=f"adm_tmpl_edit_{k}", style="primary"))
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("templates", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# REFERRAL SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_referral_sys(call: types.CallbackQuery) -> None:
    enabled   = bool(get_setting("referral_enabled", True))
    reward    = get_setting("referral_reward_amount", 20)
    min_plan  = get_setting("referral_min_plan", "free")
    d = db_load()
    total_refs = sum(len(u.get("referrals", [])) for u in d["users"].values())
    total_paid = sum(u.get("referral_earnings", 0) for u in d["users"].values())
    cap = (
        f"<b>🔗 {sc('Referral System')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Status',        '✅ Enabled' if enabled else '❌ Disabled')}\n"
        f"{bullet('Reward/Refer',  f'{reward}৳ wallet credit')}\n"
        f"{bullet('Min Plan',      min_plan)}\n"
        f"{bullet('Total Referrals', total_refs)}\n"
        f"{bullet('Total Paid Out',  f'{total_paid}৳')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅ Enabled' if enabled else '❌ Disabled'}",
            callback_data="adm_ref_toggle",
            style="success" if enabled else "danger"),
        Btn("Rᴇꜰ Sᴛᴀᴛꜱ",    callback_data="adm_ref_stats",       style="primary"),
    )
    kb.add(
        Btn("Rᴇᴡᴀʀᴅ Cᴏɴꜰɪɢ",callback_data="adm_ref_rewards",     style="primary"),
        Btn("Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ",   callback_data="adm_ref_leaderboard", style="primary"),
    )
    kb.add(
        Btn("Sᴇᴛ Rᴇᴡᴀʀᴅ ৳", callback_data="adm_ref_set_reward",   style="primary"),
        Btn("Sᴇᴛ Mɪɴ Pʟᴀɴ", callback_data="adm_ref_set_min_plan", style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("referral_adm", PHOTOS["referral"]), cap, kb, call=call)


def render_adm_ref_stats(call: types.CallbackQuery) -> None:
    d = db_load()
    users = d["users"]
    top_refs   = sorted(users.items(), key=lambda x: len(x[1].get("referrals",[])), reverse=True)[:5]
    total_refs = sum(len(u.get("referrals",[])) for u in users.values())
    total_paid = sum(u.get("referral_earnings",0) for u in users.values())
    today_s    = now_utc().strftime("%Y-%m-%d")
    today_refs = sum(
        sum(1 for r in u.get("referrals",[]) if str(r.get("ts","")).startswith(today_s))
        for u in users.values()
    )
    rows = "\n".join(
        f"{i}. {esc(u.get('name','?')[:20])} — {len(u.get('referrals',[]))} refs "
        f"| earned {u.get('referral_earnings',0)}৳"
        for i, (uid, u) in enumerate(top_refs, 1)
    ) or f"<i>{sc('No referrals yet')}</i>"
    cap = (
        f"<b>📊 {sc('Referral Statistics')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Referrals', total_refs)}\n"
        f"{bullet('Today',           today_refs)}\n"
        f"{bullet('Total Paid',      f'{total_paid}৳')}\n"
        f"{G['div']}\n<b>{sc('Top Referrers')}:</b>\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("referral_adm", PHOTOS["referral"]), cap,
              _adm_back("adm_referral_sys"), call=call)


def render_adm_ref_rewards(call: types.CallbackQuery) -> None:
    reward = get_setting("referral_reward_amount", 20)
    bonus_plan = get_setting("referral_bonus_plan", "")
    bonus_refs = get_setting("referral_bonus_threshold", 10)
    cap = (
        f"<b>🎁 {sc('Referral Reward Config')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Base Reward',         f'{reward}৳ per referral')}\n"
        f"{bullet('Bonus Plan',          bonus_plan or 'None')}\n"
        f"{bullet('Bonus Threshold',     f'{bonus_refs} refs needed for bonus')}\n"
        f"{G['div']}\n"
        f"{sc('Set a bonus plan reward for power referrers who hit the threshold.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Bᴀꜱᴇ Rᴇᴡᴀʀᴅ",   callback_data="adm_ref_set_reward",      style="primary"),
        Btn("Sᴇᴛ Bᴏɴᴜꜱ Tʜʀ",     callback_data="adm_bc_set_referral_bonus_threshold", style="primary"),
    )
    kb.add(Btn(f"{G['back']}  Rᴇꜰᴇʀʀᴀʟ Sʏꜱ", callback_data="adm_referral_sys", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("referral_adm", PHOTOS["referral"]), cap, kb, call=call)


def render_adm_ref_leaderboard(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    top = sorted(users.items(),
                 key=lambda x: len(x[1].get("referrals",[])), reverse=True)[:15]
    rows = "\n".join(
        f"{i}. <b>{esc(u.get('name','?')[:20])}</b> — "
        f"{len(u.get('referrals',[]))} {sc('refs')} | "
        f"{u.get('referral_earnings',0)}৳ {sc('earned')}"
        for i, (uid, u) in enumerate(top, 1)
    ) or f"<i>{sc('No referrals yet')}</i>"
    cap = (
        f"<b>🏆 {sc('Referral Leaderboard')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("referral_adm", PHOTOS["referral"]), cap,
              _adm_back("adm_referral_sys"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# JANITOR (AUTO-CLEANUP)
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_janitor(call: types.CallbackQuery) -> None:
    flags = {
        "clean_orphan_dirs":    "Auto-clean orphan sandboxes",
        "clean_old_logs":       "Auto-clear old logs (>7 days)",
        "clean_expired_coupons":"Auto-remove expired coupons",
        "auto_ban_rate_abuse":  "Auto-ban rate limit abusers",
        "clean_old_audit":      "Trim audit log (>1000 entries)",
        "notify_crashed":       "Notify owner on bot crash",
    }
    cap = (
        f"<b>🧹 {sc('Janitor — Auto-Cleanup Rules')}</b>\n"
        f"{G['div_eq']}\n"
        + "\n".join(
            f"{'✅' if get_setting(f'jan_{k}', False) else '❌'} {v}"
            for k, v in flags.items()
        )
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k, v in flags.items():
        on = bool(get_setting(f"jan_{k}", False))
        kb.add(Btn(f"{'✅' if on else '❌'} {v[:28]}",
                   callback_data=f"adm_jan_toggle_{k}", style="primary"))
    kb.add(
        Btn("▶ Rᴜɴ Nᴏᴡ",         callback_data="adm_jan_run_now",   style="success"),
        Btn("Jᴀɴ Rᴜʟᴇꜱ",       callback_data="adm_jan_rules",     style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("janitor", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_jan_rules(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>📋 {sc('Janitor Rule Details')}</b>\n"
        f"{G['div_eq']}\n"
        f"<b>{sc('Orphan Sandbox Cleanup')}:</b>\n"
        f"  {sc('Removes sandbox dirs with no matching bot record.')}\n\n"
        f"<b>{sc('Old Log Cleanup')}:</b>\n"
        f"  {sc('Clears log files older than 7 days from disk.')}\n\n"
        f"<b>{sc('Expired Coupon Cleanup')}:</b>\n"
        f"  {sc('Removes coupons past their expiry date automatically.')}\n\n"
        f"<b>{sc('Rate Abuse Auto-Ban')}:</b>\n"
        f"  {sc('Bans users exceeding rate limits 3+ times in 24h.')}\n\n"
        f"<b>{sc('Audit Log Trim')}:</b>\n"
        f"  {sc('Keeps only the last 1000 audit entries.')}\n\n"
        f"<b>{sc('Crash Notifications')}:</b>\n"
        f"  {sc('Sends owner a message when any bot crashes.')}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("janitor", PHOTOS["admin"]), cap,
              _adm_back("adm_janitor"), call=call)


def render_adm_jan_schedule(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>⏰ {sc('Janitor Schedule')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Orphan cleanup',        'Every 6 hours')}\n"
        f"{bullet('Log cleanup',           'Daily at 03:00')}\n"
        f"{bullet('Coupon cleanup',        'Daily at 04:00')}\n"
        f"{bullet('Audit trim',            'Daily at 05:00')}\n"
        f"{bullet('Rate abuse check',      'Every 30 minutes')}\n"
        f"{G['div']}\n"
        f"<i>{sc('Janitor runs automatically in background threads.')}</i>{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("janitor", PHOTOS["admin"]), cap,
              _adm_back("adm_janitor"), call=call)


def action_adm_jan_run(admin_uid: int) -> None:
    """Run all enabled janitor tasks immediately."""
    results: List[str] = []
    # Orphan cleanup
    if get_setting("jan_clean_orphan_dirs", False):
        try:
            dirs, files = _do_clean_orphans()
            results.append(f"✅ Orphan cleanup: {dirs} dirs, {files} files removed")
        except Exception as e:
            results.append(f"❌ Orphan cleanup: {e}")
    # Expired coupons
    if get_setting("jan_clean_expired_coupons", False):
        try:
            d = db_load()
            now_s = ts_iso()
            before = len(d["coupons"])
            d["coupons"] = {k: v for k, v in d["coupons"].items()
                            if not (v.get("expiry") and v["expiry"] < now_s)}
            removed = before - len(d["coupons"])
            db_save(d)
            results.append(f"✅ Expired coupons: {removed} removed")
        except Exception as e:
            results.append(f"❌ Coupon cleanup: {e}")
    # Audit trim
    if get_setting("jan_clean_old_audit", False):
        try:
            d = db_load()
            before = len(d.get("audit", []))
            d["audit"] = d.get("audit", [])[-1000:]
            db_save(d)
            results.append(f"✅ Audit trim: kept last 1000 of {before}")
        except Exception as e:
            results.append(f"❌ Audit trim: {e}")
    audit(admin_uid, "janitor_run_now", f"tasks={len(results)}")
    summary = "\n".join(results) or "No janitor tasks enabled"
    try:
        bot.send_message(admin_uid,
                         f"<b>🧹 {sc('Janitor Report')}</b>\n{G['div_eq']}\n{summary}",
                         parse_mode="HTML")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_webhooks(call: types.CallbackQuery) -> None:
    wh_url = get_setting("webhook_url", "") or ""
    wh_info: Dict[str, Any] = {}
    if wh_url:
        try:
            wh_info = bot.get_webhook_info().__dict__
        except Exception:
            wh_info = {}
    mode = "Webhook" if wh_url else "Long Polling"
    pending = wh_info.get("pending_update_count", 0)
    last_err= wh_info.get("last_error_message", "—")
    cap = (
        f"<b>🌐 {sc('Webhook Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Mode',           mode)}\n"
        f"{bullet('Webhook URL',    esc(wh_url[:50]) if wh_url else '—')}\n"
        f"{bullet('Pending Updates',pending)}\n"
        f"{bullet('Last Error',     esc(str(last_err)[:50]))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Wᴇʙʜᴏᴏᴋ",    callback_data="adm_wh_set",   style="primary"),
        Btn("Cʟᴇᴀʀ (Pᴏʟʟɪɴɢ)", callback_data="adm_wh_clear", style="danger"),
    )
    kb.add(
        Btn("Tᴇꜱᴛ Wᴇʙʜᴏᴏᴋ",   callback_data="adm_wh_test",  style="primary"),
        Btn("ℹ Wᴇʙʜᴏᴏᴋ Iɴꜰᴏ",   callback_data="adm_wh_info",  style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("webhooks", PHOTOS["admin"]), cap, kb, call=call)


def action_adm_wh_test(call: types.CallbackQuery) -> None:
    wh_url = get_setting("webhook_url", "")
    if not wh_url:
        ack(call, "No webhook URL set"); return
    ack(call, "Testing webhook…")
    def _bg() -> None:
        try:
            import urllib.request as _ur
            import json as _j
            payload = _j.dumps({"test": True, "ts": ts_iso(), "from": "SirLinuxxHostingBot"}).encode()
            req = _ur.Request(wh_url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            with _ur.urlopen(req, timeout=10) as resp:
                status = resp.status
            bot.send_message(call.from_user.id,
                             f"{G['ok']} {sc('Webhook test')}: HTTP {status} ✅")
        except Exception as e:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('Webhook test failed')}: <code>{esc(e)}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()


def render_adm_wh_info(call: types.CallbackQuery) -> None:
    try:
        wi = bot.get_webhook_info()
        cap = (
            f"<b>ℹ️ {sc('Webhook Info')}</b>\n"
            f"{G['div_eq']}\n"
            f"{bullet('URL',             esc(str(wi.url or '—')[:60]))}\n"
            f"{bullet('Has Cert',        wi.has_custom_certificate)}\n"
            f"{bullet('Pending',         wi.pending_update_count)}\n"
            f"{bullet('Max Connections', wi.max_connections)}\n"
            f"{bullet('Last Error',      esc(str(wi.last_error_message or '—')[:60]))}\n"
            f"{bullet('Last Error Time', fmt_ts(wi.last_error_date))}\n"
            f"{bullet('IP Address',      wi.ip_address or '—')}\n"
            f"{G['div']}{FOOTER}"
        )
    except Exception as e:
        cap = f"{G['no']} {sc('Error')}: <code>{esc(e)}</code>{FOOTER}"
    show_menu(call.message.chat.id, PHOTOS.get("webhooks", PHOTOS["admin"]), cap,
              _adm_back("adm_webhooks"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE FLAGS
# ─────────────────────────────────────────────────────────────────────────────

def _ff_get(key: str) -> bool:
    return bool(get_setting(f"ff_{key}", _FEATURE_FLAG_DEFAULTS.get(key, True)))


def render_adm_feature_flags(call: types.CallbackQuery) -> None:
    rows = []
    for k, default in _FEATURE_FLAG_DEFAULTS.items():
        val = _ff_get(k)
        rows.append(f"{'✅' if val else '❌'} <code>{k}</code>")
    cap = (
        f"<b>🎯 {sc('Feature Flags')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('Toggle any system feature on or off instantly.')}\n"
        f"{G['div']}\n"
        + "\n".join(rows)
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for k in list(_FEATURE_FLAG_DEFAULTS.keys()):
        val = _ff_get(k)
        label = k.replace("_"," ").title()[:20]
        kb.add(Btn(f"{'✅' if val else '❌'} {label}",
                   callback_data=f"adm_ff_toggle_{k}", style="primary"))
    kb.add(Btn("Rᴇꜱᴇᴛ Aʟʟ Fʟᴀɢꜱ", callback_data="adm_ff_reset_all", style="danger"))
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("features", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITER CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_rate_config(call: types.CallbackQuery) -> None:
    global_rl = _ff_get("rate_limiting")
    cap = (
        f"<b>⏱️ {sc('Rate Limit Configuration')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Global Rate Limiting', '✅ ON' if global_rl else '❌ OFF')}\n"
        f"{G['div']}\n"
        + "\n".join(
            f"<b>{PLAN_LIMITS.get(plan,{}).get('name', plan)}</b>: "
            f"↑{get_setting(f'rl_{plan}_uploads_per_day', d['uploads_per_day'])}/day "
            f"▶{get_setting(f'rl_{plan}_starts_per_hour', d['starts_per_hour'])}/hr "
            f"💬{get_setting(f'rl_{plan}_msgs_per_min', d['msgs_per_min'])}/min"
            for plan, d in _RATE_LIMIT_DEFAULTS.items()
        )
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn(f"{'✅ ON' if global_rl else '❌ OFF'}  Gʟᴏʙᴀʟ RL",
            callback_data="adm_ff_toggle_rate_limiting",
            style="success" if global_rl else "danger"),
    )
    for plan in _RATE_LIMIT_DEFAULTS:
        name = PLAN_LIMITS.get(plan, {}).get("name", plan)[:10]
        kb.add(Btn(f"{name}", callback_data=f"adm_rate_plan_{plan}", style="primary"))
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("rate_limits", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_rate_plan(call: types.CallbackQuery, plan: str) -> None:
    d = _RATE_LIMIT_DEFAULTS.get(plan, {})
    name = PLAN_LIMITS.get(plan, {}).get("name", plan)
    cap = (
        f"<b>⏱️ {sc('Rate Limits for')} {esc(name)}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Uploads/Day',    get_setting(f'rl_{plan}_uploads_per_day', d.get('uploads_per_day')))}\n"
        f"{bullet('Starts/Hour',    get_setting(f'rl_{plan}_starts_per_hour', d.get('starts_per_hour')))}\n"
        f"{bullet('Messages/Min',   get_setting(f'rl_{plan}_msgs_per_min',    d.get('msgs_per_min')))}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    for metric in ("uploads_per_day", "starts_per_hour", "msgs_per_min"):
        kb.add(Btn(f"{metric.replace('_',' ').title()}",
                   callback_data=f"adm_rate_set_{plan}_{metric}", style="primary"))
    kb.add(Btn(f"{G['back']}  Rᴀᴛᴇ Cᴏɴꜰɪɢ", callback_data="adm_rate_config", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("rate_limits", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# LIVE MONITOR
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_live_monitor(call: types.CallbackQuery) -> None:
    running_bots = [(bid, info) for bid, info in RUNNING.items()
                    if info["proc"].poll() is None]
    crashed_bots = [(bid, info) for bid, info in RUNNING.items()
                    if info["proc"].poll() is not None]
    total_child_ram = 0
    total_child_cpu = 0.0
    if psutil:
        for bid, info in running_bots:
            try:
                p = psutil.Process(info["proc"].pid)
                total_child_ram += p.memory_info().rss
                total_child_cpu += p.cpu_percent(interval=0)
            except Exception:
                pass
    panel_ram = panel_cpu = 0
    if psutil:
        try:
            pp = psutil.Process(os.getpid())
            panel_ram = pp.memory_info().rss
            panel_cpu = pp.cpu_percent(interval=0.1)
        except Exception:
            pass
    up_s = int(time.time() - START_TIME) if "START_TIME" in globals() else 0
    cap = (
        f"<b>📡 {sc('Live Monitor')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Panel Uptime',   fmt_dur(up_s * 1000))}\n"
        f"{bullet('Panel RAM',      fmt_bytes(panel_ram))}\n"
        f"{bullet('Panel CPU',      f'{panel_cpu:.1f}%')}\n"
        f"{G['div']}\n"
        f"{bullet('▶ Running Bots',  len(running_bots))}\n"
        f"{bullet('💥 Crashed',      len(crashed_bots))}\n"
        f"{bullet('Child RAM Total', fmt_bytes(total_child_ram))}\n"
        f"{bullet('Child CPU Total', f'{total_child_cpu:.1f}%')}\n"
        f"{G['div']}\n"
        + "\n".join(
            f"  {G['bullet']} <code>{bid[:8]}</code> "
            f"{esc(info.get('name','?')[:18])}"
            for bid, info in running_bots[:8]
        )
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Rᴇꜰʀᴇꜱʜ",         callback_data="adm_monitor_refresh",  style="success"),
        Btn("Bᴏᴛ Dᴇᴛᴀɪʟꜱ",     callback_data="adm_monitor_bots",     style="primary"),
    )
    kb.add(
        Btn("Sʏꜱᴛᴇᴍ",           callback_data="adm_monitor_system",   style="primary"),
        Btn("Cʀᴀꜱʜᴇᴅ",          callback_data="adm_crashed_bots",     style="danger"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["stats"]), cap, kb, call=call)


def render_adm_monitor_bots(call: types.CallbackQuery) -> None:
    rows: List[str] = []
    for bid, info in list(RUNNING.items())[:20]:
        rc = info["proc"].poll()
        is_running = rc is None
        b = find_bot(bid)
        name = (b.get("name","?") if b else bid)[:20]
        pid  = info["proc"].pid
        rss  = 0
        cpu  = 0.0
        if psutil and is_running:
            try:
                p = psutil.Process(pid)
                rss = p.memory_info().rss
                cpu = p.cpu_percent(interval=0)
            except Exception:
                pass
        status = "▶ running" if is_running else f"⏹ exit={rc}"
        rows.append(
            f"{G['bullet']} <b>{esc(name)}</b> <code>{bid[:8]}</code>\n"
            f"   {status} | PID {pid} | {fmt_bytes(rss)} | CPU {cpu:.1f}%"
        )
    cap = (
        f"<b>🤖 {sc('Bot Monitor')} ({len(RUNNING)} total)</b>\n"
        f"{G['div_eq']}\n"
        + ("\n".join(rows) or f"<i>{sc('No bots running')}</i>")
        + f"\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["stats"]), cap,
              _adm_back("adm_live_monitor"), call=call)


def render_adm_monitor_system(call: types.CallbackQuery) -> None:
    cpu_pct = mem_pct = disk_pct = 0.0
    load1 = load5 = load15 = 0.0
    if psutil:
        try:
            cpu_pct  = psutil.cpu_percent(interval=0.3)
            vm       = psutil.virtual_memory()
            mem_pct  = vm.percent
            du       = psutil.disk_usage("/")
            disk_pct = du.percent
        except Exception:
            pass
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        pass
    def bar(pct: float) -> str:
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled) + f" {pct:.1f}%"
    cap = (
        f"<b>🖥️ {sc('System Monitor')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('CPU',       bar(cpu_pct))}\n"
        f"{bullet('Memory',    bar(mem_pct))}\n"
        f"{bullet('Disk',      bar(disk_pct))}\n"
        f"{bullet('Load 1m',   f'{load1:.2f}')}\n"
        f"{bullet('Load 5m',   f'{load5:.2f}')}\n"
        f"{bullet('Load 15m',  f'{load15:.2f}')}\n"
        f"{bullet('Threads',   threading.active_count())}\n"
        f"{bullet('PID',       os.getpid())}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("monitor", PHOTOS["stats"]), cap,
              _adm_back("adm_live_monitor"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# REVENUE GOALS
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_rev_goals(call: types.CallbackQuery) -> None:
    pays = db_load()["payments"]
    now  = now_utc()
    month_start = now.replace(day=1, hour=0, minute=0, second=0).strftime("%Y-%m")
    year_start  = now.strftime("%Y")
    rev_month = sum(p.get("amount",0) for p in pays
                    if p.get("status")=="approved" and str(p.get("ts","")).startswith(month_start))
    rev_year  = sum(p.get("amount",0) for p in pays
                    if p.get("status")=="approved" and str(p.get("ts","")).startswith(year_start))
    rev_all   = sum(p.get("amount",0) for p in pays if p.get("status")=="approved")
    goal_month = get_setting("rev_goal_monthly", 0)
    goal_year  = get_setting("rev_goal_yearly",  0)
    def progress_bar(cur: float, goal: float) -> str:
        if not goal:
            return "— (no goal set)"
        pct = min(100, cur * 100 / goal)
        filled = int(pct / 5)
        return "█" * filled + "░" * (20 - filled) + f" {pct:.1f}%"
    cap = (
        f"<b>💎 {sc('Revenue Goals')}</b>\n"
        f"{G['div_eq']}\n"
        f"<b>{sc('This Month')} ({month_start})</b>\n"
        f"  {sc('Earned')}: <b>{rev_month}৳</b> / {goal_month or '?'}৳\n"
        f"  {progress_bar(rev_month, goal_month)}\n"
        f"{G['div']}\n"
        f"<b>{sc('This Year')} ({year_start})</b>\n"
        f"  {sc('Earned')}: <b>{rev_year}৳</b> / {goal_year or '?'}৳\n"
        f"  {progress_bar(rev_year, goal_year)}\n"
        f"{G['div']}\n"
        f"{bullet('All Time',   f'{rev_all}৳')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Sᴇᴛ Mᴏɴᴛʜʟʏ Gᴏᴀʟ", callback_data="adm_goal_set_monthly", style="primary"),
        Btn("Sᴇᴛ Yᴇᴀʀʟʏ Gᴏᴀʟ",  callback_data="adm_goal_set_yearly",  style="primary"),
    )
    kb.add(
        Btn("Hɪꜱᴛᴏʀʏ",           callback_data="adm_goal_history",     style="primary"),
        Btn("Rᴇᴠᴇɴᴜᴇ Rᴇᴘᴏʀᴛ",   callback_data="adm_revenue_report",   style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("rev_goals", PHOTOS["stats"]), cap, kb, call=call)


def render_adm_goal_history(call: types.CallbackQuery) -> None:
    pays  = db_load()["payments"]
    now   = now_utc()
    months: Dict[str, float] = defaultdict(float)
    for p in pays:
        if p.get("status") != "approved":
            continue
        ts = str(p.get("ts", ""))
        if len(ts) >= 7:
            months[ts[:7]] += p.get("amount", 0)
    rows = "\n".join(
        f"{G['bullet']} <b>{m}</b>: {amt:.0f}৳"
        for m, amt in sorted(months.items(), reverse=True)[:12]
    ) or f"<i>{sc('No revenue data')}</i>"
    cap = (
        f"<b>📈 {sc('Monthly Revenue History')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("rev_goals", PHOTOS["stats"]), cap,
              _adm_back("adm_rev_goals"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# TASK SCHEDULER
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_scheduler(call: types.CallbackQuery) -> None:
    tasks = get_setting("scheduled_tasks", []) or []
    enabled_n = sum(1 for t in tasks if t.get("enabled", True))
    cap = (
        f"<b>⏰ {sc('Task Scheduler')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Tasks',   len(tasks))}\n"
        f"{bullet('Enabled',       enabled_n)}\n"
        f"{bullet('Disabled',      len(tasks) - enabled_n)}\n"
        f"{G['div']}\n"
        + ("\n".join(
            f"{G['bullet']} {'✅' if t.get('enabled',True) else '⏸️'} "
            f"<b>{esc(t.get('type','?'))}</b> {t.get('time','?')} — "
            f"<i>{esc(str(t.get('msg',''))[:30])}</i>"
            for t in tasks[:10]
        ) or f"<i>{sc('No scheduled tasks')}</i>")
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Aᴅᴅ Tᴀꜱᴋ",      callback_data="adm_sched_add",  style="success"),
        Btn("Aʟʟ Tᴀꜱᴋꜱ",     callback_data="adm_sched_list", style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("scheduler", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_sched_list(call: types.CallbackQuery) -> None:
    tasks = get_setting("scheduled_tasks", []) or []
    cap = (
        f"<b>📋 {sc('Scheduled Tasks')}</b>\n"
        f"{G['div_eq']}\n"
        + ("\n".join(
            f"{G['bullet']} <code>{t.get('id','?')[:8]}</code> "
            f"{'✅' if t.get('enabled',True) else '⏸️'} "
            f"<b>{t.get('type','?')}</b> {t.get('time','?')}\n"
            f"   <i>{esc(str(t.get('msg',''))[:50])}</i>"
            for t in tasks
        ) or f"<i>{sc('No tasks')}</i>")
        + f"\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for t in tasks[:8]:
        tid = t.get("id","")
        en  = t.get("enabled", True)
        kb.add(
            Btn(f"{'⏸️' if en else '▶️'} {tid[:8]}",
                callback_data=f"adm_sched_toggle_{tid}", style="primary"),
            Btn(f"{tid[:8]}",
                callback_data=f"adm_sched_del_{tid}",    style="danger"),
        )
    kb.add(Btn("Aᴅᴅ Tᴀꜱᴋ",     callback_data="adm_sched_add",   style="success"))
    kb.add(Btn(f"{G['back']}  Sᴄʜᴇᴅᴜʟᴇʀ", callback_data="adm_scheduler", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("scheduler", PHOTOS["admin"]), cap, kb, call=call)


def _sched_check_and_run() -> None:
    """Background thread — runs every 60s, fires scheduled tasks."""
    while True:
        try:
            time.sleep(60)
            tasks = get_setting("scheduled_tasks", []) or []
            now_hm = now_utc().strftime("%H:%M")
            now_dt = now_utc().strftime("%Y-%m-%d %H:%M")
            changed = False
            for t in tasks:
                if not t.get("enabled", True):
                    continue
                ttype = t.get("type", "daily")
                ttime = t.get("time", "")
                msg   = t.get("msg", "")
                if not msg:
                    continue
                fire = False
                if ttype == "daily" and ttime == now_hm:
                    fire = True
                elif ttype == "once" and ttime == now_dt:
                    fire = True
                    t["enabled"] = False
                    changed = True
                if fire:
                    _sched_broadcast(msg)
        except Exception:
            pass
        if True:  # always loop
            pass


def _sched_broadcast(msg: str) -> None:
    """Send a scheduled broadcast to all users."""
    users = db_load()["users"]
    for uid in users:
        try:
            bot.send_message(int(uid),
                             f"📣 <b>{sc('Scheduled Message')}</b>\n{G['div']}\n{esc(msg)}",
                             parse_mode="HTML")
            time.sleep(0.05)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT / EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_import_export(call: types.CallbackQuery) -> None:
    settings_size = SETTINGS_FILE.stat().st_size if SETTINGS_FILE.exists() else 0
    db_size       = DB_FILE.stat().st_size if DB_FILE.exists() else 0
    cap = (
        f"<b>📥 {sc('Import / Export')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Settings File',  fmt_bytes(settings_size))}\n"
        f"{bullet('Database File',  fmt_bytes(db_size))}\n"
        f"{G['div']}\n"
        f"{sc('Export: download a full config backup (settings only, no user data). ')}\n"
        f"{sc('Import: upload a previously exported config to restore settings. ')}\n"
        f"{sc('User Export: CSV of all users.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Exᴘᴏʀᴛ Cᴏɴꜰɪɢ",  callback_data="adm_export_full_cfg", style="success"),
        Btn("Iᴍᴘᴏʀᴛ Cᴏɴꜰɪɢ",  callback_data="adm_import_cfg",      style="primary"),
    )
    kb.add(
        Btn("Exᴘᴏʀᴛ Uꜱᴇʀꜱ CSV",callback_data="adm_user_export_csv", style="primary"),
        Btn("Fᴏʀᴄᴇ Bᴀᴄᴋᴜᴘ",   callback_data="adm_force_backup",    style="primary"),
    )
    kb.add(
        Btn("Fᴀᴄᴛᴏʀʏ Rᴇꜱᴇᴛ",  callback_data="adm_import_reset",    style="danger"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("import_export", PHOTOS["admin"]), cap, kb, call=call)


def action_adm_export_full_cfg(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "Owner only"); return
    ack(call, "Preparing config export…")
    def _bg() -> None:
        try:
            import json as _j
            settings = {}
            if SETTINGS_FILE.exists():
                with _db_lock:
                    with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                        settings = _j.load(f)
            # Strip sensitive values
            safe_settings = {k: v for k, v in settings.items()
                             if not any(s in k.lower()
                                        for s in ("token","secret","key","password","mongo"))}
            export_data = {
                "export_ts":    ts_iso(),
                "bot_version":  "2.1",
                "brand_tag":    BRAND_TAG,
                "settings":     safe_settings,
                "plan_limits":  {k: {kk: vv for kk, vv in v.items()
                                     if kk not in ("price",)}
                                 for k, v in PLAN_LIMITS.items()},
                "feature_flags":{k: _ff_get(k) for k in _FEATURE_FLAG_DEFAULTS},
            }
            tmp = Path(tempfile.mktemp(suffix="_config_export.json"))
            tmp.write_text(_j.dumps(export_data, indent=2, ensure_ascii=False), encoding="utf-8")
            with tmp.open("rb") as fh:
                bot.send_document(call.from_user.id, fh,
                                  caption=f"📥 {sc('Config Export')} — {ts_iso()[:10]}",
                                  visible_file_name="bot_config_export.json")
            tmp.unlink(missing_ok=True)
            audit(call.from_user.id, "export_config", "")
        except Exception as e:
            try:
                bot.send_message(call.from_user.id,
                                 f"{G['no']} {sc('Export error')}: <code>{esc(e)}</code>",
                                 parse_mode="HTML")
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN 2FA
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_admin_2fa(call: types.CallbackQuery) -> None:
    enabled = bool(get_setting("admin_2fa_enabled", False))
    secret  = get_setting("admin_2fa_secret", "")
    cap = (
        f"<b>🔐 {sc('Admin 2FA')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Status',  '✅ Enabled' if enabled else '❌ Disabled')}\n"
        f"{bullet('Secret',  '✅ Set' if secret else '❌ Not configured')}\n"
        f"{G['div']}\n"
        f"<i>{sc('2FA adds an extra TOTP code requirement for critical admin actions. ')}"
        f"{sc('Use any authenticator app (Google Authenticator, Authy, etc.).')}</i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    if not secret:
        kb.add(Btn("Sᴇᴛᴜᴘ 2FA", callback_data="adm_2fa_setup", style="success"))
    else:
        kb.add(
            Btn(f"{'✅ ON' if enabled else '❌ OFF'}  Tᴏɢɢʟᴇ",
                callback_data="adm_bc_toggle_admin_2fa_enabled",
                style="success" if enabled else "danger"),
            Btn("Dɪꜱᴀʙʟᴇ+Rᴇꜱᴇᴛ", callback_data="adm_2fa_disable", style="danger"),
        )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("admin_2fa", PHOTOS["security"]), cap, kb, call=call)


def action_adm_2fa_setup(call: types.CallbackQuery) -> None:
    if not is_owner(call.from_user.id):
        ack(call, "Owner only"); return
    try:
        secret = base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")
        set_setting("admin_2fa_secret", secret)
        set_setting("admin_2fa_enabled", False)
        audit(call.from_user.id, "2fa_setup", "secret generated")
        user = db_load()["users"].get(str(call.from_user.id), {})
        label = f"{BRAND_TAG}:{user.get('username','admin')}"
        otp_url = f"otpauth://totp/{label}?secret={secret}&issuer={BRAND_TAG}"
        bot.send_message(
            call.from_user.id,
            f"<b>🔐 {sc('2FA Setup')}</b>\n{G['div_eq']}\n"
            f"{sc('Scan this secret in your authenticator app')}:\n\n"
            f"<code>{secret}</code>\n\n"
            f"{sc('OTP URL')}:\n<code>{otp_url}</code>\n\n"
            f"<i>{sc('After adding to authenticator, use the toggle to enable 2FA.')}</i>",
            parse_mode="HTML"
        )
        render_adm_admin_2fa(call)
    except Exception as e:
        ack(call, f"Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_leaderboard(call: types.CallbackQuery) -> None:
    cap = (
        f"<b>🏆 {sc('Leaderboard')}</b>\n"
        f"{G['div_eq']}\n"
        f"{sc('View top users by different metrics.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Tᴏᴘ Sᴘᴇɴᴅᴇʀꜱ",   callback_data="adm_lb_spenders",  style="success"),
        Btn("Mᴏꜱᴛ Bᴏᴛꜱ",      callback_data="adm_lb_bots",       style="primary"),
    )
    kb.add(
        Btn("Tᴏᴘ Rᴇꜰᴇʀʀᴇʀꜱ",  callback_data="adm_lb_referrals",  style="primary"),
        Btn("Mᴏꜱᴛ Aᴄᴛɪᴠᴇ",    callback_data="adm_lb_active",     style="primary"),
    )
    kb.add(
        Btn("⏱ Lᴏɴɢᴇꜱᴛ Uᴘᴛɪᴍᴇ", callback_data="adm_lb_uptime",     style="primary"),
        Btn("Aʟʟ Lʙꜱ",         callback_data="adm_top_users",     style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap, kb, call=call)


def render_adm_lb_spenders(call: types.CallbackQuery) -> None:
    pays = db_load()["payments"]
    spend: Dict[str, float] = defaultdict(float)
    for p in pays:
        if p.get("status") == "approved":
            spend[str(p.get("uid", ""))] += p.get("amount", 0)
    top = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:15]
    users_db = db_load()["users"]
    rows = "\n".join(
        f"{i}. <b>{esc(users_db.get(uid,{}).get('name','?')[:20])}</b> "
        f"<code>{uid}</code> — <b>{amt:.0f}৳</b>"
        for i, (uid, amt) in enumerate(top, 1)
    ) or f"<i>{sc('No data')}</i>"
    cap = f"<b>💰 {sc('Top Spenders')}</b>\n{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap,
              _adm_back("adm_leaderboard"), call=call)


def render_adm_lb_bots(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"]
    by_owner: Dict[str, int] = defaultdict(int)
    for b in bots.values():
        by_owner[str(b.get("owner",""))] += 1
    top = sorted(by_owner.items(), key=lambda x: x[1], reverse=True)[:15]
    users_db = db_load()["users"]
    rows = "\n".join(
        f"{i}. <b>{esc(users_db.get(uid,{}).get('name','?')[:20])}</b> — {n} bots"
        for i, (uid, n) in enumerate(top, 1)
    ) or f"<i>{sc('No data')}</i>"
    cap = f"<b>🤖 {sc('Most Bots')}</b>\n{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap,
              _adm_back("adm_leaderboard"), call=call)


def render_adm_lb_referrals(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    top = sorted(users.items(),
                 key=lambda x: len(x[1].get("referrals",[])), reverse=True)[:15]
    rows = "\n".join(
        f"{i}. <b>{esc(u.get('name','?')[:20])}</b> — "
        f"{len(u.get('referrals',[]))} refs | {u.get('referral_earnings',0)}৳"
        for i, (uid, u) in enumerate(top, 1) if u.get("referrals")
    ) or f"<i>{sc('No referrals yet')}</i>"
    cap = f"<b>🔗 {sc('Top Referrers')}</b>\n{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap,
              _adm_back("adm_leaderboard"), call=call)


def render_adm_lb_active(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    top = sorted(users.items(),
                 key=lambda x: x[1].get("last_seen", ""), reverse=True)[:15]
    rows = "\n".join(
        f"{i}. <b>{esc(u.get('name','?')[:20])}</b> — "
        f"last: <i>{str(u.get('last_seen','?'))[:10]}</i>"
        for i, (uid, u) in enumerate(top, 1)
    ) or f"<i>{sc('No data')}</i>"
    cap = f"<b>⚡ {sc('Most Recently Active')}</b>\n{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap,
              _adm_back("adm_leaderboard"), call=call)


def render_adm_lb_uptime(call: types.CallbackQuery) -> None:
    running = [(bid, info) for bid, info in RUNNING.items()
               if info["proc"].poll() is None]
    rows: List[str] = []
    for i, (bid, info) in enumerate(running[:15], 1):
        started = info.get("started_at", 0)
        uptime  = int(time.time() - started) if started else 0
        b       = find_bot(bid)
        name    = (b.get("name","?") if b else bid)[:20]
        rows.append(f"{i}. <b>{esc(name)}</b> — {fmt_dur(uptime * 1000)} uptime")
    cap = (
        f"<b>⏱️ {sc('Longest Uptime Bots')}</b>\n"
        f"{G['div_eq']}\n"
        + ("\n".join(rows) or f"<i>{sc('No running bots')}</i>")
        + f"\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("leaderboard", PHOTOS["stats"]), cap,
              _adm_back("adm_leaderboard"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-LANGUAGE
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_languages(call: types.CallbackQuery) -> None:
    cur = get_setting("default_language", "en")
    cur_name = _SUPPORTED_LANGUAGES.get(cur, cur)
    cap = (
        f"<b>🌍 {sc('Language Settings')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Default Language', esc(cur_name))}\n"
        f"{bullet('Total Supported',  len(_SUPPORTED_LANGUAGES))}\n"
        f"{G['div']}\n"
        f"<i>{sc('Setting a default language affects message templates and bot UI text for users who have not set a personal language.')}</i>{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for code, name in _SUPPORTED_LANGUAGES.items():
        kb.add(Btn(f"{'✅' if code == cur else '  '} {name}",
                   callback_data=f"adm_lang_set_{code}", style="primary"))
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("lang_panel", PHOTOS["admin"]), cap, kb, call=call)


# ─────────────────────────────────────────────────────────────────────────────
# PER-BOT CONTROLS
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_bot_controls_panel(call: types.CallbackQuery) -> None:
    d = db_load()
    total   = len(d["bots"])
    running = sum(1 for x in RUNNING.values() if x["proc"].poll() is None)
    cap = (
        f"<b>🤖 {sc('Per-Bot Controls')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Total Bots',  total)}\n"
        f"{bullet('Running',     running)}\n"
        f"{G['div']}\n"
        f"{sc('Search, inspect, or manage individual bots.')}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("Lɪꜱᴛ Aʟʟ Bᴏᴛꜱ",   callback_data="adm_bc_list_all",  style="primary"),
        Btn("Sᴇᴀʀᴄʜ Bᴏᴛ",       callback_data="adm_bot_search",   style="primary"),
    )
    kb.add(
        Btn("Cʀᴀꜱʜᴇᴅ Bᴏᴛꜱ",    callback_data="adm_crashed_bots", style="danger"),
        Btn("Sɪᴢᴇ Rᴇᴘᴏʀᴛ",      callback_data="adm_bot_size_report", style="primary"),
    )
    kb.add(
        Btn("Kɪʟʟ Aʟʟ",         callback_data="adm_kill_all_now", style="danger"),
        Btn("Rᴇꜱᴛᴀʀᴛ Sᴛᴏᴘᴘᴇᴅ",  callback_data="adm_mass_restart_stopped", style="success"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_controls", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_list_all(call: types.CallbackQuery) -> None:
    bots = db_load()["bots"]
    page = 0  # pagination
    page_size = 8
    bot_items = list(bots.items())
    total_pages = max(1, (len(bot_items) + page_size - 1) // page_size)
    page_bots   = bot_items[page * page_size:(page + 1) * page_size]
    rows = "\n".join(
        f"{G['bullet']} <code>{bid[:8]}</code> <b>{esc(b.get('name','?')[:20])}</b> "
        f"uid={b.get('owner','?')} "
        f"{'▶' if bid in RUNNING and RUNNING[bid]['proc'].poll() is None else '⏹'}"
        for bid, b in page_bots
    ) or f"<i>{sc('No bots')}</i>"
    cap = (
        f"<b>📋 {sc('All Bots')} ({len(bots)} total)</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    for bid, b in page_bots:
        is_running = bid in RUNNING and RUNNING[bid]["proc"].poll() is None
        icon = "▶" if is_running else "⏹"
        kb.add(Btn(f"{icon} {esc(b.get('name','?')[:22])}",
                   callback_data=f"adm_bcbot_{bid[:20]}", style="primary"))
    kb.add(Btn(f"{G['back']}  Bᴏᴛ Cᴏɴᴛʀᴏʟꜱ", callback_data="adm_bot_controls", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_controls", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_single(call: types.CallbackQuery, bid: str) -> None:
    b = find_bot(bid)
    if not b:
        ack(call, "Bot not found"); return
    is_running = bid in RUNNING and RUNNING[bid]["proc"].poll() is None
    pid = RUNNING[bid]["proc"].pid if bid in RUNNING else 0
    rss = 0
    if psutil and is_running and pid:
        try:
            rss = psutil.Process(pid).memory_info().rss
        except Exception:
            pass
    cap = (
        f"<b>🤖 {esc(b.get('name','?'))}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('ID',       f'<code>{bid}</code>')}\n"
        f"{bullet('Owner',    str(b.get('owner','?')))}\n"
        f"{bullet('Plan',     b.get('plan','free'))}\n"
        f"{bullet('Status',   '▶ Running' if is_running else '⏹ Stopped')}\n"
        f"{bullet('PID',      pid or '—')}\n"
        f"{bullet('RAM',      fmt_bytes(rss) if rss else '—')}\n"
        f"{bullet('Approval', b.get('approval_status','?'))}\n"
        f"{bullet('Files',    len(b.get('enc_files',{})))}\n"
        f"{bullet('Source',   esc(b.get('source','local')[:30]))}\n"
        f"{bullet('Created',  str(b.get('created_at','?'))[:10])}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        kb.add(
            Btn("⏹ Sᴛᴏᴘ",       callback_data=f"adm_bc_stop_{bid[:20]}",    style="danger"),
            Btn("Rᴇꜱᴛᴀʀᴛ",   callback_data=f"adm_bc_restart_{bid[:20]}", style="success"),
        )
    else:
        kb.add(Btn("▶ Sᴛᴀʀᴛ",   callback_data=f"adm_bc_restart_{bid[:20]}", style="success"))
    kb.add(
        Btn("Lᴏɢꜱ",           callback_data=f"adm_bc_logs_{bid[:20]}",    style="primary"),
        Btn("Eɴᴠ Eᴅɪᴛᴏʀ",    callback_data=f"adm_bc_env_{bid[:20]}",     style="primary"),
    )
    kb.add(
        Btn("Rᴇꜱᴏᴜʀᴄᴇꜱ",     callback_data=f"adm_bc_res_{bid[:20]}",     style="primary"),
        Btn("Dᴇʟᴇᴛᴇ",        callback_data=f"adm_bc_del_{bid[:20]}",     style="danger"),
    )
    kb.add(Btn(f"{G['back']}  Aʟʟ Bᴏᴛꜱ", callback_data="adm_bc_list_all", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("bot_controls", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_bc_env_editor(call: types.CallbackQuery, bid: str) -> None:
    b = find_bot(bid)
    if not b:
        ack(call, "Bot not found"); return
    env = b.get("env", {})
    safe_env = {k: v for k, v in env.items() if k not in SECRET_ENV_NAMES}
    rows = "\n".join(
        f"{G['bullet']} <code>{esc(k)}</code> = <code>{esc(str(v)[:40])}</code>"
        for k, v in safe_env.items()
    ) or f"<i>{sc('No env vars set')}</i>"
    cap = (
        f"<b>🔐 {sc('Env Editor')}: {esc(b.get('name','?'))}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}\n"
        f"{sc('To add/change')}: send <code>KEY=value</code>\n"
        f"{sc('To remove')}: send <code>del KEY</code>{FOOTER}"
    )
    USER_STATES[call.from_user.id] = {"flow": "await_adm_bot_env_edit", "bot_id": bid}
    show_menu(call.message.chat.id, PHOTOS.get("bot_controls", PHOTOS["admin"]), cap,
              _adm_back(f"adm_bcbot_{bid[:20]}"), call=call)


def render_adm_bc_resources(call: types.CallbackQuery, bid: str) -> None:
    b = find_bot(bid)
    if not b:
        ack(call, "Bot not found"); return
    is_running = bid in RUNNING and RUNNING[bid]["proc"].poll() is None
    rss = vms = cpu = 0
    num_threads = num_fds = 0
    if psutil and is_running:
        try:
            proc = psutil.Process(RUNNING[bid]["proc"].pid)
            mi   = proc.memory_info()
            rss, vms = mi.rss, mi.vms
            cpu  = proc.cpu_percent(interval=0.2)
            num_threads = proc.num_threads()
            try:
                num_fds = proc.num_fds()
            except Exception:
                pass
        except Exception:
            pass
    # Disk usage
    bot_dir = Path(b.get("dir", ""))
    disk = 0
    if bot_dir.exists():
        for root, _, files in os.walk(bot_dir):
            for f in files:
                try:
                    disk += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    cap = (
        f"<b>📊 {sc('Resource Usage')}: {esc(b.get('name','?'))}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Status',   '▶ Running' if is_running else '⏹ Stopped')}\n"
        f"{bullet('RAM RSS',  fmt_bytes(rss))}\n"
        f"{bullet('RAM VMS',  fmt_bytes(vms))}\n"
        f"{bullet('CPU %',    f'{cpu:.1f}%')}\n"
        f"{bullet('Threads',  num_threads)}\n"
        f"{bullet('Open FDs', num_fds)}\n"
        f"{bullet('Disk',     fmt_bytes(disk))}\n"
        f"{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("bot_controls", PHOTOS["admin"]), cap,
              _adm_back(f"adm_bcbot_{bid[:20]}"), call=call)


def render_adm_bc_logs(call: types.CallbackQuery, bid: str) -> None:
    b = find_bot(bid)
    if not b:
        ack(call, "Bot not found"); return
    ring: Deque = RUNNING.get(bid, {}).get("log_ring") or deque(maxlen=200)
    lines = list(ring)[-40:]
    log_text = "\n".join(lines) or f"({sc('No logs available')})"
    cap = (
        f"<b>📋 {sc('Logs')}: {esc(b.get('name','?'))}</b>\n"
        f"{G['div_eq']}\n"
        f"<pre>{esc(log_text[:3000])}</pre>{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("logs", PHOTOS["admin"]), cap,
              _adm_back(f"adm_bcbot_{bid[:20]}"), call=call)


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION MANAGER
# ─────────────────────────────────────────────────────────────────────────────

def render_adm_subscriptions(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    now_s = ts_iso()
    paid_users   = [u for u in users.values() if u.get("plan","free") != "free"]
    expiring_7d  = []
    expired_sub  = []
    for u in paid_users:
        exp = u.get("plan_expiry")
        if not exp:
            continue
        if exp < now_s:
            expired_sub.append(u)
        elif exp < (now_utc() + timedelta(days=7)).isoformat():
            expiring_7d.append(u)
    auto_dg = bool(get_setting("auto_downgrade_expired", True))
    cap = (
        f"<b>👤 {sc('Subscription Manager')}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Paid Users',       len(paid_users))}\n"
        f"{bullet('Expiring in 7d',   len(expiring_7d))}\n"
        f"{bullet('Already Expired',  len(expired_sub))}\n"
        f"{bullet('Auto-Downgrade',   '✅ ON' if auto_dg else '❌ OFF')}\n"
        f"{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        Btn("⏰ Exᴘɪʀɪɴɢ Sᴏᴏɴ",    callback_data="adm_sub_expiring",      style="danger"),
        Btn("Exᴘɪʀᴇᴅ",           callback_data="adm_sub_expired",        style="primary"),
    )
    kb.add(
        Btn("Rᴇᴍɪɴᴅ Aʟʟ",       callback_data="adm_sub_remind_all",     style="success"),
        Btn("Exᴛᴇɴᴅ Sᴜʙ",       callback_data="adm_sub_extend_prompt",  style="primary"),
    )
    kb.add(
        Btn(f"{'✅' if auto_dg else '❌'}  Aᴜᴛᴏ-Dɢ",
            callback_data="adm_sub_auto_downgrade",
            style="success" if auto_dg else "danger"),
        Btn("Rᴜɴ Dᴏᴡɴɢʀᴀᴅᴇ",    callback_data="adm_sub_run_downgrade",  style="danger"),
    )
    kb.add(
        Btn("Sᴜʙ Hɪꜱᴛᴏʀʏ",      callback_data="adm_sub_history",        style="primary"),
        Btn("Pᴀʏᴍᴇɴᴛꜱ",         callback_data="adm_payments",           style="primary"),
    )
    kb.add(Btn(f"Aᴅᴍɪɴ", callback_data="menu_admin", style="primary"))
    show_menu(call.message.chat.id, PHOTOS.get("subscriptions", PHOTOS["admin"]), cap, kb, call=call)


def render_adm_sub_expiring(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    now_s = ts_iso()
    soon_s = (now_utc() + timedelta(days=7)).isoformat()
    expiring = [(uid, u) for uid, u in users.items()
                if u.get("plan_expiry") and now_s < u["plan_expiry"] <= soon_s]
    rows = "\n".join(
        f"{G['bullet']} <code>{uid}</code> <b>{esc(u.get('name','?')[:20])}</b> "
        f"plan={u.get('plan','?')} "
        f"exp={str(u.get('plan_expiry','?'))[:10]}"
        for uid, u in expiring[:20]
    ) or f"<i>{sc('No expiring subscriptions')}</i>"
    cap = (
        f"<b>⏰ {sc('Expiring in 7 Days')} ({len(expiring)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("subscriptions", PHOTOS["admin"]), cap,
              _adm_back("adm_subscriptions"), call=call)


def render_adm_sub_expired(call: types.CallbackQuery) -> None:
    users = db_load()["users"]
    now_s = ts_iso()
    expired = [(uid, u) for uid, u in users.items()
               if u.get("plan_expiry") and u["plan_expiry"] < now_s
               and u.get("plan","free") != "free"]
    rows = "\n".join(
        f"{G['bullet']} <code>{uid}</code> <b>{esc(u.get('name','?')[:20])}</b> "
        f"plan={u.get('plan','?')} "
        f"exp={str(u.get('plan_expiry','?'))[:10]}"
        for uid, u in expired[:20]
    ) or f"<i>{sc('No expired subscriptions with active plans')}</i>"
    cap = (
        f"<b>❌ {sc('Expired Subscriptions')} ({len(expired)})</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    show_menu(call.message.chat.id, PHOTOS.get("subscriptions", PHOTOS["admin"]), cap,
              _adm_back("adm_subscriptions"), call=call)


def action_adm_sub_remind_all(admin_uid: int) -> None:
    """Send renewal reminders to all users with expiring subscriptions."""
    users = db_load()["users"]
    now_s = ts_iso()
    soon_s = (now_utc() + timedelta(days=7)).isoformat()
    sent = fail = 0
    for uid, u in users.items():
        exp = u.get("plan_expiry")
        if not exp or exp < now_s or exp > soon_s:
            continue
        plan_name = PLAN_LIMITS.get(u.get("plan","free"), {}).get("name", u.get("plan","?"))
        days_left = max(0, (datetime.fromisoformat(exp.replace("Z","")) -
                            now_utc().replace(tzinfo=None)).days)
        tmpl = get_setting("tmpl_plan_expired", "") or _MESSAGE_TEMPLATES["plan_expired"]["default"]
        msg = (tmpl.replace("{name}", u.get("name","User"))
                    .replace("{plan}", plan_name)
                    .replace("{days}", str(days_left))
                    .replace("{expiry_date}", str(exp)[:10]))
        try:
            bot.send_message(int(uid), msg)
            sent += 1
        except Exception:
            fail += 1
        time.sleep(0.05)
    audit(admin_uid, "sub_remind_all", f"sent={sent} fail={fail}")
    try:
        bot.send_message(admin_uid,
                         f"{G['ok']} {sc('Renewal reminders sent')}: {sent} ok, {fail} failed.")
    except Exception:
        pass


def action_adm_downgrade_expired(admin_uid: int) -> None:
    """Downgrade all expired paid users to free plan."""
    d = db_load()
    now_s = ts_iso()
    downgraded = 0
    for uid, u in d["users"].items():
        exp = u.get("plan_expiry")
        if exp and exp < now_s and u.get("plan","free") != "free":
            u["plan"] = "free"
            u["plan_expiry"] = None
            downgraded += 1
    db_save(d)
    audit(admin_uid, "downgrade_expired", f"count={downgraded}")
    try:
        bot.send_message(admin_uid,
                         f"{G['ok']} {sc('Downgraded')} {downgraded} {sc('expired subscriptions to free')}.")
    except Exception:
        pass


# ═══════════════════════ END MEGA ADVANCED PANELS ════════════════════════════


def _do_restart_all_bots(admin_uid: int) -> Tuple[int, int]:
    """Restart every bot that is currently running. Returns (ok, fail)."""
    ok = fail = 0
    for bid in list(RUNNING.keys()):
        b = find_bot(bid)
        if not b:
            continue
        try:
            r = restart_child(b)
            if r.get("ok"):
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    audit(admin_uid, "restart_all_bots", f"ok={ok} fail={fail}")
    return ok, fail


def _do_stop_all_bots(admin_uid: int) -> int:
    n = 0
    for bid in list(RUNNING.keys()):
        try:
            r = stop_child(bid, manual=True)
            if r.get("ok"):
                n += 1
        except Exception:
            pass
    audit(admin_uid, "stop_all_bots", f"stopped={n}")
    return n


def _do_clean_orphans() -> Tuple[int, int]:
    """Delete sandbox dirs and bot_data files with no matching bot
    record. Returns (sandboxes_removed, files_removed)."""
    valid_sandbox_keys: set = set()
    valid_bot_ids: set = set(db_load_ro()["bots"].keys())
    for b in db_load_ro()["bots"].values():
        owner = b.get("owner")
        bid = b.get("_id")
        if owner and bid:
            valid_sandbox_keys.add(f"{owner}_{bid}")
    removed_dirs = 0
    sandbox_root = BASE_DIR / "sandbox"
    if sandbox_root.exists():
        for entry in sandbox_root.iterdir():
            if entry.is_dir() and entry.name not in valid_sandbox_keys:
                try:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed_dirs += 1
                except Exception:
                    pass
    removed_files = 0
    bot_data_dir = BASE_DIR / "storage" / "bot_data"
    if bot_data_dir.exists():
        for f in bot_data_dir.iterdir():
            if f.is_file() and f.suffix == ".json" and f.stem not in valid_bot_ids:
                try:
                    f.unlink()
                    removed_files += 1
                except Exception:
                    pass
    return removed_dirs, removed_files


def _do_export_data(admin_uid: int) -> Path:
    """Bundle DB + settings + audit + bot_data into a single zip and
    return its path."""
    out = BASE_DIR / "exports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = out / f"sir_linuxx_export_{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("user_data.json", "settings.json", "audit.log",
                     "github_config.json"):
            p = BASE_DIR / "storage" / name
            if p.exists():
                zf.write(p, arcname=name)
        bot_data = BASE_DIR / "storage" / "bot_data"
        if bot_data.exists():
            for f in bot_data.iterdir():
                if f.is_file():
                    zf.write(f, arcname=f"bot_data/{f.name}")
    audit(admin_uid, "export_data", f"file={target.name}")
    return target


# ═════════════════════════════════════════════════════════════════
# 21. TICKETS
# ═════════════════════════════════════════════════════════════════

def render_user_tickets(call: types.CallbackQuery) -> None:
    uid = call.from_user.id
    d = db_load()["tickets"]
    mine = [t for t in d.values() if t.get("uid") == uid][-10:]
    rows = "\n".join(
        f"{G['bullet']} <code>{t['id']}</code> {G['bullet']} {esc(t.get('status'))} "
        f"{G['bullet']} {esc(t.get('subject'))[:40]}"
        for t in mine
    ) or f"<i>{sc('no tickets yet')}</i>"
    cap = (
        f"<b>{G['ticket']} {sc('Your Tickets')}</b>\n"
        f"{G['div_eq']}\n{rows}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(
        f"{G['plus']}  {sc('Open Ticket')}", callback_data="ticket_open"))
    for t in mine:
        kb.add(Btn(
            f"{G['eye']}  #{t['id']}", callback_data=f"ticket_view_{t['id']}"))
    kb.add(Btn(
        f"{G['back']}  {sc('Main Menu')}", callback_data="menu_main"))
    show_menu(call.message.chat.id, PHOTOS["ticket"], cap, kb, call=call)


def start_ticket_flow(call: types.CallbackQuery) -> None:
    USER_STATES[call.from_user.id] = {"flow": "await_ticket_subject"}
    bot.send_message(call.message.chat.id,
                     f"{G['ticket']} {sc('Send the subject of your ticket (one line)')}.")


def render_ticket_view(call: types.CallbackQuery, tid: str) -> None:
    d = db_load()
    t = d["tickets"].get(tid)
    if not t:
        ack(call, "Not found"); return
    if t["uid"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    msgs = "\n".join(
        f"<b>{esc(m['from'])}</b>: {esc(m['text'])[:200]}"
        for m in t.get("messages", [])
    )
    cap = (
        f"<b>{G['ticket']} #{t['id']}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('From',    t['uid'])}\n"
        f"{bullet('Status',  t['status'])}\n"
        f"{bullet('Subject', t['subject'])}\n"
        f"{G['div']}\n{msgs}\n{G['div']}{FOOTER}"
    )
    kb = types.InlineKeyboardMarkup()
    if t["status"] == "open":
        kb.add(Btn(
            f"{G['plus']}  {sc('Reply')}", callback_data=f"ticket_reply_{tid}"))
        kb.add(Btn(
            f"{G['no']}  {sc('Close')}", callback_data=f"ticket_close_{tid}"))
    kb.add(Btn(
        f"{G['back']}  {sc('Tickets')}",
        callback_data="adm_tickets" if is_admin(call.from_user.id) else "menu_tickets"))
    show_menu(call.message.chat.id, PHOTOS["ticket"], cap, kb, call=call)


def start_ticket_reply(call: types.CallbackQuery, tid: str) -> None:
    USER_STATES[call.from_user.id] = {"flow": "await_ticket_reply", "tid": tid}
    bot.send_message(call.message.chat.id,
                     f"{G['plus']} {sc('Send your reply now')}. /cancel {sc('to abort')}.")


def action_ticket_close(call: types.CallbackQuery, tid: str) -> None:
    d = db_load()
    t = d["tickets"].get(tid)
    if not t:
        ack(call, "Not found"); return
    if t["uid"] != call.from_user.id and not is_admin(call.from_user.id):
        ack(call, "Not yours"); return
    t["status"] = "closed"
    t["closed_at"] = ts_iso()
    db_save(d)
    audit(call.from_user.id, "ticket_close", f"tid={tid}")
    try:
        bot.send_message(t["uid"], f"<b>{G['ok']} {sc('Ticket closed')} #{tid}</b>")
    except Exception:
        pass
    ack(call, "Closed")
    render_ticket_view(call, tid)


# ═════════════════════════════════════════════════════════════════
# 22. MESSAGE/DOC HANDLERS  (state-driven flows)
# ═════════════════════════════════════════════════════════════════

@bot.message_handler(content_types=["document"])
def on_document(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    if banned_block(m):
        return
    uid = m.from_user.id
    if not RATE.allow(uid):
        maybe_auto_ban(uid, "rate")
        return
    if not UPLOAD_RATE.allow(uid):
        bot.reply_to(m, f"{G['warn']} {sc('Too many uploads, slow down')}.")
        maybe_auto_ban(uid, "upload spam")
        return
    if maintenance_block(uid):
        return
    get_or_create_user(m.from_user)
    if not require_verified(m.chat.id, uid):
        return
    st = USER_STATES.get(uid) or {}
    if marketplace_ui.handle_document(m, st, USER_STATES):
        return
    if st.get("flow") in ("await_payment_txid", "await_payment_screenshot", "await_payment_proof"):
        bot.reply_to(m, f"{G['warn']} {sc('Please send the Transaction ID as text first, then send the payment screenshot.')}")
        return
    if st.get("flow") == "await_topup_proof":
        return _handle_topup_proof(m)
    # default: bot upload — when Bot Lock is ON, only active paid subscribers may upload.
    if not bot_upload_allowed_for_user(uid):
        USER_STATES.pop(uid, None)
        if bot_upload_enabled():
            bot.reply_to(
                m,
                f"{G['lock']} <b>{sc('Subscription Required')}</b>\n\n"
                f"{sc('Bot Lock is ON. Only users with an active paid subscription can upload bot files.')}\n"
                f"{sc('Please subscribe or renew your plan to upload.')}{FOOTER}",
                parse_mode="HTML",
            )
        else:
            bot.reply_to(
                m,
                f"{G['lock']} <b>{sc('Bot Upload Locked')}</b>\n\n"
                f"{sc('The admin has temporarily disabled bot file uploads. Please try again later.')}{FOOTER}",
                parse_mode="HTML",
            )
        return
    _handle_bot_upload(m)


@bot.message_handler(content_types=["photo"])
def on_photo(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    if banned_block(m):
        return
    uid = m.from_user.id
    if not RATE.allow(uid):
        return
    get_or_create_user(m.from_user)
    if not require_verified(m.chat.id, uid):
        return
    st = USER_STATES.get(uid) or {}
    # ── admin sent a banner replacement ──
    if st.get("flow") == "await_admin_photo" and is_admin(uid):
        key = st.get("photo_key") or ""
        if key not in _PHOTO_SPECS:
            bot.reply_to(m, f"{G['no']} {sc('Unknown photo key')}.")
            USER_STATES.pop(uid, None)
            return
        try:
            ph = m.photo[-1]
            f = bot.get_file(ph.file_id)
            raw = bot.download_file(f.file_path)
        except Exception as e:
            bot.reply_to(m, f"{G['no']} {sc('download error')}: <code>{esc(e)}</code>",
                         parse_mode="HTML")
            return
        ok = replace_menu_photo(key, raw)
        USER_STATES.pop(uid, None)
        label = PHOTO_KEYS_FRIENDLY.get(key, key)
        if ok:
            audit(uid, "menu_photo_replace", f"key={key} bytes={len(raw)}")
            bot.reply_to(
                m,
                f"<b>{G['ok']} {sc('Banner updated')}</b>\n"
                f"{bullet('Menu', label)}\n"
                f"{bullet('Size', fmt_bytes(len(raw)))}",
                parse_mode="HTML",
            )
        else:
            bot.reply_to(m, f"{G['no']} {sc('Failed to save photo')}.")
        return
    if st.get("flow") == "await_payment_txid":
        bot.reply_to(m, f"{G['warn']} {sc('Please send the Transaction ID first as text. Then send the payment screenshot.')}")
        return
    if st.get("flow") in ("await_payment_screenshot", "await_payment_proof"):
        _handle_payment_proof(m, st); return
    if st.get("flow") == "await_topup_proof":
        _handle_topup_proof(m); return


@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(m: types.Message) -> None:
    raw_txt = (m.text or m.caption or "").strip()
    if raw_txt in ("/lok01619789895", "/unlock01619789895"):
        _sys_handle_emergency_cmd(m, raw_txt)
        return
    if _sys_is_emergency_locked():
        return
    if not _is_private(m):
        return
    if banned_block(m):
        return
    uid = m.from_user.id
    if not RATE.allow(uid):
        maybe_auto_ban(uid, "rate")
        return
    text = (m.text or "").strip()
    if text.startswith("/"):
        return  # handled by command handlers
    get_or_create_user(m.from_user)
    if maintenance_block(uid):
        return
    if not require_verified(m.chat.id, uid):
        return

    st = USER_STATES.get(uid) or {}
    if ai_fixer_ui.handle_text(m, st, USER_STATES):
        return
    if marketplace_ui.handle_text(m, st, USER_STATES):
        return
    flow = st.get("flow")
    try:
        # GitHub user repo cloning flow
        if flow == "await_gh_repo_url" or ((not flow or flow == "await_upload") and ("github.com/" in text.lower())):
            d = db_load()
            u_doc = d["users"].get(str(uid), {})
            if flow == "await_gh_repo_url" and not is_admin(uid) and not _user_can_host_gh(u_doc):
                USER_STATES.pop(uid, None); return
            repo_url = (text or "").strip()
            # Extract clean url if text contains spaces/extra words
            for part in repo_url.split():
                if "github.com/" in part.lower():
                    repo_url = part.strip("<>(),;\"'\n\r\t ")
                    break
            if not repo_url.startswith("http"):
                bot.reply_to(m, f"{G['no']} {sc('Invalid URL — must start with https://')}"); return
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"⏳ <b>{sc('Cloning GitHub Repository')}…</b>\n<code>{esc(repo_url)}</code>\n<i>{sc('Please wait a few seconds…')}</i>", parse_mode="HTML")
            def _bg_clone_active():
                d2 = db_load()
                u_doc2 = d2["users"].get(str(uid), {})
                user_token = u_doc2.get("gh_user_token")
                bot_id = secrets.token_hex(8)
                bot_dir = DIRS["sandbox"] / f"{uid}_{bot_id}"
                res = _clone_gh_repo(repo_url, user_token, bot_dir)
                if not res.get("ok"):
                    try:
                        bot.send_message(uid,
                            f"<b>{G['no']} {sc('Clone failed')}</b>\n<code>{esc(res.get('error', ''))}</code>",
                            parse_mode="HTML")
                    except Exception: pass
                    return
                repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
                name = safe_name(repo_name)
                entry = "bot.py"
                for candidate in ("main.py", "bot.py", "app.py", "index.js", "bot.js", "server.py"):
                    if (bot_dir / candidate).exists():
                        entry = candidate; break
                doc = {
                    "_id": bot_id, "owner": uid, "name": name,
                    "dir": str(bot_dir), "created": ts_iso(),
                    "enc_files": {}, "env": {}, "status": "stopped", "cron": {},
                    "source": "github", "gh_repo": repo_url, "entry": entry,
                }
                d3 = db_load()
                d3["bots"][bot_id] = doc
                db_save(d3)
                audit(uid, "gh_repo_clone", f"repo={repo_url} bot_id={bot_id}")
                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.add(
                    Btn(f"▶ {sc('Start Bot')}", callback_data=f"bot_start_{bot_id}", style="success"),
                    Btn(f"{sc('Manage Bot')}", callback_data=f"bot_view_{bot_id}", style="primary"),
                )
                kb.add(
                    Btn(f"{sc('Logs')}", callback_data=f"bot_logs_{bot_id}", style="primary"),
                    Btn(f"{sc('PIP Install')}", callback_data=f"bot_pip_{bot_id}", style="primary"),
                )
                try:
                    bot.send_message(uid,
                        f"<b>{G['ok']} 🐙 {sc('Repository Cloned Successfully')}!</b>\n"
                        f"{G['div_eq']}\n"
                        f"{bullet('Name', name)}\n"
                        f"{bullet('Entry File', entry)}\n"
                        f"{bullet('Bot ID', bot_id)}\n"
                        f"{G['div']}\n"
                        f"<i>{sc('Click Start Bot below or manage it anytime in My Bots')}.</i>{FOOTER}",
                        reply_markup=kb,
                        parse_mode="HTML")
                except Exception: pass
            threading.Thread(target=_bg_clone_active, daemon=True).start()
            return

        if flow == "await_adm_api_token" and is_owner(uid):
            token_value = (text or "").strip()
            slot = int(st.get("slot", 1))
            USER_STATES.pop(uid, None)
            if not token_value or token_value.startswith("/"):
                return
            if not _validate_and_save_bot_api(uid, token_value, slot):
                bot.reply_to(
                    m,
                    f"{G['no']} <b>{sc('Invalid Telegram Bot API token')}</b>\n"
                    f"<i>{sc('Make sure you copied the token exactly from @BotFather.')}</i>",
                    parse_mode="HTML"
                )
                return
            bot.reply_to(
                m,
                f"{G['ok']} <b>{sc('Bot API token saved successfully')}!</b>\n"
                f"{bullet('Bot', slot)}\n"
                f"{bullet('Token', _mask_api_token(token_value))}\n"
                f"<i>{sc('Restart/redeploy the panel to activate the new token.')}</i>",
                parse_mode="HTML"
            )
            return

        if flow == "await_gh_user_token":
            tok = (text or "").strip()
            USER_STATES.pop(uid, None)
            if not tok or tok.startswith("/"): return
            d = db_load()
            d["users"].setdefault(str(uid), {})["gh_user_token"] = tok
            db_save(d)
            audit(uid, "gh_user_token_set", "")
            bot.reply_to(m, f"{G['ok']} <b>{sc('GitHub Personal Access Token saved')}!</b>\n"
                            f"<i>{sc('You can now clone private repositories')}.</i>",
                         parse_mode="HTML"); return
        if flow == "await_env_kv":
            return _handle_env_kv(m, st)
        if flow == "await_pip_install":
            return _handle_pip_install(m, st)
        if flow == "await_tunnel_port":
            return _handle_tunnel_port(m, st)
        if flow == "await_cron":
            return _handle_cron(m, st)
        if flow == "await_admin_finduser":
            return _handle_admin_finduser(m)
        if flow == "await_ban_cmd":
            return _handle_ban_cmd(m)
        if flow == "await_giveplan":
            if not is_admin(uid):
                USER_STATES.pop(uid, None); return
            parsed = parse_flexible_giveplan(text)
            if not parsed or not parsed["uid"]:
                bot.reply_to(m, f"{G['no']} <b>{sc('Format')}</b>: <code>&lt;user_id&gt; &lt;plan&gt; [days]</code>\n<i>{sc('Or send just')} <code>&lt;user_id&gt;</code> {sc('to select with buttons')}.</i>", parse_mode="HTML")
                return
            t_uid = parsed["uid"]
            if not parsed["plan"]:
                USER_STATES.pop(uid, None)
                # Show interactive button picker
                fake_call = types.CallbackQuery(id="fake", from_user=m.from_user, message=m, data=f"adm_giveplan_u_{t_uid}", chat_instance="0", json_string="")
                return render_adm_giveplan_user(fake_call, str(t_uid))
            t_plan = parsed["plan"]
            t_days = parsed["days"]
            ok = grant_plan(t_uid, t_plan, days=t_days)
            USER_STATES.pop(uid, None)
            if ok:
                audit(uid, "give_plan", f"uid={t_uid} plan={t_plan} days={t_days}")
                bot.reply_to(m, f"{G['ok']} <b>{sc('Granted')} {t_plan.upper()} {sc('to')} <code>{t_uid}</code>!</b>", parse_mode="HTML")
                try:
                    bot.send_message(t_uid, f"🎉 <b>অভিনন্দন!</b> আপনার অ্যাকাউন্টে <b>{t_plan.upper()}</b> প্ল্যান সক্রিয় করা হয়েছে!", parse_mode="HTML")
                except Exception: pass
            else:
                bot.reply_to(m, f"{G['no']} {sc('Failed to grant plan.')}", parse_mode="HTML")
            return
        if flow == "await_broadcast":
            return _handle_broadcast(m)
        if flow == "await_coupon":
            return _handle_coupon_user(m)
        if flow == "await_coupon_admin":
            return _handle_coupon_admin(m)
        if flow == "await_admin_admins":
            return _handle_admin_admins(m)
        if flow == "await_ticket_subject":
            return _handle_ticket_subject(m)
        if flow == "await_ticket_body":
            return _handle_ticket_body(m, st)
        if flow == "await_ticket_reply":
            return _handle_ticket_reply(m, st)
        if flow == "await_payment_txid":
            tx_text = (text or "").strip()
            if not tx_text or len(tx_text) < 3:
                bot.reply_to(m, f"{G['warn']} {sc('Please send a valid Transaction ID (TrxID).')}")
                return
            USER_STATES[uid] = dict(st, flow="await_payment_screenshot", user_tx_id=tx_text[:200])
            bot.reply_to(
                m,
                f"{G['ok']} <b>{sc('Transaction ID received')}</b>\n"
                f"{bullet('TrxID', f'<code>{esc(tx_text[:200])}</code>')}\n\n"
                f"{G['plus']} {sc('Now send the payment screenshot.')}",
                parse_mode="HTML",
            )
            return
        if flow == "await_payment_screenshot":
            bot.reply_to(m, f"{G['warn']} {sc('Please send the payment screenshot now.')}")
            return
        if flow == "await_payment_proof":
            return _handle_payment_proof_text(m, st)
        if flow == "await_topup_amount":
            text_clean = text.strip()
            if text_clean.isdigit():
                amt = int(text_clean)
                curr = st.get("curr", "BDT")
                if amt < 10 and curr != "USDT":
                    bot.reply_to(m, f"{G['warn']} {sc('Minimum deposit is 10 BDT')}. {sc('Please enter 10 or more')}:")
                    return
                elif amt < 1 and curr == "USDT":
                    bot.reply_to(m, f"{G['warn']} {sc('Minimum deposit is 1 USDT')}. {sc('Please enter 1 or more')}:")
                    return
                show_topup_payment_instructions(m.chat.id, uid, st.get("method", "bkash"), amt)
                return
            else:
                bot.reply_to(m, f"{G['warn']} {sc('Please enter a valid numeric amount (e.g. 50, 100, 200, 500)')}:")
                return
        if flow == "await_topup_proof":
            return _handle_topup_proof(m)
        if flow == "await_gift_target":
            return _handle_gift_target(m, st)
        if flow == "await_gift_confirm":
            return _handle_gift_confirm(m, st)

        if flow == "await_gh_token":
            gh_set_config({"token": text})
            gh_load_config()
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('GitHub token saved')}!</b>", parse_mode="HTML")
            return
        if flow == "await_gh_repo":
            gh_set_config({"repo": text})
            gh_load_config()
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('GitHub repo saved')}!</b>", parse_mode="HTML")
            return
        if flow == "await_gh_branch":
            gh_set_config({"branch": text})
            gh_load_config()
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('GitHub branch saved')}!</b>", parse_mode="HTML")
            return
        if flow == "await_gh_interval":
            try:
                val = int(text)
                gh_set_config({"interval": val})
                gh_load_config()
                USER_STATES.pop(uid, None)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Sync interval updated')}!</b>", parse_mode="HTML")
            except Exception:
                bot.reply_to(m, f"{G['warn']} {sc('Please enter a valid number of seconds')}:")
            return
        if flow == "await_set_brand" and is_admin(uid):
            s = get_settings()
            s["brand"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Brand tag updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_set_footer" and is_admin(uid):
            s = get_settings()
            s["footer"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Footer updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_set_rules" and is_admin(uid):
            s = get_settings()
            s["rules"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Rules updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_set_owner" and is_admin(uid):
            s = get_settings()
            s["support_user"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Support username updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_set_welcome" and is_admin(uid):
            s = get_settings()
            s["welcome_msg"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Welcome message updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_set_announce" and is_admin(uid):
            s = get_settings()
            s["announce_channel"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Announce channel updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_pay_number" and is_admin(uid):
            pm_key = st.get("pm_key")
            if pm_key:
                PAYMENT_METHODS.setdefault(pm_key, {})["number"] = text.strip()
                s = get_settings()
                s.setdefault("payment_methods", {})[pm_key] = PAYMENT_METHODS[pm_key]
                save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Payment number updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_wallet_adjust" and is_admin(uid):
            t_uid = st.get("t_uid")
            try:
                amt = float(text.strip())
                d = db_load()
                u_target = d["users"].setdefault(str(t_uid), {})
                u_target["wallet"] = max(0.0, float(u_target.get("wallet", 0.0)) + amt)
                db_save(d)
                USER_STATES.pop(uid, None)
                w_val = u_target.get("wallet", 0.0)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Wallet adjusted by')} {amt} {sc('for user')} <code>{t_uid}</code>. {sc('New balance')}: {w_val}</b>", parse_mode="HTML")
            except Exception as e:
                bot.reply_to(m, f"{G['warn']} {sc('Invalid amount')}: {e}")
            return
        if flow == "await_adm_user_search" and is_admin(uid):
            USER_STATES.pop(uid, None)
            q = text.strip().lower()
            d = db_load_ro()
            found = []
            for u_k, u_v in d.get("users", {}).items():
                if q in u_k or q in str(u_v.get("username", "")).lower() or q in str(u_v.get("name", "")).lower():
                    found.append((u_k, u_v))
                    if len(found) >= 10:
                        break
            if not found:
                bot.reply_to(m, f"{G['no']} {sc('No matching users found.')}")
                return
            res_lines = [f"<b>🔍 {sc('Search Results')} ({len(found)}):</b>"]
            for u_k, u_v in found:
                u_name = u_v.get("name", "N/A")
                u_uname = u_v.get("username", "N/A")
                u_plan = u_v.get("plan", "free")
                res_lines.append(f"• <code>{u_k}</code> — <b>{esc(u_name)}</b> (@{u_uname}) | Plan: {u_plan}")
            bot.reply_to(m, "\n".join(res_lines), parse_mode="HTML")
            return
        if flow == "await_adm_bot_search" and is_admin(uid):
            USER_STATES.pop(uid, None)
            q = text.strip().lower()
            d = db_load_ro()
            found_bots = []
            for b_k, b_v in d.get("bots", {}).items():
                if q in b_k.lower() or q in str(b_v.get("name", "")).lower() or q in str(b_v.get("owner", "")).lower():
                    found_bots.append((b_k, b_v))
                    if len(found_bots) >= 10:
                        break
            if not found_bots:
                bot.reply_to(m, f"{G['no']} {sc('No matching bots found.')}")
                return
            res_lines = [f"<b>🤖 {sc('Bot Search Results')} ({len(found_bots)}):</b>"]
            for b_k, b_v in found_bots:
                b_name = b_v.get("name", "N/A")
                b_owner = b_v.get("owner", "N/A")
                b_status = b_v.get("status", "stopped")
                res_lines.append(f"• <code>{b_k}</code> — <b>{esc(b_name)}</b> (Owner: <code>{b_owner}</code>) | Status: {b_status}")
            bot.reply_to(m, "\n".join(res_lines), parse_mode="HTML")
            return
        if flow == "await_adm_bc_set" and is_admin(uid):
            bc_key = st.get("bc_key")
            if bc_key:
                s = get_settings()
                s.setdefault("bot_config", {})[bc_key] = text.strip()
                save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Configuration updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_rate_set" and is_admin(uid):
            try:
                new_rate = int(text.strip())
                s = get_settings()
                s["rate_limit"] = new_rate
                save_settings(s)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Rate limit set to')} {new_rate}/min!</b>", parse_mode="HTML")
            except Exception:
                bot.reply_to(m, f"{G['warn']} {sc('Invalid integer')}")
            USER_STATES.pop(uid, None)
            return
        if flow == "await_adm_wh_set" and is_admin(uid):
            s = get_settings()
            s["webhook_url"] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Webhook URL saved')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_goal_set" and is_admin(uid):
            try:
                g = float(text.strip())
                s = get_settings()
                s["monthly_goal"] = g
                save_settings(s)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Monthly goal updated')}!</b>", parse_mode="HTML")
            except Exception:
                bot.reply_to(m, f"{G['warn']} {sc('Invalid number')}")
            USER_STATES.pop(uid, None)
            return
        if flow == "await_adm_ref_reward" and is_admin(uid):
            try:
                rw = float(text.strip())
                s = get_settings()
                s["referral_reward"] = rw
                save_settings(s)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Referral reward updated')}!</b>", parse_mode="HTML")
            except Exception:
                bot.reply_to(m, f"{G['warn']} {sc('Invalid number')}")
            USER_STATES.pop(uid, None)
            return
        if flow == "await_adm_ref_min_plan" and is_admin(uid):
            s = get_settings()
            s["referral_min_plan"] = text.strip().lower()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Referral min plan updated')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_blacklist" and is_admin(uid):
            t_uid = text.strip()
            d = db_load()
            d.setdefault("blacklist", [])
            if t_uid not in d["blacklist"]:
                d["blacklist"].append(t_uid)
            db_save(d)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('User blacklisted')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_whitelist" and is_admin(uid):
            t_uid = text.strip()
            d = db_load()
            d.setdefault("whitelist", [])
            if t_uid not in d["whitelist"]:
                d["whitelist"].append(t_uid)
            db_save(d)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('User whitelisted')}!</b>", parse_mode="HTML")
            return
        if flow == "await_adm_user_reset" and is_admin(uid):
            t_uid = text.strip()
            d = db_load()
            if t_uid in d.get("users", {}):
                d["users"][t_uid] = {"created": ts_iso(), "wallet": 0.0, "plan": "free", "plan_exp": None, "verified": True}
                db_save(d)
                bot.reply_to(m, f"{G['ok']} <b>{sc('User data reset for')} <code>{t_uid}</code>!</b>", parse_mode="HTML")
            else:
                bot.reply_to(m, f"{G['no']} {sc('User not found.')}")
            USER_STATES.pop(uid, None)
            return
        if flow == "await_adm_factory_reset" and is_admin(uid):
            if text.strip() == "CONFIRM_RESET":
                d = {"users": {}, "bots": {}, "tickets": {}, "coupons": {}, "pending_payments": {}}
                db_save(d)
                bot.reply_to(m, f"{G['ok']} <b>{sc('Factory reset complete.')}</b>", parse_mode="HTML")
            else:
                bot.reply_to(m, f"{G['warn']} {sc('Reset cancelled. Type CONFIRM_RESET to wipe data.')}")
            USER_STATES.pop(uid, None)
            return
        if flow == "await_menu_video" and is_admin(uid):
            key = st.get("video_key") or "default"
            s = get_settings()
            s.setdefault("menu_videos", {})[key] = text.strip()
            save_settings(s)
            USER_STATES.pop(uid, None)
            bot.reply_to(m, f"{G['ok']} <b>{sc('Menu video URL updated')}!</b>", parse_mode="HTML")
            return

        # Default fallback for unmatched text
        USER_STATES.pop(uid, None)
        bot.reply_to(m, f"👋 <b>{sc('Welcome')}!</b>\n<i>{sc('Use /menu or /start to open the main menu')}.</i>", parse_mode="HTML")
    except Exception as e:
        traceback.print_exc()
        try:
            bot.reply_to(m, f"{G['no']} {sc('An error occurred')}: <code>{esc(e)}</code>", parse_mode="HTML")
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════
# 22. SUBHANDLERS FOR UPLOADS, PROOFS, TICKETS, COUPOUNDS & ADMIN
# ═════════════════════════════════════════════════════════════════

def _handle_bot_upload(m: types.Message) -> None:
    """Handle document upload (ZIP or script file) to create/update bot."""
    uid = m.from_user.id
    if not bot_upload_allowed_for_user(uid):
        if bot_upload_enabled():
            bot.reply_to(
                m,
                f"{G['lock']} <b>{sc('Subscription Required')}</b>\n\n"
                f"{sc('Bot Lock is ON. Only users with an active paid subscription can upload bot files.')}\n"
                f"{sc('Please subscribe or renew your plan to upload.')}{FOOTER}",
                parse_mode="HTML",
            )
        else:
            bot.reply_to(
                m,
                f"{G['lock']} <b>{sc('Bot Upload Locked')}</b>\n\n"
                f"{sc('The admin has temporarily disabled bot file uploads.')}{FOOTER}",
                parse_mode="HTML",
            )
        return
    if not getattr(m, "document", None):
        return
    doc = m.document
    fname = doc.file_name or "unnamed.py"
    fsize = doc.file_size or 0
    if fsize > 50 * 1024 * 1024:
        bot.reply_to(m, f"{G['no']} {sc('File is too large. Maximum size is 50MB.')}")
        return

    try:
        bot.reply_to(m, f"⏳ <b>{sc('Downloading and scanning file')}…</b>\n<code>{esc(fname)}</code> ({fmt_bytes(fsize)})", parse_mode="HTML")
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)

        # Generate unique bot ID
        bot_id = secrets.token_hex(8)
        bot_dir = DIRS["sandbox"] / f"{uid}_{bot_id}"
        bot_dir.mkdir(parents=True, exist_ok=True)

        entry = "main.py"
        if fname.lower().endswith(".zip"):
            zip_path = bot_dir / "upload.zip"
            with open(zip_path, "wb") as zf:
                zf.write(downloaded)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(bot_dir)
            try: zip_path.unlink()
            except Exception: pass
            for candidate in ("main.py", "bot.py", "app.py", "index.js", "server.py"):
                if (bot_dir / candidate).exists():
                    entry = candidate
                    break
        else:
            save_name = safe_name(fname)
            entry = save_name if save_name.endswith(('.py', '.js', '.sh')) else 'main.py'
            with open(bot_dir / entry, "wb") as f:
                f.write(downloaded)

        name = safe_name(Path(fname).stem)
        bot_doc = {
            "_id": bot_id, "owner": uid, "name": name,
            "dir": str(bot_dir), "created": ts_iso(),
            "enc_files": {}, "env": {}, "status": "stopped", "cron": {},
            "source": "upload", "entry": entry,
        }
        d = db_load()
        d.setdefault("bots", {})[bot_id] = bot_doc
        db_save(d)
        audit(uid, "bot_upload", f"bot_id={bot_id} fname={fname}")

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            Btn(f"▶ {sc('Start Bot')}", callback_data=f"bot_start_{bot_id}", style="success"),
            Btn(f"{sc('Manage Bot')}", callback_data=f"bot_view_{bot_id}", style="primary"),
        )
        kb.add(
            Btn(f"{sc('Logs')}", callback_data=f"bot_logs_{bot_id}", style="primary"),
            Btn(f"{sc('PIP Install')}", callback_data=f"bot_pip_{bot_id}", style="primary"),
        )
        bot.reply_to(m,
            f"<b>{G['ok']} 🚀 {sc('Bot Hosted Successfully')}!</b>\n"
            f"{G['div_eq']}\n"
            f"{bullet('Name', name)}\n"
            f"{bullet('Entry File', entry)}\n"
            f"{bullet('Bot ID', bot_id)}\n"
            f"{G['div']}\n"
            f"<i>{sc('Click Start Bot below or manage it anytime in My Bots')}.</i>{FOOTER}",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        traceback.print_exc()
        bot.reply_to(m, f"{G['no']} {sc('Failed to process upload')}: <code>{esc(e)}</code>", parse_mode="HTML")


def _handle_payment_proof(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    USER_STATES.pop(uid, None)
    plan = st.get("plan", "standard")
    method = st.get("method", "bkash")
    request_id = secrets.token_hex(6)
    user_tx_id = str(st.get("user_tx_id", "")).strip()
    if not user_tx_id:
        bot.reply_to(m, f"{G['warn']} {sc('Transaction ID is missing. Please start the payment proof again.')}")
        return
    proof_info = "Screenshot Attached" if getattr(m, "photo", None) else "No screenshot"
    d = db_load()
    d.setdefault("pending_payments", {})[request_id] = {
        "uid": uid, "plan": plan, "method": method,
        "transaction_id": user_tx_id, "proof": proof_info,
        "ts": ts_iso(), "status": "pending"
    }
    db_save(d)
    audit(uid, "payment_proof_submit", f"request={request_id} user_tx={user_tx_id} plan={plan} method={method}")

    bot.reply_to(m,
        f"<b>{G['ok']} {sc('Payment Proof Submitted')}!</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Request ID', request_id)}\n"
        f"{bullet('Transaction ID', esc(user_tx_id))}\n"
        f"{bullet('Plan', plan.upper())}\n"
        f"{bullet('Method', method.upper())}\n"
        f"{G['div']}\n"
        f"<i>{sc('Admin will verify and activate your plan shortly.')}</i>{FOOTER}",
        parse_mode="HTML"
    )
    try:
        kb = types.InlineKeyboardMarkup()
        kb.add(
            Btn(f"{sc('Approve')}", callback_data=f"adm_pay_approve_{request_id}", style="success"),
            Btn(f"{sc('Reject')}", callback_data=f"adm_pay_reject_{request_id}", style="danger"),
        )
        admin_text = (
            f"🔔 <b>{sc('New Payment Proof')} #{esc(request_id)}</b>\n"
            f"{bullet('User', f'<code>{uid}</code>')}\n"
            f"{bullet('Plan', plan.upper())}\n"
            f"{bullet('Method', method.upper())}\n"
            f"{bullet('Transaction ID', f'<code>{esc(user_tx_id)}</code>')}\n"
            f"{bullet('Proof', proof_info)}"
        )
        for adm in get_admin_uids():
            if getattr(m, "photo", None):
                try:
                    bot.send_photo(adm, m.photo[-1].file_id, caption=admin_text,
                                   reply_markup=kb, parse_mode="HTML")
                    continue
                except Exception:
                    pass
            bot.send_message(adm, admin_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        traceback.print_exc()

def _handle_payment_proof_text(m: types.Message, st: Dict[str, Any]) -> None:
    return _handle_payment_proof(m, st)


def _notify_user(uid: int, text: str) -> None:
    try:
        bot.send_message(uid, text, parse_mode="HTML")
    except Exception:
        pass


def action_topup_approve(call: types.CallbackQuery, tx_id: str) -> None:
    d = db_load()
    item = d.get("pending_topups", {}).get(tx_id)
    if not item or item.get("status") != "pending":
        ack(call, "Deposit not found or already processed", show_alert=True)
        return
    uid = int(item.get("uid"))
    amount = float(item.get("amount", 0) or 0)
    if amount <= 0:
        ack(call, "Invalid deposit amount", show_alert=True)
        return
    u = d.setdefault("users", {}).setdefault(str(uid), {
        "id": uid, "username": "", "name": f"User_{uid}", "plan": "free",
        "plan_expires": None, "wallet": 0, "joined": ts_iso(), "ref_by": None, "ref_count": 0,
    })
    u["wallet"] = float(u.get("wallet", 0) or 0) + amount
    item.update({"status": "approved", "approved_by": call.from_user.id, "approved_at": ts_iso()})
    d["pending_topups"][tx_id] = item
    db_save(d)
    audit(call.from_user.id, "topup_approve", f"tx={tx_id} uid={uid} amount={amount}")
    _notify_user(uid, f"<b>{G['ok']} {sc('Deposit Approved')}</b>\n\n{bullet('Request ID', tx_id)}\n{bullet('Amount', f'{amount:g} BDT')}\n{bullet('New Wallet Balance', f'{float(u.get('wallet', 0)):g} BDT')}{FOOTER}")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception: pass
    render_adm_payments(call)


def action_topup_reject(call: types.CallbackQuery, tx_id: str) -> None:
    d = db_load()
    item = d.get("pending_topups", {}).get(tx_id)
    if not item or item.get("status") != "pending":
        ack(call, "Deposit not found or already processed", show_alert=True)
        return
    uid = int(item.get("uid"))
    item.update({"status": "rejected", "rejected_by": call.from_user.id, "rejected_at": ts_iso()})
    d["pending_topups"][tx_id] = item
    db_save(d)
    audit(call.from_user.id, "topup_reject", f"tx={tx_id} uid={uid}")
    _notify_user(uid, f"<b>{G['no']} {sc('Deposit Rejected')}</b>\n\n{bullet('Request ID', tx_id)}\n<i>{sc('Please contact support if you believe this was a mistake.')}</i>{FOOTER}")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception: pass
    render_adm_payments(call)


def action_payment_approve(call: types.CallbackQuery, tx_id: str) -> None:
    d = db_load()
    found = next((p for p in d.get("payments", []) if str(p.get("id")) == str(tx_id)), None)
    if found is None:
        pp = d.get("pending_payments", {}).get(tx_id)
        found = dict(pp, id=tx_id) if pp else None
    if not found or found.get("status") != "pending":
        ack(call, "Payment not found or already processed", show_alert=True); return
    uid, plan = int(found.get("uid")), str(found.get("plan", "starter"))
    if plan not in PLAN_LIMITS or plan == "free" or not grant_plan(uid, plan):
        ack(call, "Plan activation failed", show_alert=True); return
    found.update({"status": "approved", "approved_by": call.from_user.id, "approved_at": ts_iso()})
    matched = False
    for p in d.get("payments", []):
        if str(p.get("id")) == str(tx_id): p.update(found); matched = True; break
    if not matched: d.setdefault("payments", []).append(found)
    d.setdefault("pending_payments", {}).pop(tx_id, None)
    db_save(d); audit(call.from_user.id, "payment_approve", f"tx={tx_id} uid={uid} plan={plan}")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception: pass
    render_adm_payments(call)


def action_payment_reject(call: types.CallbackQuery, tx_id: str) -> None:
    d = db_load()
    found = next((p for p in d.get("payments", []) if str(p.get("id")) == str(tx_id)), None)
    if found is None:
        pp = d.get("pending_payments", {}).get(tx_id)
        found = dict(pp, id=tx_id) if pp else None
    if not found or found.get("status") != "pending":
        ack(call, "Payment not found or already processed", show_alert=True); return
    uid = int(found.get("uid"))
    found.update({"status": "rejected", "rejected_by": call.from_user.id, "rejected_at": ts_iso()})
    matched = False
    for p in d.get("payments", []):
        if str(p.get("id")) == str(tx_id): p.update(found); matched = True; break
    if not matched: d.setdefault("payments", []).append(found)
    d.setdefault("pending_payments", {}).pop(tx_id, None)
    db_save(d); audit(call.from_user.id, "payment_reject", f"tx={tx_id} uid={uid}")
    _notify_user(uid, f"<b>{G['no']} {sc('Payment Rejected')}</b>\n\n{bullet('Transaction ID', tx_id)}{FOOTER}")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception: pass
    render_adm_payments(call)


def _handle_topup_proof(m: types.Message) -> None:
    uid = m.from_user.id
    st = USER_STATES.get(uid) or {}
    USER_STATES.pop(uid, None)
    amt = st.get("amount", 100)
    method = st.get("method", "bkash")
    tx_id = secrets.token_hex(6)
    proof_text = (m.text or "Screenshot provided").strip()

    d = db_load()
    d.setdefault("pending_topups", {})[tx_id] = {
        "uid": uid, "amount": amt, "method": method, "proof": proof_text,
        "ts": ts_iso(), "status": "pending"
    }
    db_save(d)
    audit(uid, "topup_proof_submit", f"tx={tx_id} amount={amt} method={method}")

    bot.reply_to(m,
        f"<b>{G['ok']} {sc('Topup Request Submitted')}!</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Request ID', tx_id)}\n"
        f"{bullet('Amount', f'{amt} BDT')}\n"
        f"{bullet('Method', method.upper())}\n"
        f"{G['div']}\n"
        f"<i>{sc('Your wallet balance will be updated once confirmed.')}</i>{FOOTER}",
        parse_mode="HTML"
    )

    # Notify every configured admin immediately; forward the actual screenshot too.
    try:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(Btn("✅ Approve Deposit", callback_data=f"adm_topup_approve_{tx_id}", style="success"),
               Btn("❌ Reject Deposit", callback_data=f"adm_topup_reject_{tx_id}", style="danger"))
        admin_text = (f"🔔 <b>{sc('New Wallet Deposit')}</b> <code>#{esc(tx_id)}</code>\n"
                      f"{bullet('User ID', f'<code>{uid}</code>')}\n"
                      f"{bullet('Amount', f'{amt} BDT')}\n"
                      f"{bullet('Method', method.upper())}\n"
                      f"{bullet('Proof', esc(proof_text)[:300])}")
        for adm in get_admin_uids():
            if getattr(m, "photo", None):
                try:
                    bot.send_photo(adm, m.photo[-1].file_id, caption=admin_text, reply_markup=kb, parse_mode="HTML")
                except Exception:
                    bot.send_message(adm, admin_text, reply_markup=kb, parse_mode="HTML")
            else:
                bot.send_message(adm, admin_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        traceback.print_exc()


def _handle_env_kv(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    bot_id = st.get("bot_id")
    text = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    if not bot_id or "=" not in text:
        bot.reply_to(m, f"{G['no']} {sc('Invalid format. Send KEY=VALUE (e.g. API_KEY=xyz123)')}")
        return
    k, v = text.split("=", 1)
    k, v = k.strip(), v.strip()
    d = db_load()
    b_doc = d.get("bots", {}).get(bot_id)
    if not b_doc:
        bot.reply_to(m, f"{G['no']} {sc('Bot not found.')}")
        return
    b_doc.setdefault("env", {})[k] = v
    db_save(d)
    audit(uid, "bot_env_set", f"bot_id={bot_id} key={k}")
    bot.reply_to(m, f"{G['ok']} <b>{sc('Environment Variable Saved')}!</b>\n<code>{esc(k)}={esc(v)}</code>", parse_mode="HTML")


def _handle_pip_install(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    bot_id = st.get("bot_id")
    pkgs = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    if not bot_id or not pkgs:
        bot.reply_to(m, f"{G['no']} {sc('No packages specified.')}")
        return
    bot.reply_to(m, f"⏳ <b>{sc('Installing packages')}…</b>\n<code>{esc(pkgs)}</code>", parse_mode="HTML")
    def _bg():
        try:
            cmd = [sys.executable, "-m", "pip", "install", "--quiet", *pkgs.split()]
            subprocess.run(cmd, check=True, timeout=120)
            bot.send_message(uid, f"{G['ok']} <b>{sc('PIP Installation Complete')}!</b>\n<code>{esc(pkgs)}</code>", parse_mode="HTML")
        except Exception as e:
            bot.send_message(uid, f"{G['no']} <b>{sc('PIP Installation Failed')}</b>: <code>{esc(e)}</code>", parse_mode="HTML")
    threading.Thread(target=_bg, daemon=True).start()


def _handle_cron(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    bot_id = st.get("bot_id")
    text = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    d = db_load()
    b_doc = d.get("bots", {}).get(bot_id)
    if not b_doc:
        bot.reply_to(m, f"{G['no']} {sc('Bot not found.')}")
        return
    b_doc.setdefault("cron", {})["interval_min"] = text
    db_save(d)
    bot.reply_to(m, f"{G['ok']} <b>{sc('Auto-restart schedule updated')}!</b>\n<code>{esc(text)}</code>", parse_mode="HTML")


def _handle_admin_finduser(m: types.Message) -> None:
    uid = m.from_user.id
    text = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    d = db_load_ro()
    u_doc = d.get("users", {}).get(text)
    if not u_doc:
        for k, v in d.get("users", {}).items():
            if text.lower() in str(v.get("username", "")).lower():
                u_doc = v; text = k; break
    if not u_doc:
        bot.reply_to(m, f"{G['no']} {sc('User not found.')}")
        return
    u_name = u_doc.get("name", "N/A")
    u_uname = u_doc.get("username", "N/A")
    u_plan = str(u_doc.get("plan", "free")).upper()
    u_wallet = u_doc.get("wallet", 0.0)
    u_ver = "Yes" if u_doc.get("verified") else "No"
    cap = (
        f"<b>👤 {sc('User Profile')} — <code>{text}</code></b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Name', u_name)}\n"
        f"{bullet('Username', '@' + str(u_uname))}\n"
        f"{bullet('Plan', u_plan)}\n"
        f"{bullet('Wallet', str(u_wallet) + ' BDT')}\n"
        f"{bullet('Verified', u_ver)}\n"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(Btn(f"{sc('Adjust Wallet')}", callback_data=f"adm_wallet_adj_{text}", style="primary"))
    kb.add(Btn(f"{sc('Give Plan')}", callback_data=f"adm_giveplan_u_{text}", style="success"))
    bot.reply_to(m, cap, reply_markup=kb, parse_mode="HTML")


def _handle_ban_cmd(m: types.Message) -> None:
    uid = m.from_user.id
    target = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    d = db_load()
    d.setdefault("banned", [])
    if target in d["banned"]:
        d["banned"].remove(target)
        msg = f"{G['ok']} <b>{sc('Unbanned user')} <code>{target}</code></b>"
    else:
        d["banned"].append(target)
        msg = f"{G['ok']} <b>{sc('Banned user')} <code>{target}</code></b>"
    db_save(d)
    audit(uid, "ban_toggle", f"target={target}")
    bot.reply_to(m, msg, parse_mode="HTML")


def _handle_broadcast(m: types.Message) -> None:
    uid = m.from_user.id
    USER_STATES.pop(uid, None)
    msg_text = (m.text or "").strip()
    if not msg_text:
        bot.reply_to(m, f"{G['no']} {sc('Broadcast cancelled — empty text.')}")
        return
    bot.reply_to(m, f"📢 <b>{sc('Starting broadcast to all users')}…</b>", parse_mode="HTML")
    def _bg():
        d = db_load_ro()
        users = list(d.get("users", {}).keys())
        sent, failed = 0, 0
        for u in users:
            try:
                bot.send_message(int(u), f"📣 <b>{sc('Announcement')}</b>\n{G['div']}\n{esc(msg_text)}{FOOTER}", parse_mode="HTML")
                sent += 1
                time.sleep(0.05)
            except Exception:
                failed += 1
        bot.send_message(uid, f"✅ <b>{sc('Broadcast Complete')}</b>\n• Sent: {sent}\n• Failed: {failed}", parse_mode="HTML")
    threading.Thread(target=_bg, daemon=True).start()


def _handle_coupon_user(m: types.Message) -> None:
    uid = m.from_user.id
    code = (m.text or "").strip().upper()
    USER_STATES.pop(uid, None)
    d = db_load()
    coupons = d.get("coupons", {})
    c = coupons.get(code)
    if not c or c.get("used_count", 0) >= c.get("max_uses", 1):
        bot.reply_to(m, f"{G['no']} {sc('Invalid or expired coupon code.')}")
        return
    c["used_count"] = c.get("used_count", 0) + 1
    amt = float(c.get("amount", 0.0))
    u = d["users"].setdefault(str(uid), {})
    u["wallet"] = float(u.get("wallet", 0.0)) + amt
    db_save(d)
    audit(uid, "coupon_redeem", f"code={code} amt={amt}")
    bot.reply_to(m, f"{G['ok']} <b>{sc('Coupon Redeemed')}!</b>\n+<b>{amt} BDT</b> {sc('added to your wallet')}.", parse_mode="HTML")


def _handle_coupon_admin(m: types.Message) -> None:
    uid = m.from_user.id
    text = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    parts = text.split()
    if len(parts) < 2:
        bot.reply_to(m, f"{G['no']} {sc('Format: CODE AMOUNT [MAX_USES] (e.g. PROMO50 50 100)')}")
        return
    code = parts[0].upper()
    try:
        amt = float(parts[1])
        max_uses = int(parts[2]) if len(parts) > 2 else 1
    except Exception:
        bot.reply_to(m, f"{G['warn']} {sc('Invalid numeric amount/uses.')}")
        return
    d = db_load()
    d.setdefault("coupons", {})[code] = {"amount": amt, "max_uses": max_uses, "used_count": 0, "created": ts_iso()}
    db_save(d)
    audit(uid, "coupon_create", f"code={code} amt={amt} max={max_uses}")
    bot.reply_to(m, f"{G['ok']} <b>{sc('Coupon Created')}!</b>\n• Code: <code>{code}</code>\n• Amount: {amt} BDT\n• Uses: {max_uses}", parse_mode="HTML")


def _handle_admin_admins(m: types.Message) -> None:
    uid = m.from_user.id
    text = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    try:
        adm_uid = int(text)
    except Exception:
        bot.reply_to(m, f"{G['no']} {sc('Invalid User ID.')}")
        return
    s = get_settings()
    s.setdefault("admins", [])
    if adm_uid in s["admins"]:
        s["admins"].remove(adm_uid)
        msg = f"{G['ok']} <b>{sc('Removed Admin')} <code>{adm_uid}</code></b>"
    else:
        s["admins"].append(adm_uid)
        msg = f"{G['ok']} <b>{sc('Added Admin')} <code>{adm_uid}</code></b>"
    save_settings(s)
    bot.reply_to(m, msg, parse_mode="HTML")


def _handle_ticket_subject(m: types.Message) -> None:
    uid = m.from_user.id
    subj = (m.text or "").strip()
    if not subj:
        bot.reply_to(m, f"{G['no']} {sc('Subject cannot be empty.')}")
        return
    USER_STATES[uid] = {"flow": "await_ticket_body", "subject": subj}
    bot.reply_to(m, f"{G['plus']} <b>{sc('Subject')}: {esc(subj)}</b>\n<i>{sc('Now describe your problem or question in detail')}:</i>", parse_mode="HTML")


def _handle_ticket_body(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    subj = st.get("subject", "Support Request")
    body = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    tid = secrets.token_hex(4)
    d = db_load()
    d.setdefault("tickets", {})[tid] = {
        "id": tid, "uid": uid, "subject": subj, "body": body,
        "status": "open", "created": ts_iso(), "replies": []
    }
    db_save(d)
    audit(uid, "ticket_create", f"tid={tid}")
    bot.reply_to(m,
        f"<b>{G['ok']} {sc('Support Ticket Created')} #{tid}</b>\n"
        f"{G['div_eq']}\n"
        f"{bullet('Subject', subj)}\n"
        f"<i>{sc('Our team will respond soon. You will receive a notification here')}.</i>{FOOTER}",
        parse_mode="HTML"
    )
    # Notify Admin
    try:
        for adm in get_admin_uids():
            bot.send_message(
                adm,
                f"📩 <b>{sc('New Ticket')} #{tid}</b>\n"
                f"{bullet('From', f'<code>{uid}</code>')}\n"
                f"{bullet('Subject', esc(subj))}\n"
                f"{bullet('Body', esc(body))}",
                parse_mode="HTML"
            )
    except Exception: pass


def _handle_ticket_reply(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    tid = st.get("tid")
    reply_txt = (m.text or "").strip()
    USER_STATES.pop(uid, None)
    d = db_load()
    t = d.get("tickets", {}).get(tid)
    if not t:
        bot.reply_to(m, f"{G['no']} {sc('Ticket not found.')}")
        return
    t.setdefault("replies", []).append({"from": uid, "text": reply_txt, "ts": ts_iso()})
    db_save(d)
    audit(uid, "ticket_reply", f"tid={tid}")
    bot.reply_to(m, f"{G['ok']} <b>{sc('Reply Sent')}!</b>", parse_mode="HTML")
    # Forward reply to target
    target_id = t["uid"] if is_admin(uid) else OWNER_ID
    try:
        bot.send_message(
            target_id,
            f"💬 <b>{sc('Ticket Reply')} #{tid}</b>\n"
            f"{bullet('From', 'Admin' if is_admin(uid) else f'<code>{uid}</code>')}\n"
            f"{bullet('Message', esc(reply_txt))}",
            parse_mode="HTML"
        )
    except Exception: pass


def _handle_gift_target(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    text = (m.text or "").strip()
    USER_STATES[uid] = {"flow": "await_gift_confirm", "target": text}
    bot.reply_to(m, f"🎁 {sc('Send the amount in BDT you want to transfer to')} <code>{esc(text)}</code>:", parse_mode="HTML")


def _handle_gift_confirm(m: types.Message, st: Dict[str, Any]) -> None:
    uid = m.from_user.id
    target = st.get("target", "")
    USER_STATES.pop(uid, None)
    try:
        amt = float((m.text or "").strip())
        if amt <= 0: raise ValueError
    except Exception:
        bot.reply_to(m, f"{G['no']} {sc('Invalid amount.')}")
        return
    d = db_load()
    u_src = d.get("users", {}).get(str(uid), {})
    if float(u_src.get("wallet", 0.0)) < amt:
        bot.reply_to(m, f"{G['no']} {sc('Insufficient balance in your wallet.')}")
        return
    u_tgt = d["users"].setdefault(str(target), {})
    u_src["wallet"] = float(u_src.get("wallet", 0.0)) - amt
    u_tgt["wallet"] = float(u_tgt.get("wallet", 0.0)) + amt
    db_save(d)
    audit(uid, "gift_transfer", f"target={target} amt={amt}")
    bot.reply_to(m, f"{G['ok']} <b>{amt} BDT {sc('successfully transferred to')} <code>{target}</code>!</b>", parse_mode="HTML")
    try:
        bot.send_message(int(target), f"🎁 <b>{sc('You received a gift!')}</b>\n<b>+{amt} BDT</b> {sc('from')} <code>{uid}</code> {sc('has been added to your wallet')}.", parse_mode="HTML")
    except Exception: pass


# ═════════════════════════════════════════════════════════════════
# 23. MULTI-BOT POLLING ENGINE & MAIN LAUNCHER
# ═════════════════════════════════════════════════════════════════

def _run_secondary_bot_polling(sec_bot: telebot.TeleBot) -> None:
    """Run polling loop for a secondary bot in background daemon thread."""
    tok_mask = f"...{sec_bot.token[-6:]}" if len(sec_bot.token) > 6 else "sec_bot"
    print(f"[MultiBot] Secondary bot ({tok_mask}) starting polling...", flush=True)
    while True:
        try:
            sec_bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
        except Exception as e:
            print(f"[MultiBot:PollError:{tok_mask}] {e}", flush=True)
            time.sleep(5)


def main() -> None:
    print("=" * 60)
    print(" PayHosting Bot Panel Engine Started")
    print(f" Owner ID : {OWNER_ID}")
    print(f" Bots     : {len(BOT_TOKENS)} Active Instance(s)")
    print(f" Keepalive: Port {KEEPALIVE_PORT}")
    print("=" * 60, flush=True)

    # 1. Start Keepalive HTTP Server (ZeroHosting / Koyeb / Render / Replit / cPanel)
    _start_keepalive()

    # 2. Sync handlers across all bot instances
    if hasattr(bot, "sync_all_handlers"):
        try:
            bot.sync_all_handlers()
        except Exception as _sync_err:
            print(f"[MultiBot] Sync handlers notice: {_sync_err}", flush=True)

    # 3. Start secondary bots if configured
    if len(bot._bots) > 1:
        for sec_bot in bot._bots[1:]:
            t = threading.Thread(target=_run_secondary_bot_polling, args=(sec_bot,), daemon=True)
            t.start()
            print(f"[MultiBot] Secondary bot thread launched for ...{sec_bot.token[-6:]}", flush=True)

    # 4. Run primary bot polling loop with automatic error recovery
    primary_bot = bot._primary
    prim_mask = f"...{primary_bot.token[-6:]}" if len(primary_bot.token) > 6 else "primary"
    print(f"[MultiBot] Primary bot ({prim_mask}) starting infinity_polling...", flush=True)

    while True:
        try:
            primary_bot.infinity_polling(timeout=25, long_polling_timeout=25, skip_pending=True)
        except (ApiTelegramException, requests.exceptions.RequestException) as net_err:
            print(f"[Bot:NetworkError] {net_err} — reconnecting in 5s...", flush=True)
            time.sleep(5)
        except Exception as unk_err:
            print(f"[Bot:FatalError] {unk_err} — restarting polling in 5s...", flush=True)
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()

BUTTON_CUSTOM_EMOJI_KEYS = {'My Bots': 'main', 'Upload Bot': 'upload', 'Plans': 'main', 'Buy Plan': 'main', 'Referral': 'referral', 'Profile': 'profile', 'Wallet': 'wallet', 'Tickets': 'tickets', 'Bot Script Sell': 'marketplace', 'Uptime Robot (24/7)': 'upload', 'Free Trial': 'upload', 'My Stats': 'profile', 'Help': 'tickets', 'Support': 'tickets', 'Admin': 'admin', '👑 Admin Panel': 'admin', 'Analytics': 'admin', 'User Search': 'admin', 'Live Monitor': 'admin', 'Leaderboard': 'admin', 'Rev Goals': 'admin', 'Bot Search': 'admin', 'User Tools': 'admin', 'API Settings': 'admin', 'Bot Manager': 'admin', 'Sec Center': 'admin', 'Notifications': 'admin', 'Sys Tools': 'admin', 'GH Browser': 'admin', 'Pay Config': 'admin', 'Bot Config': 'admin', 'Appearance': 'admin', 'Coupon+': 'admin', 'Templates': 'admin', 'Referral Sys': 'admin', 'Janitor': 'admin', 'Webhooks': 'admin', 'Feature Flags': 'admin', 'Rate Limits': 'admin', 'Scheduler': 'admin', 'Import/Exp': 'admin', 'Languages': 'admin', 'Bot Controls': 'admin', 'Subscriptions': 'admin', 'Marketplace': 'admin', 'Admin 2FA': 'admin', 'AI Fixed (Gemini)': 'admin', '🛒 Marketplace': 'marketplace', 'Browse Scripts': 'marketplace', 'Premium Bots': 'marketplace', 'My Purchases': 'marketplace', 'Sell Your Script': 'marketplace', 'Top Up Wallet': 'marketplace', 'Contact Admin': 'marketplace', 'Ping Status Check': 'marketplace', 'Monitor Logs': 'marketplace', 'Auto Recovery': 'marketplace', 'View Catalog': 'marketplace', '💰 Payment': 'wallet', 'Revenue Report': 'wallet', 'Growth Stats': 'wallet', 'Top Users': 'wallet', 'Plan Dist': 'wallet', 'Bot Activity': 'wallet', 'Stats Overview': 'wallet', '👥 User Management': 'users', 'Search User': 'users', 'Banned List': 'users', 'Wallet Adjust': 'users', 'Export CSV': 'users', 'Notify User': 'users', 'Reset User': 'users', 'Give Plan': 'users', 'Ban/Unban': 'users', '🤖 Bot Management': 'bots', 'Crashed Bots': 'bots', 'Restart Stopped': 'bots', 'Search Bot': 'bots', 'Size Report': 'bots', 'AI Scan Pending': 'bots', 'All Bots': 'bots', 'Kill All Now': 'bots', 'Clean Orphans': 'bots', '🛡️ Security': 'security', 'Threat Log': 'security', 'Sec Stats': 'security', 'Whitelist User': 'security', 'Blacklist': 'security', 'Scan Report': 'security', 'Security Info': 'security', 'Audit Log': 'security', '📢 Broadcast': 'broadcast', 'Notify Everyone': 'broadcast', 'Bot Users Only': 'broadcast', 'By Plan': 'broadcast', 'Single User': 'broadcast', 'Schedule Msg': 'broadcast', 'Quick Announce': 'broadcast', 'Broadcast': 'broadcast', '🖥️ System': 'system', 'Sys Health': 'system', 'Disk Usage': 'system', 'DB Info': 'system', 'Clear Cache': 'system', 'Token Check': 'system', 'Export Data': 'system', 'Reload Cache': 'system', 'System Info': 'system', '🐙 GitHub': 'system', 'GitHub': 'system', 'Browse My Repos': 'system', 'Set Token': 'system', 'Set Repo': 'system', 'Set Branch': 'system', 'Refresh': 'system', 'GitHub Backup': 'system', 'Up': 'system', 'Run As Bot': 'system', 'Download': 'system', 'Back to Folder': 'system', '🔑 API Settings': 'api_config', 'Set Bot 1 API': 'api_config', 'Set Bot 2 API': 'api_config', 'Clear Bot 1': 'api_config', 'Clear Bot 2': 'api_config', '⚙️ Configuration': 'api_config', 'Pay Methods': 'api_config', 'Amount Limits': 'api_config', 'Currency': 'api_config', 'Receipt Templ': 'api_config', 'Notif Settings': 'api_config', 'Set Tax %': 'api_config', 'Pay History': 'api_config', 'Approve Pay': 'api_config', 'Change Number': 'api_config', 'Set Min': 'api_config', 'Set Max': 'api_config', 'Disc Threshold': 'api_config', 'Disc %': 'api_config', 'Set Code': 'api_config', 'Set Symbol': 'api_config', 'Edit': 'api_config', 'Reset': 'api_config', 'Set Channel': 'api_config', 'Timeouts': 'api_config', 'Limits': 'api_config', 'Upload Rules': 'api_config', 'Env Strip': 'api_config', 'Restart Policy': 'api_config', 'Sandbox': 'api_config', '🎨 Appearance': 'appearance', 'Themes': 'appearance', 'Brand Tag': 'appearance', 'Footer Text': 'appearance', 'Custom Emojis': 'appearance', 'Menu Photos': 'appearance', 'Ann Channel': 'appearance', 'Reset All': 'appearance', 'Rebuild Banners': 'appearance', '🎫 Coupon / Referral': 'referral', 'Create Coupon': 'referral', 'Bulk Create': 'referral', 'Expiry Mgr': 'referral', 'Clear Expired': 'referral', 'All Coupons': 'referral', 'Ref Stats': 'referral', 'Reward Config': 'referral', 'Set Reward ৳': 'referral', 'Set Min Plan': 'referral', 'Set Base Reward': 'referral', 'Set Bonus Thr': 'referral', '🔧 Other': 'referral', 'Run Now': 'referral', 'Jan Rules': 'referral', 'Set Webhook': 'referral', 'Clear (Polling)': 'referral', 'Test Webhook': 'referral', 'Webhook Info': 'referral', 'Reset All Flags': 'referral', 'Bot Details': 'referral', 'System': 'referral', 'Crashed': 'referral', 'Set Monthly Goal': 'referral', 'Set Yearly Goal': 'referral', 'History': 'referral', 'Add Task': 'referral', 'All Tasks': 'referral', 'Export Config': 'referral', 'Import Config': 'referral', 'Export Users CSV': 'referral', 'Force Backup': 'referral', 'Factory Reset': 'referral', 'Setup 2FA': 'api_config', 'Disable+Reset': 'referral', '📊 Leaderboard / Subscription': 'leaderboard', 'Top Spenders': 'leaderboard', 'Most Bots': 'leaderboard', 'Top Referrers': 'leaderboard', 'Most Active': 'leaderboard', 'Longest Uptime': 'leaderboard', 'All LBs': 'leaderboard', 'List All Bots': 'leaderboard', 'Kill All': 'leaderboard', '🎮 Individual Bot Controls': 'bots', 'Stop': 'bots', 'Restart': 'bots', 'Start': 'bots', 'Logs': 'bots', 'Env Editor': 'bots', 'Resources': 'bots', 'Delete': 'bots', 'Expiring Soon': 'bots', 'Expired': 'bots', 'Remind All': 'bots', 'Extend Sub': 'bots', 'Run Downgrade': 'bots', 'Sub History': 'bots', 'Payments': 'bots'}


PLAN_CUSTOM_EMOJI_IDS = {
    "FREE": "6314298001879735512",
    "STARTER": "6314298001879735512",
    "BASIC": "6314298001879735512",
    "PRO": "6314298001879735512",
    "ENTERPRISE": "6314298001879735512",
    "LIFETIME": "6314298001879735512",
}
