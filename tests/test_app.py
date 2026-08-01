import tempfile
import unittest
from pathlib import Path

import app


def profile(**overrides):
    data = {
        "height": 168,
        "weight": 62,
        "body_fat": 24,
        "goal": "减脂",
        "diet": "无",
        "injuries": "无伤痛",
        "schedule": "19:00-19:40",
        "frequency": "每周 3 次",
    }
    data.update(overrides)
    return data


class PlanSafetyTests(unittest.TestCase):
    def test_rejects_implausible_height(self):
        with self.assertRaisesRegex(ValueError, "120 - 230"):
            app.generate_plan_tool(profile(height=300))

    def test_knee_pain_removes_squats_and_impact(self):
        plan = app.generate_plan_tool(profile(injuries="膝部疼痛"))
        names = " ".join(ex["name"] for day in plan["workouts"] for ex in day["exercises"])
        for blocked in ("深蹲", "箱式半蹲", "跳跃", "冲刺", "快走"):
            self.assertNotIn(blocked, names)
        self.assertIn("膝部", plan["injury_note"])

    def test_frequency_controls_active_days(self):
        plan = app.generate_plan_tool(profile(frequency="每周 2 次"))
        active = [day for day in plan["workouts"] if day["focus"] != "恢复"]
        self.assertEqual(len(active), 2)

    def test_review_threshold_for_fat_loss(self):
        old = app.generate_plan_tool(profile(weight=70, body_fat=28))
        review = app.evaluate_review(old, {"weight": 68.9, "body_fat": 27.8})
        self.assertTrue(review["effective"])
        self.assertEqual(review["status"], "有效")

    def test_effective_review_changes_menu(self):
        old = app.generate_plan_tool(profile(weight=70, body_fat=28))
        new = app.iterate_plan_tool(old, {"weight": 68.8, "body_fat": 27.7, "menu_preference": "refresh"})
        self.assertNotEqual(old["meals"][0], new["meals"][0])
        self.assertEqual(old["preferences"]["frequency"], new["preferences"]["frequency"])

    def test_effective_review_can_keep_menu(self):
        old = app.generate_plan_tool(profile(weight=70, body_fat=28))
        new = app.iterate_plan_tool(old, {"weight": 68.8, "body_fat": 27.7, "menu_preference": "keep"})
        self.assertEqual(old["meals"], new["meals"])
        self.assertEqual(new["review"]["menu_choice"], "继续当前菜单")
        self.assertIn("继续使用当前菜单", new["coach_note"])

    def test_pdf_contains_disclaimer(self):
        try:
            import pdfplumber
        except ImportError:
            self.skipTest("pdfplumber is not installed")
        plan = app.generate_plan_tool(profile())
        with tempfile.TemporaryDirectory() as tmp:
            output = app.generate_pdf_tool(plan, Path(tmp) / "plan.pdf")
            with pdfplumber.open(output) as pdf:
                self.assertGreaterEqual(len(pdf.pages), 2)
                for page in pdf.pages:
                    self.assertIn(app.DISCLAIMER, page.extract_text())


if __name__ == "__main__":
    unittest.main()
