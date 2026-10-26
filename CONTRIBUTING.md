# Contributing to RouterGuard

Thanks for your interest in improving RouterGuard! Contributions of all sizes are welcome.

## Reporting bugs

Open an issue and include:

- What you ran (`run`, `scan`, `demo`, `dashboard`…) and what you expected to happen
- What actually happened, with the relevant log lines if you have them
- Your router model and firmware version, if the bug involves scanning
- Your OS and Python version

Please remove passwords, public IP addresses, and real MAC addresses of your devices before posting logs or screenshots.

## Adding support for a new router

Router admin pages are the hard part. RouterGuard selects elements with XPath candidates in the router client, so support for a new router UI usually means adding selectors, not rewriting logic:

1. Open your router's connected-devices (DHCP clients) page and inspect its HTML table.
2. Add XPath candidates for your model alongside the existing ones.
3. Test with `python main.py scan` and confirm devices are detected with correct names and MACs.

Pull requests for new router models are especially welcome.

## Development setup

    git clone https://github.com/mostafa77mohmed22-boop/routerguard.git
    cd routerguard
    python -m venv .venv
    # Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
    pip install -r requirements.txt
    pip install pytest
    python main.py demo      # simulated data — no router needed

## Running the tests

    pytest

All tests must pass before a pull request can be merged.

## Code style

- Python 3.10+, standard library first — new dependencies need a clear justification in the PR.
- No real credentials, MAC addresses, or IPs in code, tests, or examples. Use the example values from `config.example.yaml`.
- Keep the dashboard usable in Arabic RTL and in the dark and light themes.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Keep the change focused — one feature or fix per PR.
3. Add or update tests for behavior changes.
4. Describe what you changed and how you tested it.

By contributing, you agree that your contributions are licensed under the MIT License.
