from dataclasses import dataclass, field

from app.services.adaptive_retriever import AdaptiveTopKRetriever


@dataclass
class RecordingRetriever:
    requested_top_k: list[int] = field(default_factory=list)

    def search(self, query: str, *, top_k: int = 3) -> list:
        self.requested_top_k.append(top_k)
        return []


def test_direct_lookup_uses_one_result() -> None:
    base = RecordingRetriever()

    AdaptiveTopKRetriever(base).search("Which college does Neil attend?")

    assert base.requested_top_k == [1]


def test_synthesis_uses_four_results() -> None:
    base = RecordingRetriever()

    AdaptiveTopKRetriever(base).search("Describe the diabetes project.")

    assert base.requested_top_k == [4]


def test_school_question_uses_two_education_records() -> None:
    base = RecordingRetriever()

    AdaptiveTopKRetriever(base).search("Which school did Neil attend?")

    assert base.requested_top_k == [2]
