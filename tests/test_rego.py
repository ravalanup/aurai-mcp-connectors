import subprocess

from tests.conftest import ROOT, needs_opa


@needs_opa
def test_rego_unit_tests_pass():
    done = subprocess.run(["opa", "test", str(ROOT / "policy")], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


@needs_opa
def test_rego_is_formatted():
    done = subprocess.run(
        ["opa", "fmt", "--fail", "-d", str(ROOT / "policy" / "aurai")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout
