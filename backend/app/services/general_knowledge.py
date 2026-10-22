import re
from functools import lru_cache

import httpx

from app.models.query import ChatMessage

FACTUAL_STARTERS = {
    "define",
    "explain",
    "what",
    "when",
    "where",
    "which",
    "who",
}


class LocalGeneralKnowledgeProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base_url: str = "https://api.openai.com/v1",
        chat_model: str = "gpt-4.1-mini",
        local_model: str = "Qwen/Qwen2.5-1.5B-Instruct",
        client=None,
    ) -> None:
        """Create the provider.

        Args:
            client: A ``ChatCompletionClient`` to answer through. Preferred
                over the direct request below because it switches to a
                fallback model when the main one runs out of quota.
        """
        self._client = client
        self._api_key = api_key
        self._api_base_url = api_base_url.rstrip("/")
        self._chat_model = chat_model
        self._local_model = local_model

    def answer(
        self,
        question: str,
        history: list[ChatMessage] | None = None,
    ) -> str:
        if self._client is not None:
            client_answer = self._client_answer(question, history or [])
            if client_answer:
                return client_answer
        elif self._api_key:
            hosted_answer = self._hosted_answer(question, history or [])
            if hosted_answer:
                return hosted_answer
        if _asks_for_links(question):
            return _safe_link_response(question)
        if _looks_factual(question):
            wikipedia_answer = _wikipedia_answer(question)
            if wikipedia_answer:
                return wikipedia_answer
            return (
                "I can't verify that general-knowledge fact with the currently "
                "configured sources, so I won't guess. Configure a hosted model "
                "or an approved factual-search provider to enable verified "
                "general answers."
            )
        tokenizer, model = _load_model(self._local_model)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a concise general-knowledge assistant. Begin with "
                    "a direct answer, then add only the explanation needed. "
                    "Use at most two short paragraphs and do not use a list "
                    "unless the user requests one. For technical concepts, "
                    "define the concept accurately and explain its main "
                    "mechanism. Do not mention uploaded documents. If uncertain, "
                    "state the uncertainty instead of inventing facts."
                ),
            },
            *[
                {"role": message.role.value, "content": message.content}
                for message in (history or [])[-12:]
            ],
            {"role": "user", "content": question},
        ]
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True)
        outputs = model.generate(
            **inputs,
            max_new_tokens=180,
            do_sample=False,
            repetition_penalty=1.1,
            pad_token_id=tokenizer.eos_token_id,
        )
        generated_tokens = outputs[0][inputs["input_ids"].shape[1] :]
        answer = tokenizer.decode(
            generated_tokens,
            skip_special_tokens=True,
        ).strip()
        return answer or "I could not generate a reliable general answer."

    def _client_answer(
        self,
        question: str,
        history: list[ChatMessage],
    ) -> str | None:
        from app.services.llm_client import LLMError

        earlier = "\n".join(
            f"{'User' if message.role.value == 'user' else 'Assistant'}: "
            f"{message.content}"
            for message in history[-12:]
        )
        user = f"{question}"
        if earlier:
            user = f"--- EARLIER IN THIS CONVERSATION ---\n{earlier}\n\n{question}"
        try:
            return (
                self._client.complete_text(
                    system=(
                        "You are Source Intelligence, a chat assistant that answers "
                        "questions about documents the user uploads (PDF, DOCX, "
                        "TXT, Markdown, CSV, JSON, XLSX) with citations, and also "
                        "holds normal conversations. You run on the "
                        f"{self._client.model} model. Answer the user's intent "
                        "directly: short for simple questions, more detail only "
                        "when useful. Never claim that uploaded documents contain "
                        "information. If uncertain about a fact, say so instead of "
                        "inventing it."
                    ),
                    user=user,
                ).strip()
                or None
            )
        except LLMError:
            return None

    def _hosted_answer(
        self,
        question: str,
        history: list[ChatMessage],
    ) -> str | None:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Source Intelligence, a chat assistant that answers "
                    "questions about documents the user uploads (PDF, DOCX, "
                    "TXT, Markdown, CSV, JSON, XLSX) with citations, and also "
                    "holds normal conversations. You run on the "
                    f"{self._chat_model} model. You are helpful and accurate. "
                    "Answer the user's intent directly. Use a short answer for "
                    "simple questions and more detail only when useful. Never "
                    "claim that uploaded documents contain information because "
                    "document-grounded questions are handled by another system. "
                    "If uncertain about a fact, say so instead of inventing it."
                ),
            },
            *[
                {"role": message.role.value, "content": message.content}
                for message in history[-12:]
            ],
            {"role": "user", "content": question},
        ]
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{self._api_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._chat_model,
                        "messages": messages,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return content.strip() or None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None


def _looks_factual(question: str) -> bool:
    first_word = re.findall(r"[a-z]+", question.lower())
    return bool(first_word) and first_word[0] in FACTUAL_STARTERS


def _asks_for_links(question: str) -> bool:
    terms = set(re.findall(r"[a-z]+", question.lower()))
    return bool(terms & {"link", "links", "url", "urls", "website", "websites"})


def _safe_link_response(question: str) -> str:
    lowered = question.lower()
    if "keyboard" in lowered:
        return (
            "A few established mechanical-keyboard brands are Keychron, "
            "Logitech G, Razer, Corsair, and SteelSeries.\n\n"
            "I don't have live product search configured, so I can't verify "
            "current models, prices, or purchase links and won't invent URLs. "
            "Connect an approved search provider to enable reliable live links."
        )
    return (
        "I can help identify what to look for, but live web search is not "
        "configured, so I can't verify current links and won't invent URLs. "
        "Connect an approved search provider to enable reliable live results."
    )


def _wikipedia_answer(question: str) -> str | None:
    headers = {"User-Agent": "SourceIntelligenceRAG/0.1 (local portfolio project)"}
    try:
        with httpx.Client(timeout=8, headers=headers) as client:
            search = client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": question,
                    "srlimit": 1,
                    "format": "json",
                },
            )
            search.raise_for_status()
            results = search.json().get("query", {}).get("search", [])
            if not results:
                return None
            title = results[0]["title"]
            page = client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "redirects": 1,
                    "titles": title,
                    "format": "json",
                },
            )
            page.raise_for_status()
            pages = page.json().get("query", {}).get("pages", {})
            extract = next(iter(pages.values()), {}).get("extract", "").strip()
            if not extract:
                return None
            return (
                f"{_first_sentences(extract, limit=3)}\n\nSource: Wikipedia — {title}"
            )
    except (httpx.HTTPError, ValueError, KeyError, StopIteration):
        return None


def _first_sentences(text: str, *, limit: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(sentences[:limit])


@lru_cache
def _load_model(model_name: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    return (
        AutoTokenizer.from_pretrained(model_name),
        AutoModelForCausalLM.from_pretrained(model_name),
    )
