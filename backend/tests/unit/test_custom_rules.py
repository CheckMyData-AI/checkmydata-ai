import tempfile
from pathlib import Path

from app.knowledge.custom_rules import CustomRulesEngine


class TestCustomRules:
    def test_load_from_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CustomRulesEngine(rules_dir=tmpdir)
            rules = engine.load_rules()
            assert rules == []

    def test_load_markdown_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "business_logic.md"
            rule_file.write_text("# Revenue Metrics\n\nRevenue = price * quantity")

            engine = CustomRulesEngine(rules_dir=tmpdir)
            rules = engine.load_rules()
            assert len(rules) == 1
            assert rules[0].name == "business_logic"
            assert rules[0].format == "markdown"
            assert "Revenue" in rules[0].content

    def test_load_yaml_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "naming.yaml"
            rule_file.write_text("tables:\n  users: 'Main user table'\n")

            engine = CustomRulesEngine(rules_dir=tmpdir)
            rules = engine.load_rules()
            assert len(rules) == 1
            assert rules[0].format == "yaml"

    def test_rules_to_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "rule1.md").write_text("Content 1")
            (Path(tmpdir) / "rule2.md").write_text("Content 2")

            engine = CustomRulesEngine(rules_dir=tmpdir)
            rules = engine.load_rules()
            context = engine.rules_to_context(rules)
            assert "Custom Rules" in context
            assert "Content 1" in context
            assert "Content 2" in context

    def test_empty_rules_context(self):
        engine = CustomRulesEngine(rules_dir="/nonexistent")
        context = engine.rules_to_context([])
        assert context == ""

    def test_project_rules_dir(self):
        with (
            tempfile.TemporaryDirectory() as global_dir,
            tempfile.TemporaryDirectory() as project_dir,
        ):
            (Path(global_dir) / "global.md").write_text("Global rule")
            (Path(project_dir) / "project.md").write_text("Project rule")

            engine = CustomRulesEngine(rules_dir=global_dir)
            rules = engine.load_rules(project_rules_dir=project_dir)
            assert len(rules) == 2
