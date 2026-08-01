#!/usr/bin/env python3
"""A small, dependency-light health planning web server.

The API is intentionally stateless: the browser sends the current profile and
plan when it asks for a PDF or a two-week review. This keeps personal data out
of a server-side database for the demo and makes the safety rules auditable.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DISCLAIMER = "本建议由 AI 生成，仅供参考，不构成医疗建议。剧烈运动前请咨询专业人士。"
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 14 * 1024 * 1024


def _as_float(value: Any, label: str, lower: float, upper: float, required: bool = True) -> float | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"请填写{label}。")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}需要是数字。") from exc
    if not lower <= number <= upper:
        raise ValueError(f"{label}应在 {lower:g} - {upper:g} 范围内，请重新输入。")
    return number


def validate_metrics(payload: dict[str, Any], include_height_weight: bool = True) -> dict[str, Any]:
    """Validate user/OCR metrics before they can influence a plan."""
    clean: dict[str, Any] = {}
    if include_height_weight:
        clean["height"] = _as_float(payload.get("height"), "身高（cm）", 120, 230)
        clean["weight"] = _as_float(payload.get("weight"), "体重（kg）", 30, 250)
    else:
        clean["weight"] = _as_float(payload.get("weight"), "新体重（kg）", 30, 250)
    clean["body_fat"] = _as_float(payload.get("body_fat"), "体脂率（%）", 2, 60, required=False)
    clean["muscle"] = _as_float(payload.get("muscle"), "肌肉量（kg）", 10, 120, required=False)
    clean["age"] = _as_float(payload.get("age"), "年龄", 13, 90, required=False)
    if clean.get("age") is not None:
        clean["age"] = int(clean["age"])
    if payload.get("sex") in {"female", "male", "other"}:
        clean["sex"] = payload["sex"]
    return clean


def _injury_flags(injuries: Any) -> set[str]:
    text = " ".join(injuries if isinstance(injuries, list) else [str(injuries or "")]).lower()
    flags: set[str] = set()
    mapping = {
        "knee": ("膝", "knee"),
        "back": ("腰", "背", "back", "椎"),
        "shoulder": ("肩", "shoulder"),
        "ankle": ("踝", "脚", "足", "ankle"),
        "wrist": ("腕", "手腕", "wrist"),
    }
    for key, terms in mapping.items():
        if any(term in text for term in terms):
            flags.add(key)
    if "无" in text or "none" in text:
        flags.clear()
    return flags


def _safe_exercises(flags: set[str]) -> tuple[list[dict[str, Any]], str, str]:
    """Return a safe, comprehensible exercise set for the reported pain areas."""
    warning: list[str] = []
    if flags:
        labels = {"knee": "膝部", "back": "腰背", "shoulder": "肩部", "ankle": "踝足", "wrist": "手腕", "other": "未明确部位"}
        warning = [labels[x] for x in sorted(flags)]
    if "other" in flags:
        return [
            {"name": "腹式呼吸", "sets": 3, "reps": "每组5次慢呼吸", "rest": "30秒"},
            {"name": "关节无痛范围活动", "sets": 2, "reps": "5-8分钟", "rest": "按需"},
        ], "你报告了未明确部位的伤痛。暂不安排负重、冲击或强度训练，请先由专业人士确认可运动范围。", "腹式呼吸 + 无痛范围轻活动 10 分钟"
    lower = [
        {"name": "臀桥（自重）" if "back" not in flags else "侧卧髋外展", "sets": 3, "reps": "12-15次", "rest": "60秒"},
        {"name": "箱式半蹲" if "knee" not in flags else "仰卧脚跟滑动（无痛范围）", "sets": 3, "reps": "10-12次", "rest": "75秒"},
        {"name": "鸟狗式" if "back" not in flags else "死虫式（小幅度）", "sets": 3, "reps": "每侧8-10次", "rest": "45秒"},
    ]
    upper = [
        {"name": "弹力带划船" if "shoulder" not in flags else "靠墙肩胛收缩", "sets": 3, "reps": "12次", "rest": "60秒"},
        {"name": "斜板俯卧撑" if "wrist" not in flags else "前臂墙推", "sets": 3, "reps": "8-12次", "rest": "60秒"},
        {"name": "站姿弹力带下压" if "shoulder" not in flags else "轻阻力外旋", "sets": 3, "reps": "12-15次", "rest": "45秒"},
    ]
    core = [
        {"name": "死虫式" if "back" not in flags else "仰卧呼吸收腹", "sets": 3, "reps": "每侧8次", "rest": "45秒"},
        {"name": "侧桥（屈膝）" if "back" not in flags else "仰卧骨盆中立位保持（无痛）", "sets": 2, "reps": "每侧20-30秒", "rest": "45秒"},
    ]
    if "ankle" not in flags and "knee" not in flags:
        cardio = "快走 20 分钟（能完整说句子）"
    elif "shoulder" in flags:
        cardio = "腹式呼吸 + 无痛范围轻活动 10 分钟"
    else:
        cardio = "坐姿上肢摆臂 10-15 分钟（踝足完全放松）"
    if warning:
        note = "已根据你报告的" + "、".join(warning) + "不适避开跳跃、冲刺和高负荷动作；训练中出现疼痛请立即停止。"
    else:
        note = "训练采用可控自重与弹力带动作；疼痛、眩晕或异常呼吸出现时请立即停止。"
    return lower + upper + core, note, cardio


MEALS_A = [
    {
        "breakfast": "燕麦 50g + 无糖酸奶 200g + 蓝莓 80g（冷藏拌匀）",
        "lunch": "糙米饭 150g + 清蒸鸡胸 130g + 西兰花 200g（少油）",
        "dinner": "番茄豆腐 250g + 清炒虾仁 120g + 小白菜 200g",
        "snack": "苹果 150g + 原味坚果 10g",
    },
    {
        "breakfast": "全麦吐司 70g + 水煮蛋 2个（约100g）+ 小番茄 120g",
        "lunch": "荞麦面 180g + 牛里脊 100g + 彩椒 150g（少油煎）",
        "dinner": "南瓜 200g + 清蒸鳕鱼 150g + 菠菜 200g",
        "snack": "无糖豆浆 250ml",
    },
    {
        "breakfast": "玉米 150g + 低脂奶 250ml + 鸡蛋 1个（水煮）",
        "lunch": "藜麦饭 150g + 黑椒鸡腿肉 130g + 生菜 200g",
        "dinner": "紫薯 160g + 虾仁蒸蛋 200g + 芦笋 180g",
        "snack": "猕猴桃 150g",
    },
    {
        "breakfast": "杂粮粥 300g + 茶叶蛋 1个 + 黄瓜 100g",
        "lunch": "糙米饭 150g + 豆腐烧牛肉 200g + 菌菇 150g",
        "dinner": "土豆 160g + 香煎三文鱼 120g + 芦笋 180g（少油）",
        "snack": "无糖酸奶 150g",
    },
    {
        "breakfast": "燕麦 45g + 低脂奶 250ml + 香蕉 80g",
        "lunch": "全麦意面 180g + 番茄虾仁 150g（少油）",
        "dinner": "玉米 150g + 清炖牛腱 120g + 西葫芦 200g",
        "snack": "橙子 180g + 南瓜子 10g",
    },
    {
        "breakfast": "全麦馒头 80g + 鸡蛋 1个 + 无糖豆浆 250ml",
        "lunch": "荞麦饭 150g + 清蒸鲈鱼 150g + 油麦菜 200g",
        "dinner": "红薯 180g + 鸡胸肉沙拉 150g（橄榄油 5g）",
        "snack": "梨 160g",
    },
    {
        "breakfast": "希腊酸奶 200g + 即食燕麦 40g + 草莓 100g",
        "lunch": "糙米饭 150g + 香煎鸡胸 130g + 西兰花 200g",
        "dinner": "荞麦面 180g + 番茄豆腐 250g + 海带芽 80g",
        "snack": "低脂奶 200ml + 坚果 10g",
    },
]

MEALS_B = [
    {
        "breakfast": "小米粥 300g + 鸡蛋 2个（水煮）+ 生菜 100g",
        "lunch": "藜麦饭 150g + 清蒸鸡胸 130g + 菜花 200g",
        "dinner": "山药 180g + 清炖鲈鱼 150g + 油麦菜 200g",
        "snack": "无糖酸奶 180g + 杏仁 10g",
    },
    {
        "breakfast": "紫薯 160g + 无糖豆浆 250ml + 水煮蛋 1个",
        "lunch": "全麦卷饼 1份（饼 70g）+ 火鸡胸 120g + 生菜 150g",
        "dinner": "糙米饭 130g + 番茄牛肉 150g + 冬瓜 200g",
        "snack": "橙子 180g",
    },
    {
        "breakfast": "玉米 150g + 原味酸奶 180g + 蓝莓 60g",
        "lunch": "荞麦面 180g + 香煎鳕鱼 150g + 菠菜 200g",
        "dinner": "南瓜 200g + 虾仁豆腐 220g + 芹菜 180g",
        "snack": "苹果 150g + 核桃 8g",
    },
    {
        "breakfast": "全麦吐司 70g + 牛油果 40g + 鸡蛋 1个（水煮）",
        "lunch": "糙米饭 150g + 黑椒牛柳 120g + 彩椒 180g（少油）",
        "dinner": "土豆 160g + 清蒸鲫鱼 160g + 小白菜 200g",
        "snack": "无糖豆浆 250ml",
    },
    {
        "breakfast": "杂粮粥 300g + 低脂奶 200ml + 小番茄 100g",
        "lunch": "藜麦饭 150g + 柠檬鸡腿肉 130g + 芦笋 180g",
        "dinner": "红薯 180g + 三文鱼 120g + 生菜沙拉 200g（少油）",
        "snack": "猕猴桃 150g",
    },
    {
        "breakfast": "燕麦 50g + 无糖豆浆 250ml + 香蕉 70g",
        "lunch": "全麦意面 180g + 金枪鱼 120g + 番茄 150g",
        "dinner": "玉米 150g + 鸡胸肉 130g + 菌菇 200g（清炒）",
        "snack": "梨 160g + 南瓜子 10g",
    },
    {
        "breakfast": "山药 150g + 鸡蛋 2个（水煮）+ 黄瓜 100g",
        "lunch": "荞麦饭 150g + 清蒸虾 160g + 西葫芦 200g",
        "dinner": "南瓜 180g + 豆腐 250g + 牛里脊 100g",
        "snack": "原味酸奶 150g",
    },
]


def _meal_with_restrictions(meal: str, restrictions: str) -> str:
    text = (restrictions or "").lower()
    if any(x in text for x in ("奶", "乳糖", "lactose")) and ("奶" in meal or "酸奶" in meal or "豆浆" in meal):
        return meal.replace("无糖酸奶", "无糖豆浆").replace("原味酸奶", "无糖豆浆").replace("低脂奶", "无糖豆浆")
    if any(x in text for x in ("海鲜", "虾", "鱼", "shellfish")) and any(x in meal for x in ("虾", "鱼", "三文鱼", "鳕", "鲈", "鲫")):
        return "鸡胸肉 130g（清蒸）+ 时蔬 200g"
    if any(x in text for x in ("素食", "不吃肉", "vegetarian")) and any(x in meal for x in ("鸡", "牛", "鱼", "虾", "三文鱼", "鳕", "鲈", "鲫", "火鸡")):
        return "北豆腐 220g + 毛豆 80g + 时蔬 200g（少油）"
    return meal


def generate_plan_tool(profile: dict[str, Any], menu_variant: int = 0, intensity_scale: float = 1.0) -> dict[str, Any]:
    """Generate a safe, executable starter plan from a validated profile."""
    menu_variant = int(menu_variant) % 2
    metrics = validate_metrics(profile, include_height_weight=True)
    raw_injury = f"{profile.get('injuries', '')} {profile.get('injury_note', '')}"
    flags = _injury_flags(raw_injury)
    if "其他" in raw_injury and not flags:
        flags.add("other")
    exercises, injury_note, cardio = _safe_exercises(flags)
    weight = metrics["weight"]
    water = round(min(4.0, max(1.2, weight * 0.035)), 1)
    goal = profile.get("goal", "减脂")
    meals = MEALS_B if menu_variant else MEALS_A
    restrictions = str(profile.get("diet", ""))
    meals = [{key: _meal_with_restrictions(value, restrictions) for key, value in day.items()} for day in meals]
    scale = max(0.8, min(1.25, float(intensity_scale)))
    base_minutes = int(35 * scale)
    if goal == "增肌":
        focus = "力量基础 + 足够蛋白"
    elif goal == "维持":
        focus = "全身活动 + 体能维持"
    else:
        focus = "低冲击力量 + 有氧"
    day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    frequency_match = re.search(r"([2-5])", str(profile.get("frequency", "每周 3 次")))
    frequency = int(frequency_match.group(1)) if frequency_match else 3
    active_days = {2: {1, 4}, 3: {0, 2, 4}, 4: {0, 1, 3, 5}, 5: {0, 1, 2, 4, 5}}[frequency]
    preferred_time = str(profile.get("schedule", "")).strip()
    schedule = [preferred_time or "07:30-08:10", preferred_time or "19:00-19:35", preferred_time or "12:30-13:00", preferred_time or "19:00-19:35", preferred_time or "07:30-08:10", preferred_time or "10:00-10:35", "休息 / 轻松散步"]
    workouts: list[dict[str, Any]] = []
    for index, day in enumerate(day_names):
        if index == 6 or index not in active_days:
            recovery_name = "无痛范围轻活动（遵医嘱）" if flags else "轻松散步 + 拉伸"
            workouts.append({"day": day, "time": schedule[index], "focus": "恢复", "duration": "20-30分钟", "exercises": [{"name": recovery_name, "sets": 1, "reps": "20-30分钟", "rest": "按需"}]})
            continue
        if index in (0, 3):
            day_exercises = exercises[:3]
            focus_name = "下肢与核心" if index == 0 else "全身力量"
        elif index in (1, 4):
            day_exercises = exercises[3:6]
            focus_name = "上肢与姿态"
        else:
            day_exercises = exercises[6:]
            focus_name = "核心与稳态有氧"
        if index in (2, 5):
            day_exercises = day_exercises + [{"name": cardio, "sets": 1, "reps": "15-20分钟", "rest": "按心率调整"}]
        workouts.append({"day": day, "time": schedule[index], "focus": focus_name, "duration": f"约{base_minutes}分钟", "exercises": day_exercises})
    return {
        "created_at": date.today().isoformat(),
        "goal": goal,
        "focus": focus,
        "profile": metrics,
        "injuries": profile.get("injuries", "无伤痛"),
        "preferences": {
            "diet": profile.get("diet", "无"),
            "schedule": profile.get("schedule", ""),
            "frequency": profile.get("frequency", "每周 3 次"),
            "sleep": profile.get("sleep", ""),
            "kitchen": profile.get("kitchen", "简单烹饪"),
            "injury_note": profile.get("injury_note", ""),
        },
        "injury_note": injury_note,
        "workouts": workouts,
        "meals": meals,
        "menu_variant": menu_variant,
        "water_liters": water,
        "metrics": [
            "晨起体重（同一台秤、同一时间）",
            "体脂率（如设备可测，观察趋势）",
            "腰围（肚脐水平，厘米）",
            "每周完成训练次数与疼痛评分（0-10）",
        ],
        "review_reminder": "两周后回来填写新体重、体脂率和腰围，我会根据趋势继续调整。",
        "disclaimer": DISCLAIMER,
    }


def evaluate_review(old: dict[str, Any], new_metrics: dict[str, Any]) -> dict[str, Any]:
    old_profile = old.get("profile", {})
    old_weight = float(old_profile.get("weight", 0))
    new_weight = float(new_metrics.get("weight", 0))
    old_fat = old_profile.get("body_fat")
    new_fat = new_metrics.get("body_fat")
    weight_delta = round(new_weight - old_weight, 2)
    fat_delta = round(float(new_fat) - float(old_fat), 2) if old_fat is not None and new_fat is not None else None
    goal = old.get("goal", "减脂")
    if goal == "减脂":
        effective = weight_delta < -1 or (fat_delta is not None and fat_delta < -0.5)
        status = "有效" if effective else "需要调整"
    elif goal == "增肌":
        effective = weight_delta > 0.5 and (fat_delta is None or fat_delta <= 0.2)
        status = "有效" if effective else "需要调整"
    else:
        weight_pct = abs(weight_delta / old_weight * 100) if old_weight else 99
        fat_pct = abs(fat_delta / float(old_fat) * 100) if old_fat and fat_delta is not None else 0
        effective = weight_pct <= 1 and fat_pct <= 1
        status = "维持稳定" if effective else "需要调整"
    return {"status": status, "effective": effective, "weight_delta": weight_delta, "fat_delta": fat_delta, "goal": goal}


def _current_menu_variant(plan: dict[str, Any]) -> int:
    """Recover the menu version, including plans saved before it was persisted."""
    if plan.get("menu_variant") in (0, 1):
        return int(plan["menu_variant"])
    meals = plan.get("meals") or []
    first_breakfast = meals[0].get("breakfast", "") if meals and isinstance(meals[0], dict) else ""
    return 1 if "小米粥" in first_breakfast else 0


def iterate_plan_tool(old_plan: dict[str, Any], new_metrics_payload: dict[str, Any]) -> dict[str, Any]:
    new_metrics = validate_metrics(new_metrics_payload, include_height_weight=False)
    review = evaluate_review(old_plan, new_metrics)
    profile = dict(old_plan.get("profile", {}))
    profile.update(old_plan.get("preferences", {}))
    profile.update({key: value for key, value in new_metrics.items() if value is not None})
    profile.update({"goal": old_plan.get("goal", "减脂"), "injuries": old_plan.get("injuries", "无伤痛")})
    current_menu_variant = _current_menu_variant(old_plan)
    menu_preference = new_metrics_payload.get("menu_preference", "refresh")
    if review["effective"]:
        if menu_preference == "keep":
            next_plan = generate_plan_tool(profile, menu_variant=current_menu_variant)
            previous_meals = old_plan.get("meals")
            if isinstance(previous_meals, list) and previous_meals:
                next_plan["meals"] = [dict(day) for day in previous_meals if isinstance(day, dict)]
            next_plan["coach_note"] = "趋势达到阶段目标，保留训练框架，并按你的选择继续使用当前菜单。"
            review["menu_choice"] = "继续当前菜单"
        else:
            next_plan = generate_plan_tool(profile, menu_variant=1 - current_menu_variant)
            next_plan["coach_note"] = "趋势达到阶段目标，保留训练框架，并按你的选择更换整周菜单。"
            review["menu_choice"] = "更换整周菜单"
    else:
        next_plan = generate_plan_tool(profile, menu_variant=1 - current_menu_variant, intensity_scale=1.1)
        if new_metrics_payload.get("adherence") == "low":
            next_plan["coach_note"] = "当前趋势未达到目标，主要优先处理执行难度：保留短时训练并更换菜单，先把完成率提高到 70% 以上。"
            review["reason"] = "执行率偏低"
        else:
            next_plan["coach_note"] = "当前趋势未达到目标，可能与摄入估算或代谢适应有关；下一周期增加约10%训练密度，并微调餐盘份量。"
            review["reason"] = "需排查摄入估算、睡眠与代谢适应"
    next_plan["review"] = review
    next_plan["disclaimer"] = DISCLAIMER
    return next_plan


def _extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts)


def _call_vision_ocr(data_url: str) -> dict[str, Any]:
    """Optional OpenAI vision OCR. Fails closed so a bad read never becomes data."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置视觉识别服务，请手动输入体重、体脂率和肌肉量。")
    request_body = {
        "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "从体脂秤截图中读取体重、体脂率、肌肉量。只返回 JSON，字段为 weight、body_fat、muscle，读取不到的字段为 null。不要猜测。"},
            {"type": "input_image", "image_url": data_url},
        ]}],
        "max_output_tokens": 200,
    }
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(request_body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("图片识别暂时不可用，请手动输入关键指标。") from exc
    text = _extract_response_text(raw)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise RuntimeError("没有识别到清晰的数字，请手动输入关键指标。")
    try:
        result = json.loads(match.group(0))
        return validate_metrics({"height": 170, **result}, include_height_weight=True) | {"height": None}
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("识别结果未通过数据校验，请手动输入关键指标。") from exc


def generate_pdf_tool(plan: dict[str, Any], output_path: Path) -> Path:
    """Create a polished, multi-page Chinese PDF with a disclaimer on every page."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import BaseDocTemplate, CondPageBreak, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("生成 PDF 需要 reportlab，请先安装 requirements.txt。") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = "HealthUnicode"
    font_candidates = [
        os.environ.get("HEALTH_FONT_PATH", ""),
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/NISC18030.ttf",
    ]
    registered = False
    for font_path in font_candidates:
        if not font_path or not Path(font_path).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            registered = True
            break
        except Exception:
            continue
    if not registered:
        font_name = "STSong-Light"
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        except Exception:
            font_name = "Helvetica"
    page_w, page_h = A4
    navy = colors.HexColor("#18211C")
    green = colors.HexColor("#176B57")
    mint = colors.HexColor("#E8F3EE")
    coral = colors.HexColor("#E8785A")
    pale = colors.HexColor("#F7F8F5")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverKicker", fontName=font_name, fontSize=9, textColor=green, leading=13, spaceAfter=8))
    styles.add(ParagraphStyle(name="CoverTitle", fontName=font_name, fontSize=26, leading=32, textColor=navy, spaceAfter=10))
    styles.add(ParagraphStyle(name="H1CN", fontName=font_name, fontSize=18, leading=24, textColor=navy, spaceBefore=6, spaceAfter=12))
    styles.add(ParagraphStyle(name="H2CN", fontName=font_name, fontSize=12, leading=18, textColor=green, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodyCN", fontName=font_name, fontSize=9.5, leading=16, textColor=colors.HexColor("#334039")))
    styles.add(ParagraphStyle(name="SmallCN", fontName=font_name, fontSize=8, leading=12, textColor=colors.HexColor("#63736B")))
    styles.add(ParagraphStyle(name="CellCN", fontName=font_name, fontSize=7.8, leading=11, textColor=navy))
    styles.add(ParagraphStyle(name="CellWhite", fontName=font_name, fontSize=8, leading=11, textColor=colors.white))
    styles.add(ParagraphStyle(name="Metric", fontName=font_name, fontSize=18, leading=23, textColor=navy))

    def P(text: Any, style: str = "BodyCN") -> Paragraph:
        safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(safe, styles[style])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D9E2DD"))
        canvas.line(18 * mm, 14 * mm, page_w - 18 * mm, 14 * mm)
        canvas.setFont(font_name, 7)
        canvas.setFillColor(colors.HexColor("#6F7B75"))
        canvas.drawString(18 * mm, 9 * mm, DISCLAIMER)
        canvas.drawRightString(page_w - 18 * mm, 9 * mm, f"{doc.page:02d}")
        canvas.restoreState()

    doc = BaseDocTemplate(str(output_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=17 * mm, bottomMargin=21 * mm, title="个人健康计划")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
    story: list[Any] = []
    profile = plan.get("profile", {})
    story += [P("MOTION / 个人健康计划", "CoverKicker"), P("把接下来两周，练成一个可执行的节奏。", "CoverTitle"), P("这是一份根据你的身体数据、目标与生活条件生成的起始计划。请先按 70-80% 的完成度执行，再根据两周反馈调整。", "BodyCN"), Spacer(1, 10 * mm)]
    summary = [[P("目标", "SmallCN"), P("当前体重", "SmallCN"), P("每日饮水", "SmallCN"), P("训练重点", "SmallCN")], [P(plan.get("goal", "减脂"), "Metric"), P(f"{profile.get('weight', '--')} kg", "Metric"), P(f"{plan.get('water_liters', '--')} L", "Metric"), P(plan.get("focus", "全身活动"), "Metric")]]
    table = Table(summary, colWidths=[doc.width / 4] * 4, rowHeights=[9 * mm, 18 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), mint), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9DED4")), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9DED4")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    story += [table, Spacer(1, 8 * mm), P("安全边界", "H2CN"), P(plan.get("injury_note", "训练中出现疼痛、眩晕或异常呼吸时立即停止。"), "BodyCN"), Spacer(1, 5 * mm), P("生成日期：" + str(plan.get("created_at", date.today().isoformat())), "SmallCN"), PageBreak()]
    story += [P("01 / 一周训练计划", "H1CN"), P("每次先热身 5-8 分钟，动作保持可控。组间休息以呼吸恢复为准，疼痛不是训练强度。", "BodyCN"), Spacer(1, 3 * mm)]
    for day in plan.get("workouts", []):
        story.append(P(f"{day.get('day')} · {day.get('time')} · {day.get('focus')} · {day.get('duration')}", "H2CN"))
        rows = [[P("动作", "CellWhite"), P("组数", "CellWhite"), P("次数 / 时间", "CellWhite"), P("休息", "CellWhite")]]
        for exercise in day.get("exercises", []):
            rows.append([P(exercise.get("name", "-"), "CellCN"), P(exercise.get("sets", "-"), "CellCN"), P(exercise.get("reps", "-"), "CellCN"), P(exercise.get("rest", "-"), "CellCN")])
        t = Table(rows, colWidths=[doc.width * 0.47, doc.width * 0.12, doc.width * 0.24, doc.width * 0.17])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8E0DB")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story += [t, Spacer(1, 3 * mm)]
    story += [CondPageBreak(65 * mm), P("02 / 一周饮食计划", "H1CN"), P("重量均为可食部分估算；烹饪以少油、清蒸、水煮为主。对过敏源请以医生或营养师建议为准。", "BodyCN"), Spacer(1, 3 * mm)]
    meal_rows = [[P("日程", "CellWhite"), P("早餐", "CellWhite"), P("午餐", "CellWhite"), P("晚餐", "CellWhite"), P("加餐", "CellWhite")]]
    for i, meals in enumerate(plan.get("meals", [])):
        meal_rows.append([P(f"周{i + 1}", "CellCN"), P(meals.get("breakfast", "-"), "CellCN"), P(meals.get("lunch", "-"), "CellCN"), P(meals.get("dinner", "-"), "CellCN"), P(meals.get("snack", "-"), "CellCN")])
    meal_table = Table(meal_rows, colWidths=[doc.width * 0.1, doc.width * 0.225, doc.width * 0.255, doc.width * 0.255, doc.width * 0.165], repeatRows=1)
    meal_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), coral), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale]), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8E0DB")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [meal_table, Spacer(1, 6 * mm), P("03 / 两周后评估", "H1CN")]
    for metric in plan.get("metrics", []):
        story.append(P("• " + metric, "BodyCN"))
    story += [Spacer(1, 4 * mm), P(plan.get("review_reminder", "两周后回来反馈新数据。"), "H2CN"), P("复盘判定：减脂看体重下降 >1kg 或体脂下降 >0.5%；增肌看体重上升 >0.5kg 且体脂稳定/下降；维持看波动是否在 1% 内。", "BodyCN")]
    doc.build(story)
    return output_path


class Handler(BaseHTTPRequestHandler):
    server_version = "HealthPlanner/1.0"

    def _json(self, payload: dict[str, Any], status: int = HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise ValueError("上传内容过大，请压缩图片后重试。")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求格式不正确。")
        return value

    def do_GET(self):
        if self.path == "/api/health":
            return self._json({"ok": True, "disclaimer": DISCLAIMER})
        if self.path == "/" or self.path == "/index.html":
            return self._file(STATIC / "index.html", "text/html; charset=utf-8")
        if self.path.startswith("/static/"):
            file_path = (STATIC / self.path.removeprefix("/static/")).resolve()
            if STATIC.resolve() in file_path.parents and file_path.is_file():
                content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                return self._file(file_path, content_type)
        self._json({"error": "页面不存在", "disclaimer": DISCLAIMER}, HTTPStatus.NOT_FOUND)

    def _file(self, path: Path, content_type: str):
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        try:
            payload = self._body()
            if self.path == "/api/ocr":
                data_url = str(payload.get("image", ""))
                if not data_url.startswith("data:image/") or ";base64," not in data_url:
                    raise ValueError("请上传 PNG、JPG 或 WEBP 图片。")
                if len(data_url) > MAX_BODY:
                    raise ValueError("图片过大，请压缩后重试。")
                result = _call_vision_ocr(data_url)
                return self._json({"ok": True, "metrics": result, "disclaimer": DISCLAIMER})
            if self.path == "/api/plan":
                plan = generate_plan_tool(payload)
                return self._json({"ok": True, "plan": plan, "disclaimer": DISCLAIMER})
            if self.path == "/api/review":
                plan = iterate_plan_tool(payload.get("plan", {}), payload.get("metrics", {}))
                return self._json({"ok": True, "plan": plan, "disclaimer": DISCLAIMER})
            if self.path == "/api/pdf":
                plan = payload.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("缺少计划内容。")
                out = ROOT / "output" / "pdf" / f"health-plan-{date.today().isoformat()}.pdf"
                generate_pdf_tool(plan, out)
                content = out.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", "attachment; filename=health-plan.pdf")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            self._json({"error": "接口不存在", "disclaimer": DISCLAIMER}, HTTPStatus.NOT_FOUND)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc), "disclaimer": DISCLAIMER}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json({"error": "服务暂时不可用，请稍后重试。", "disclaimer": DISCLAIMER}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args):
        # Keep personal data out of the development server log.
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "4173"))
    STATIC.mkdir(parents=True, exist_ok=True)
    print(f"健康计划助手已启动: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
