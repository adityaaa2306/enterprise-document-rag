from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from carbon_calculator import analyze_pdf_carbon_impact


app = FastAPI(title="Carbon-Aware LLM Router (PoC)")


@app.post("/analyze-pdf")
async def analyze_pdf(file: UploadFile = File(...)):
    try:
        result = await analyze_pdf_carbon_impact(file)
        print(result)
        return JSONResponse(content=result)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:  
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)


