import pytest


def pytest_addoption(parser):
    parser.addoption("--run-e2e", action="store_true", default=False, help="Run e2e LLM tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-e2e"):
        skip = pytest.mark.skip(reason="need --run-e2e to run")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip)
