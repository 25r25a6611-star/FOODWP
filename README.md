# FoodLoop Campus

A small full-stack MVP for sharing campus surplus food, suggesting eligible recipients, reserving listings, confirming handovers with a one-time code, and tracking impact.

## Stack
- **Frontend:** HTML, CSS, vanilla JavaScript
- **Backend:** Python + FastAPI
- **Database:** SQLite, initialized automatically on first run

## Run locally
Requires Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://127.0.0.1:8000. Interactive API documentation: http://127.0.0.1:8000/docs.

## Demo workflow
1. Publish a listing with portions, declared allergens, preparation time, storage and pickup deadline.
2. View suggested recipient groups.
3. Reserve a listing and receive a one-time pickup code.
4. Enter the code to record the handover.
5. Review the live impact statistics or export listing data as CSV.

## API overview
- `GET /api/health`
- `GET /api/listings`
- `POST /api/listings`
- `GET /api/listings/{id}/matches`
- `POST /api/listings/{id}/reserve`
- `POST /api/listings/{id}/confirm`
- `GET /api/reports/impact`

## Important limitations
This is a student/demo MVP, not a production food-safety or logistics system. Recipient profiles are illustrative examples, not verified organizations. Always verify handling, allergens and pickup feasibility. Authentication and production-grade authorization are not included; add these before any real deployment.
