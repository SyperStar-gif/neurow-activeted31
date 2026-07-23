.PHONY: install run test lint format format-check check docker

install:
	python -m pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .

format-check:
	ruff format --check .

format:
	ruff check . --fix
	ruff format .

check: lint test

docker:
	docker compose up --build
