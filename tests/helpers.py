from unittest.mock import MagicMock


# Long enough answer to pass the length validator (needs >50 words)
_DEFAULT_ANSWER = (
    "Photosynthesis is the biological process by which plants, algae, and "
    "some bacteria convert light energy into chemical energy stored as glucose. "
    "This process occurs primarily in the chloroplasts of plant cells, where "
    "chlorophyll absorbs sunlight and uses it to drive the conversion of carbon "
    "dioxide and water into glucose and oxygen [src_001]."
)


def make_mock_llm_response(answer: str = _DEFAULT_ANSWER):
    """
    Builds a mock LiteLLM response object for use in tests.
    The default answer is long enough to pass the length validator
    so no LangGraph retry is triggered during integration tests.
    """
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = (
        f"{answer}\n"
        '{"confidence": 0.88, "used_source_ids": ["src_001"]}'
    )
    mock.usage = MagicMock(prompt_tokens=150, completion_tokens=60)
    return mock