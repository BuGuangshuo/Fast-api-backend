from app.utils import get_logger

logger = get_logger(__name__)


def test_hello(hello_message: str) -> None:
    assert hello_message == "hello test"
    logger.info(hello_message)
