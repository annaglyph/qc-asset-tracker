import subprocess


def test_cli_help_runs():
    proc = subprocess.run(["qc-crawl", "-h"], capture_output=True)
    assert proc.returncode in (0, 1)  # some CLIs exit 1 on -h; just ensure no crash
    assert proc.stdout or proc.stderr
