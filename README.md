# RouterGuard 🛡️

**Know the moment a stranger joins your home network.**

RouterGuard monitors the devices connected to your router, detects unknown devices the moment they appear, and alerts you — by sound, desktop notification, Telegram, email, or webhook. It keeps a full history in SQLite, tracks internet outages, and serves an Arabic RTL web dashboard.

Built with Python, Selenium, Flask, and SQLite. Includes a demo mode with fake data, so you can try everything without touching your router.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

![RouterGuard dashboard — demo data](Dashboard%20demo.png)

*The Arabic RTL dashboard in demo mode — 3 devices online, one unknown device flagged.*

## Features

- **Intruder detection** — periodic scans of the router's DHCP client table; devices are classified as allowed / visitor / unknown / blocked
- **Instant new-device alerts** with the device's manufacturer (offline MAC vendor / OUI lookup)
- **MAC spoofing detection** — warns when a known device name appears with a different MAC address
- **Departure tracking** — when a device leaves, a `device_left` event is logged with the exact timestamp
- **Blocklist + night guard** — block devices by MAC, and get high-priority alerts (or auto-block) for unknown devices at night
- **Internet watchdog** — gateway/DNS ping checks, an outage log with durations, uptime percentage, and optional periodic speed tests
- **Multi-channel alerts** — sound, desktop, Telegram (including remote commands: `/status` `/scan` `/devices` `/block`), email, webhook — with escalation repeats until you acknowledge critical alerts
- **Reports** — automatic daily security report, with CSV / HTML / PDF export
- **Web dashboard** — Arabic RTL, dark/light themes, live clock, device table with presence and connection duration, event timeline, and speed chart
- **Background service** — Windows Task Scheduler or Linux systemd; the browser session is reused across scans for speed
- **Demo mode** — explore the whole system with simulated data, no router required

## Quick start

```bash
git clone https://github.com/mostafa77mohmed22-boop/routerguard.git
cd routerguard
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python main.py init     # creates config.yaml from the example
# Edit config.yaml: router URL/credentials and your allowed device names

python main.py demo     # try it first with fake data — no router needed
python main.py scan     # one real scan
python main.py run      # continuous monitoring
```

> ⚠️ Change your router's default admin password. RouterGuard reads your network — it should not be easier to get into than your front door.

## Commands

| Command | What it does |
|---|---|
| `python main.py run` | Continuous monitoring (shared browser session) |
| `python main.py scan` | One scan, then exit |
| `python main.py status` | Status summary and recent events |
| `python main.py devices [--status unknown]` | List recorded devices |
| `python main.py block <mac>` / `unblock <mac>` | Manage the blocklist |
| `python main.py report [--day YYYY-MM-DD] [--pdf]` | Daily report + CSV/HTML export |
| `python main.py dashboard` | Web dashboard (default: http://127.0.0.1:8080) |
| `python main.py demo` | Full demo with simulated data |

## Configuration

Copy `config.example.yaml` to `config.yaml` (`python main.py init` does this). Secrets can stay out of the file entirely via environment variables:

```yaml
router:
  password: env:ROUTER_PASSWORD   # read from the environment
```

Telegram alerts (optional): create a bot with [@BotFather](https://t.me/BotFather), then set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your environment and enable Telegram in `config.yaml`.

## Project structure

```
routerguard/
├── main.py            # Entry point, CLI, wiring
├── core/              # Browser factory, router client, config loading
├── monitors/          # Device, internet, and new-join monitors
├── alerts/            # Pluggable alerts: sound, desktop, Telegram, email, webhook
├── storage/           # SQLite storage, reports, exports
├── dashboard/         # Flask web dashboard (Arabic RTL)
├── service/           # Background installers (Windows / systemd)
├── tools/             # MAC vendor (OUI) lookup
└── tests/             # Unit tests (pytest)
```

## Tests

```bash
pip install pytest
pytest
```

## Roadmap

- Support for more router admin interfaces (contributions welcome — see Troubleshooting in the code for how XPaths are selected)
- English dashboard translation toggle
- Docker packaging

## License

MIT — see [LICENSE](LICENSE).

## Author

Built by [Mostafa Alshibani](https://github.com/mostafa77mohmed22-boop) — Information Systems & CS student at Queen Arwa University, Sana'a, Yemen.
