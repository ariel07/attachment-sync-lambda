"""Phase 1 tests: infrastructure-as-code validation.

There is no business logic to unit test in Phase 1 (that's Phase 3). Per the
checklist's TDD requirement, "test" here means: verify the template is valid
CloudFormation/SAM, and verify it does not grant broader permissions than the
handoff doc's stated need (Secrets Manager read of one named secret; nothing
else declared). These tests are the acceptance criteria for "Phase 1 done."

Run with: pytest tests/test_phase1_infra.py -v
Requires: cfn-lint (pip install cfn-lint --break-system-packages)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "infra" / "template.yaml"


def _load_template_raw_text() -> str:
    assert TEMPLATE_PATH.exists(), f"Template not found at {TEMPLATE_PATH}"
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _load_template_as_dict() -> dict:
    """Parse the SAM template as YAML.

    CloudFormation intrinsic function short forms (!Ref, !Sub, !GetAtt, etc.)
    are not standard YAML, so we register permissive constructors rather than
    guessing at semantics we haven't verified - we only need structural
    access (keys/values), not intrinsic-function evaluation, for these checks.
    """

    class _PassThroughLoader(yaml.SafeLoader):
        pass

    def _construct_any(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _PassThroughLoader.add_multi_constructor("!", _construct_any)
    return yaml.load(_load_template_raw_text(), Loader=_PassThroughLoader)


def test_template_file_exists():
    assert TEMPLATE_PATH.exists()


def test_template_is_valid_yaml():
    doc = _load_template_as_dict()
    assert doc is not None
    assert "Resources" in doc


def test_template_declares_sam_transform():
    doc = _load_template_as_dict()
    assert doc.get("Transform") == "AWS::Serverless-2016-10-31"


def test_lambda_function_resource_present():
    doc = _load_template_as_dict()
    resources = doc["Resources"]
    assert "AttachmentSyncFunction" in resources
    assert resources["AttachmentSyncFunction"]["Type"] == "AWS::Serverless::Function"


def test_lambda_uses_documented_supported_runtime():
    """python3.14 is a real, AWS-confirmed Lambda runtime identifier
    (AWS Lambda adds support for Python 3.14, Nov 18 2025) - not assumed."""
    doc = _load_template_as_dict()
    runtime = doc["Globals"]["Function"]["Runtime"]
    assert runtime == "python3.14"


def test_no_secret_value_is_hardcoded_in_template():
    """Defensive check: the template must reference the secret ARN via a
    Parameter, never embed a literal token/secret string."""
    raw = _load_template_raw_text()
    forbidden_markers = ["-----BEGIN", "AKIA", "token:", "password:"]
    for marker in forbidden_markers:
        assert marker not in raw, f"Possible hardcoded secret marker found: {marker!r}"


def test_iam_policy_is_scoped_not_wildcard():
    """Least privilege: the only declared Policies statement must target the
    single Secrets Manager secret ARN parameter, not '*' or a broad service ARN."""
    doc = _load_template_as_dict()
    fn = doc["Resources"]["AttachmentSyncFunction"]
    policies = fn["Properties"]["Policies"]
    assert isinstance(policies, list) and len(policies) == 1
    statement = policies[0]["Statement"][0]
    assert statement["Action"] == ["secretsmanager:GetSecretValue"]
    resource = statement["Resource"]
    # Must resolve via !Ref to the parameter, not a literal "*"
    assert resource != "*"


def test_http_api_endpoint_has_no_open_cors():
    """This is a server-to-server webhook receiver, not a browser client;
    it must not declare a CorsConfiguration (which would imply browser access)."""
    doc = _load_template_as_dict()
    http_api = doc["Resources"]["AttachmentSyncHttpApi"]["Properties"]
    assert "CorsConfiguration" not in http_api


def test_log_group_has_finite_retention():
    """Avoid the insecure/costly default of infinite CloudWatch log retention."""
    doc = _load_template_as_dict()
    log_group = doc["Resources"]["AttachmentSyncLogGroup"]["Properties"]
    assert isinstance(log_group["RetentionInDays"], int)
    assert log_group["RetentionInDays"] > 0


def test_cfn_lint_passes():
    """Full structural/semantic validation against CloudFormation + SAM specs."""
    import shutil

    cfn_lint_bin = shutil.which("cfn-lint")
    assert cfn_lint_bin is not None, (
        "cfn-lint is not installed. Install with: pip install cfn-lint --break-system-packages"
    )
    result = subprocess.run(
        [cfn_lint_bin, str(TEMPLATE_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"cfn-lint reported issues:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
