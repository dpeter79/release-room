.DEFAULT_GOAL := help

help:
	@echo "make demo     set up the fictional app on your local Switch server"
	@echo "make poster   start @asc against the fake (leave it running)"
	@echo "make advance  play Apple one step"
	@echo "make reset    start the demo's fake over"
	@echo "make test     run the tests; needs no Switch, Apple account or network"
	@echo "make setup    set it up for your own apps"
demo:
	python3 demo/setup.py
setup:
	python3 setup_app.py
poster:
	python3 demo/setup.py --connect
	python3 asc_poster.py --every 20
advance:
	python3 kit/fake_asc.py advance state/demo-asc.json
reset:
	rm -rf state demo/DemoCam
	python3 demo/setup.py
test:
	python3 tests/test_poster.py
	python3 tests/test_sales.py
	python3 tests/test_lock.py
	python3 tests/test_upload.py
	python3 tests/test_setup.py
	cd kit && python3 test_asc.py
.PHONY: help demo setup poster advance reset test
