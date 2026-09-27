.PHONY: install data sample summary test lint clean

install:            ## install the package with dev tools
	pip install -e ".[dev]"

data:               ## run the full pipeline on your own export (data/raw/strava_export)
	runlab all

sample:             ## generate the synthetic export and run the pipeline on it
	python scripts/make_sample_export.py data/raw/sample_export
	runlab --config config.sample.yaml all

summary:            ## headline numbers from your warehouse
	runlab summary

test:
	pytest -q

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts

clean:              ## delete derived data (never touches data/raw/strava_export)
	rm -rf data/interim/* data/warehouse/* data/raw/sample_export
	touch data/interim/.gitkeep data/warehouse/.gitkeep
