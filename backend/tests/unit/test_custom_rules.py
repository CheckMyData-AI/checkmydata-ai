import tempfile
from pathlib import Path

from app.knowledge.custom_rules import CustomRulesEngine
from app.services.default_rule_template import (
    DEFAULT_RULE_NAME,
    get_default_rule_content,
)


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

    def test_rules_to_context_includes_db_rule_ids(self):
        from app.knowledge.custom_rules import CustomRule

        engine = CustomRulesEngine(rules_dir="/nonexistent")
        rules = [
            CustomRule(
                name="File rule",
                content="From file",
                file_path="/rules/a.md",
                format="markdown",
            ),
            CustomRule(
                name="DB rule",
                content="From database",
                file_path="db:abc-123",
                format="markdown",
            ),
        ]
        context = engine.rules_to_context(rules)
        assert "### File rule" in context
        assert "(id: abc-123)" in context
        assert "### DB rule  (id: abc-123)" in context

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


class TestDefaultRuleTemplate:
    def test_template_is_non_empty(self):
        content = get_default_rule_content()
        assert len(content) > 500

    def test_template_contains_revenue_metrics(self):
        content = get_default_rule_content()
        assert "Revenue" in content
        assert "GMV" in content
        assert "AOV" in content
        assert "ARPU" in content

    def test_template_contains_roi_section(self):
        content = get_default_rule_content()
        assert "ROAS" in content
        assert "CAC" in content

    def test_template_contains_traffic_sources(self):
        content = get_default_rule_content()
        assert "Traffic" in content
        assert "utm_source" in content

    def test_template_contains_payment_methods(self):
        content = get_default_rule_content()
        assert "Payment" in content
        assert "payment_method" in content

    def test_template_contains_engagement_metrics(self):
        content = get_default_rule_content()
        assert "DAU" in content
        assert "MAU" in content

    def test_template_contains_churn_retention(self):
        content = get_default_rule_content()
        assert "Churn" in content
        assert "Retention" in content

    def test_template_contains_query_guidelines(self):
        content = get_default_rule_content()
        assert "LIMIT" in content
        assert "NULL" in content

    def test_default_rule_name(self):
        assert DEFAULT_RULE_NAME == "Business Metrics & Guidelines"
