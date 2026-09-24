.PHONY: test image

test:
	.venv/bin/pytest -q

image:
	docker build -t govee-logger:dev .
