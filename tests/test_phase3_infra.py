"""Phase 3 infra test: confirms the JiraBaseUrl parameter added for the real
handler is wired through to the function's environment, and that it's a
plain parameter (not another Secrets Manager ARN) since a base URL isn't
sensitive."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "infra" / "template.yaml"


def _load_template_as_dict() -> dict:
    class _PassThroughLoader(yaml.SafeLoader):
        pass

    def _construct_any(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _PassThroughLoader.add_multi_constructor("!", _construct_any)
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return yaml.load(f, Loader=_PassThroughLoader)


def test_jira_base_url_parameter_exists_and_is_not_a_secret_arn():
    doc = _load_template_as_dict()
    param = doc["Parameters"]["JiraBaseUrl"]
    assert param["Type"] == "String"
    # Must NOT use the secretsmanager ARN pattern - it's a plain URL, not a secret.
    assert "secretsmanager" not in param.get("AllowedPattern", "")


def test_jira_base_url_is_wired_to_function_environment():
    doc = _load_template_as_dict()
    env_vars = (
        doc["Resources"]["AttachmentSyncFunction"]["Properties"]
        .get("Environment", {})
        .get("Variables", doc["Globals"]["Function"]["Environment"]["Variables"])
    )
    assert "JIRA_BASE_URL" in env_vars
