import json

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    questions = [
        "Has Neil worked with Flask?",
        "Does Neil know FastAPI?",
    ]
    with TestClient(app) as client:
        responses = [
            client.post("/api/query", json={"question": question}).json()
            for question in questions
        ]
    print(json.dumps(responses, indent=2))


if __name__ == "__main__":
    main()
