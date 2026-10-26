UV ?= uv

.PHONY: sync serve test selftest docker clean

sync:
	$(UV) sync --extra star --extra dev

serve:
	$(UV) run pharmcow serve --reload

test:
	$(UV) run pytest -q

selftest:
	$(UV) run pharmcow selftest

docker:
	docker build -t pharmcow .

clean:
	rm -rf .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
