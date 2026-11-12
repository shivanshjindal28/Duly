# Shortcuts (macOS / Linux, or Windows with make). Every target is a plain command you can run directly.
# Activate the virtual environment first, or override: make demo-check PYTHON=.venv/bin/python
PYTHON ?= python

.PHONY: seed run test typecheck demo-check generate e2e

seed:        ## reset the database with the 90-day history
	$(PYTHON) scripts/seed.py --reset

run:         ## backend :8000 + frontend :5173
	$(PYTHON) run.py

test:        ## backend tests
	cd backend && $(PYTHON) -m pytest -q

typecheck:
	cd frontend && npm run typecheck

demo-check:  ## the whole demo through the API, green/red table (isolated temp DB, AI offline)
	$(PYTHON) scripts/demo_check.py

generate:    ## regenerate demo/invoices and demo/manifest.json
	$(PYTHON) scripts/generate_invoices.py

e2e:         ## Playwright demo-path smoke test in a real browser (own temp DB and ports)
	cd frontend && npx playwright test
