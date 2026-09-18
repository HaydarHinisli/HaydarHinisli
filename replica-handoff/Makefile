.PHONY: run test compile
run:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test:
	pytest -q

compile:
	python -m compileall -q app tests
