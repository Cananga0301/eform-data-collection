.PHONY: build up up-d down dev logs shell db-shell clean test lint format

build:
	docker-compose build

up:
	docker-compose up

up-d:
	docker-compose up -d

down:
	docker-compose down

dev:
	docker-compose up --build

logs:
	docker-compose logs -f

logs-web:
	docker-compose logs -f eform

logs-db:
	docker-compose logs -f postgres

shell:
	docker-compose exec eform bash

db-shell:
	docker-compose exec postgres psql -U eform_user -d eform_data

poetry-install:
	docker-compose exec eform poetry install

poetry-add:
	docker-compose exec eform poetry add $(package)

poetry-add-dev:
	docker-compose exec eform poetry add --group dev $(package)

db-migrate:
	docker-compose exec eform poetry run alembic revision --autogenerate -m "$(message)"

db-upgrade:
	docker-compose exec eform poetry run alembic upgrade head

db-downgrade:
	docker-compose exec eform poetry run alembic downgrade -1

streamlit:
	poetry run streamlit run src/streamlit_app.py

sync:
	poetry run python sync.py

test:
	docker-compose exec eform poetry run pytest

test-cov:
	docker-compose exec eform poetry run pytest --cov=src

lint:
	docker-compose exec eform poetry run flake8 src

format:
	docker-compose exec eform poetry run black src

clean:
	docker-compose down -v
	docker system prune -f

clean-all:
	docker-compose down -v --rmi all
	docker system prune -a -f

help:
	@echo "Available commands:"
	@echo "  build        - Build Docker images"
	@echo "  up           - Start services"
	@echo "  up-d         - Start services in background"
	@echo "  down         - Stop services"
	@echo "  dev          - Start with live rebuild"
	@echo "  shell        - Open shell in eform container"
	@echo "  db-shell     - Open psql in postgres container"
	@echo "  db-migrate   - Generate Alembic migration (message=...)"
	@echo "  db-upgrade   - Apply all pending migrations"
	@echo "  streamlit    - Run Streamlit UI locally"
	@echo "  sync         - Run sync.py manually"
	@echo "  test         - Run test suite"
	@echo "  clean        - Remove containers and volumes"
