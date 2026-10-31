PY ?= python

.PHONY: demo test eval data

demo:
	$(PY) -m intake.demo

test:
	$(PY) -m pytest

eval:
	$(PY) -m intake.eval

data:
	$(PY) scripts/generate_data.py
