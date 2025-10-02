from fastapi import FastAPI

app = FastAPI(title="Crypto Matching Engine")

@app.get("/health")
def health():
    return {"status": "ok"}
