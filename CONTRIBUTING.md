# Contributing to Floe

We welcome contributions to **Floe** (formerly GP_ANA)! Here's how you can help:

## Getting Started

1. **Fork the repository** on GitHub (`https://github.com/Leo-luxy/Floe`)
2. **Clone your fork** to your local machine
3. **Create a new branch** for your feature or bug fix
4. **Make your changes** and verify all unit tests pass
5. **Submit a pull request** with a clear description of your changes

## Contribution Guidelines

### Code Style & Safety
- Follow Python's PEP 8 style guide and keep module responsibilities clear.
- Never commit personal API keys, Tushare tokens, `config.py`, `trading_records.py`, or local market data under `data/`.
- Ensure backward compatibility across macOS, Windows, and Linux (`app_paths.py` handles source vs. packaged user-data paths).

### Running Regression Tests
Before submitting a pull request, run the full unit test suite (309+ tests):

```bash
python -m unittest discover -s tests -t .
```

### Reporting Issues & Feature Requests
- Open an issue on [GitHub Issues](https://github.com/Leo-luxy/Floe/issues) or email **luleo856@gmail.com**.
- Include your OS, installation method (Desktop `.dmg`/`.exe`/`.AppImage`, Homebrew, npm, or Source), steps to reproduce, screenshots, and `floe --doctor` output if applicable.

## Development Workflow

1. **Setup development environment**:
   ```bash
   git clone https://github.com/your-username/Floe.git
   cd Floe
   pip install -r requirements.txt
   ```

2. **Create a new branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes and run tests**:
   ```bash
   python -m unittest discover -s tests -t .
   ```

4. **Commit and push to your fork**:
   ```bash
   git add .
   git commit -m "feat: concise description of your change"
   git push origin feature/your-feature-name
   ```

5. **Open a Pull Request** on GitHub.

Thank you for contributing to **Floe**!
