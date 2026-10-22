"""Concurrent users against a running stack, through nginx.

Each user signs up, uploads a document, waits for it to be indexed, then
asks questions one after another in one chat. All users run at once.
Reports errors and the latency of every answer: time to the first token and
to the end of the stream.

    python scripts/load/load_test.py --users 20 --questions 5

Pair it with scripts/load/fake_llm.py (see deploy/docker-compose.loadtest.yml)
to measure this stack rather than a model provider.
"""

import argparse
import asyncio
import random
import statistics
import time

import httpx

DOCUMENT = (
    "# Operations\n\n## Fleet\n\nThe company operates 214 trucks and six "
    "warehouses. Electric vans make up a growing share of last-mile routes.\n\n"
    "## Safety\n\nLost-time incidents fell to 7 in 2025, down from 12 in 2024. "
    "Forklift training is mandatory every 18 months.\n"
).encode()
QUESTIONS = [
    "How big is the fleet?",
    "How did incidents change?",
    "How often is forklift training?",
    "What share of routes use electric vans?",
    "Summarise the safety section.",
]


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


async def user(client: httpx.AsyncClient, base: str, number: int, questions: int):
    results, errors = [], []
    email = f"load-{number}-{random.randint(0, 10**9)}@example.com"
    signup = await client.post(
        f"{base}/auth/signup",
        json={"email": email, "password": "correct horse battery", "name": "Load"},
    )
    if signup.status_code != 201:
        return results, [f"signup {signup.status_code}"]
    headers = {"X-CSRF-Token": signup.json()["csrf_token"]}
    upload = await client.post(
        f"{base}/documents",
        files=[("files", (f"ops-{number}.md", DOCUMENT, "text/markdown"))],
        headers=headers,
    )
    if upload.status_code != 202:
        return results, [f"upload {upload.status_code}"]
    document_id = upload.json()[0]["id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        status = (await client.get(f"{base}/documents/{document_id}")).json()["status"]
        if status in ("ready", "failed"):
            break
        await asyncio.sleep(0.5)
    if status != "ready":
        return results, [f"indexing ended {status}"]
    chat_id = (await client.post(f"{base}/chats", json={}, headers=headers)).json()[
        "id"
    ]

    for index in range(questions):
        started = time.perf_counter()
        first = None
        done = False
        try:
            async with client.stream(
                "POST",
                f"{base}/chats/{chat_id}/messages",
                json={"question": QUESTIONS[index % len(QUESTIONS)]},
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    errors.append(f"ask {response.status_code}")
                    continue
                event = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        if event == "token" and first is None:
                            first = time.perf_counter() - started
                        elif event == "done":
                            done = True
                        elif event == "error":
                            errors.append(f"answer error {line[6:80]}")
        except httpx.HTTPError as exc:
            errors.append(f"ask {exc.__class__.__name__}")
            continue
        if done and first is not None:
            results.append((first, time.perf_counter() - started))
        elif not errors:
            errors.append("stream ended without done")
    return results, errors


async def main(base: str, users: int, questions: int) -> None:
    limits = httpx.Limits(max_connections=users * 2)
    started = time.perf_counter()
    clients = [httpx.AsyncClient(timeout=120, limits=limits) for _ in range(users)]
    outcomes = await asyncio.gather(
        *(user(c, base, n, questions) for n, c in enumerate(clients))
    )
    for client in clients:
        await client.aclose()
    elapsed = time.perf_counter() - started

    answers = [r for results, _ in outcomes for r in results]
    errors = [e for _, errs in outcomes for e in errs]
    first = [a[0] for a in answers]
    total = [a[1] for a in answers]
    print(f"users={users} questions/user={questions} wall={elapsed:.1f}s")
    print(f"answers={len(answers)} errors={len(errors)} {sorted(set(errors))[:5]}")
    if answers:
        print(
            f"first token: p50 {statistics.median(first):.2f}s "
            f"p95 {percentile(first, 0.95):.2f}s max {max(first):.2f}s"
        )
        print(
            f"full answer: p50 {statistics.median(total):.2f}s "
            f"p95 {percentile(total, 0.95):.2f}s max {max(total):.2f}s"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080/api")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--questions", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.base, args.users, args.questions))
