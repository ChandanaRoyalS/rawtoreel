.PHONY: install test lint sample demo clean

install:
	pip install -e ".[dev]"
	npm install --no-audit --no-fund
	npx hyperframes browser ensure

test:
	ruff check .
	pytest -q

sample:
	rawtoreel sample --out sample/sample.mp4

demo: sample
	rawtoreel intake sample sample/sample.mp4 --title "rawtoreel, end to end" --speaker rawtoreel --role "local run"
	rawtoreel run sample --format youtube --music
	rawtoreel step 3 sample -f reels && rawtoreel step 5 sample -f reels && rawtoreel step 7 sample -f reels

clean:
	rm -rf projects/* outputs/* sample/*.mp4
	touch projects/.gitkeep outputs/.gitkeep
