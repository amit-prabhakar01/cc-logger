.PHONY: install test lint clean logs-clean help

help:
	@echo ""
	@echo "  cc-logger · Available commands"
	@echo ""
	@echo "  make install      Install cc-logger into the current project"
	@echo "  make test         Run unit tests"
	@echo "  make lint         Run ruff linter on hook script"
	@echo "  make logs-clean   Delete all session logs (keeps examples/)"
	@echo "  make clean        Remove __pycache__ and .pyc files"
	@echo ""

install:
	@bash install.sh

test:
	@python3 -m pytest tests/ -v

lint:
	@command -v ruff >/dev/null 2>&1 && ruff check .claude/hooks/log_session.py || \
	  python3 -m py_compile .claude/hooks/log_session.py && echo "Syntax OK"

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned."

logs-clean:
	@echo "This will delete all files in ./logs/ (examples/ will NOT be affected)."
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] && \
	  find logs/ -mindepth 1 -not -name '.gitkeep' -exec rm -rf {} + 2>/dev/null; \
	  echo "Logs cleared." || echo "Aborted."
