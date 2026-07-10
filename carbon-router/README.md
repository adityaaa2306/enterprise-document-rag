## Carbon-Aware LLM Router (PoC)

Minimal FastAPI service that recommends the most carbon-efficient server location to process a PDF summarization task. Uses WattTime APIs for grid carbon signals. No real LLM calls.

### Dependencies

```
pip install -r requirements.txt
```

### Environment

Set WattTime credentials (register at `https://api.watttime.org/register`).

On Windows PowerShell:
```
$env:WATTTIME_USERNAME="your_username"
$env:WATTTIME_PASSWORD="your_password"
```

### Run

```
python main.py
```

Or via uvicorn:
```
uvicorn main:app --reload --port 8000
```

### Test

```
curl -X POST "http://localhost:8000/analyze-pdf" -F "file=@test.pdf"
```

### Notes

- WattTime `/v3/region-from-loc` is used by server lat/lon in `servers.json` to derive the grid region.
- Carbon intensity approximation prioritizes `/v3/forecast?horizon_hours=0` for a point estimate; otherwise falls back to mapping the `signal-index` percentile to a plausible 200–700 gCO2/kWh range for a PoC.
- Token estimation assumes 1 token per ~4 characters plus 100 prompt tokens.

### WattTime quick setup

1) Copy settings and edit values:
```
cp settings.py.template settings.py
```

2) Register:
```
python 1-register.py
```

3) Request token:
```
python 2-requesttoken.py
```

4) Make a test request (region lookup + forecast):
```
python 3-makerequest.py
```

5) Run API with live WattTime data:
```
$env:WATTTIME_USERNAME="<from settings>"
$env:WATTTIME_PASSWORD="<from settings>"
$env:USE_WATTTIME="1"
uvicorn main:app --reload --port 8000
```

6) Run API with mock intensities (no external calls):
```
$env:USE_WATTTIME="0"
uvicorn main:app --reload --port 8010
```


