import pytest


@pytest.fixture
def hello_message() -> str:
    return "hello test"
