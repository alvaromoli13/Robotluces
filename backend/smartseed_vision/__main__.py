import uvicorn

if __name__ == "__main__":
    uvicorn.run("smartseed_vision.app:app", host="127.0.0.1", port=8000)
